"""
Place at: waste/management/commands/send_deadline_reminders.py

Run daily:
    python manage.py send_deadline_reminders

Preview only (nothing sent, nothing saved):
    python manage.py send_deadline_reminders --dry-run

One-time, BEFORE the first real run: record every currently-due reminder as
"already handled" WITHOUT emailing anyone, so old overdue items don't cause an
email burst. Only future deadlines will produce emails afterwards:
    python manage.py send_deadline_reminders --mark-existing

Covers: Action Plan, Accomplishment Report, Collection.
Emails: 3 days before, 1 day before, and once after the deadline if still not done.
Requires the ReminderLog model (migration 0024).
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from waste.models import (
    Accomplishment, ActionPlan, Collection, ReminderLog,
    generate_due_collections,
)

PLACEHOLDER_DOMAIN = "@swms-carigara.local"


def real(email):
    return bool(email) and not email.lower().endswith(PLACEHOLDER_DOMAIN)


def barangay_emails(barangay):
    if not barangay:
        return []
    qs = User.objects.filter(
        is_active=True, profile__role="user", profile__barangay=barangay
    ).values_list("email", flat=True)
    return [e for e in qs if real(e)]


def admin_emails():
    qs = User.objects.filter(is_active=True).filter(
        Q(is_superuser=True) | Q(profile__role="admin")
    ).values_list("email", flat=True).distinct()
    return [e for e in qs if real(e)]


def stage_for(days_left):
    """
    Catch-up rule: if the command missed a day, the reminder still goes out
    on the next run, because we check "within the window", not "exact day".
      more than 3 days left -> nothing
      2-3 days left         -> "3d"
      0-1 days left         -> "1d"   (includes the deadline day itself)
      past the deadline     -> "overdue"
    """
    if days_left > 3:
        return None
    if days_left >= 2:
        return "3d"
    if days_left >= 0:
        return "1d"
    return "overdue"


class Command(BaseCommand):
    help = "Email reminders: 3 days before, 1 day before, and after a missed deadline."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show what would happen. Sends nothing and saves nothing.",
        )
        parser.add_argument(
            "--mark-existing", action="store_true",
            help="Record all currently-due reminders as handled WITHOUT sending emails.",
        )

    def handle(self, *args, **opts):
        self.dry = opts["dry_run"]
        self.mark = opts["mark_existing"]
        self.count = 0
        today = timezone.localdate()

        # Create the due weekly/monthly collections even if nobody opened the page.
        if not self.dry:
            generate_due_collections(today)

        # Action Plans (target_date) and Accomplishment Reports (due_date):
        # "not done" = no submission_date yet.
        for model, field, label in (
            (ActionPlan, "target_date", "Action Plan"),
            (Accomplishment, "due_date", "Accomplishment Report"),
        ):
            qs = model.objects.filter(
                submission_date__isnull=True, **{f"{field}__isnull": False}
            )
            for obj in qs:
                due = getattr(obj, field)
                days_left = (due - today).days
                stage = stage_for(days_left)
                if stage:
                    self.remind(obj, label, obj.title, due, days_left, stage)

        # Collections: "not done" = status is not Completed.
        # Before the date we only remind while still "Scheduled".
        for c in Collection.objects.filter(scheduled_date__isnull=False).exclude(status="Completed"):
            due = timezone.localtime(c.scheduled_date).date()
            days_left = (due - today).days
            stage = stage_for(days_left)
            # Weekly pickups come around every week - skip the early "3 days
            # before" email for them (day-before and overdue still go out).
            if c.frequency == "Weekly" and stage == "3d":
                continue
            if stage == "overdue" or (stage and c.status == "Scheduled"):
                self.remind(c, "Waste Collection", f"{c.waste_type} - {c.barangay}", due, days_left, stage)

        if self.mark:
            verb = "[dry-run] would mark" if self.dry else "Marked"
            self.stdout.write(self.style.SUCCESS(f"{verb} {self.count} existing item(s) as handled. No emails sent."))
        else:
            verb = "[dry-run] would send" if self.dry else "Sent"
            self.stdout.write(self.style.SUCCESS(f"{verb} {self.count} email(s)."))

    # ------------------------------------------------------------------
    def remind(self, obj, label, title, due, days_left, stage):
        barangay = getattr(obj, "barangay", "") or ""
        due_txt = due.strftime("%b %d, %Y")

        if stage == "overdue":
            subject = f"[SWMS] OVERDUE {label}: {title}"
            lead = f"The deadline ({due_txt}) has passed and this {label.lower()} is still not done."
            to = list(dict.fromkeys(barangay_emails(barangay) + admin_emails()))
        else:
            if days_left == 0:
                when = "TODAY"
            elif days_left == 1:
                when = "tomorrow"
            else:
                when = f"in {days_left} days"
            subject = f"[SWMS] {label} due {when}: {title}"
            lead = f"This {label.lower()} is due {when} ({due_txt}). Please complete it before the deadline."
            to = barangay_emails(barangay)

        body = (
            f"Barangay: {barangay or 'Municipal-wide'}\n"
            f"{label}: {title}\n"
            f"Deadline: {due_txt}\n\n"
            f"{lead}\n"
            "Please log in to SWMS to take action.\n\n- SWMS Carigara"
        )
        self.deliver(obj, stage, subject, body, to)

    def deliver(self, obj, stage, subject, body, to):
        key = dict(model=obj._meta.label, object_id=obj.pk, stage=stage)
        if ReminderLog.objects.filter(**key).exists():
            return  # already sent (or already marked) for this item + stage

        # --mark-existing: remember it, send nothing.
        if self.mark:
            self.count += 1
            if self.dry:
                self.stdout.write(f"  would mark: {subject}")
            else:
                ReminderLog.objects.get_or_create(**key)
            return

        if not to:
            return  # nobody with a real email to notify

        self.count += 1
        if self.dry:
            self.stdout.write(f"  {subject} -> {to}")
            return
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, to, fail_silently=False)
            ReminderLog.objects.get_or_create(**key)
        except Exception as exc:
            # Not logged as sent, so the next daily run tries this stage again.
            self.count -= 1
            self.stderr.write(f"Failed '{subject}': {exc}")