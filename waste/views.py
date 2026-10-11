import calendar
import logging
import time
from decimal import Decimal, InvalidOperation
from datetime import date, datetime, timedelta

from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import authenticate, login as auth_login
from django.contrib.auth.models import User as AuthUser
from django.core.paginator import Paginator
from django.core.mail import send_mail
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.db.models import Sum, Count, Q, Exists, OuterRef
from django.utils import timezone
from django.http import HttpResponse

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from .models import Collection, Complaint, Profile, Accomplishment, ActionPlan, SCMAR, BARANGAY_CHOICES, LoginVerification, RecurringCollectionSchedule, generate_due_collections, week_bounds, WASTE_TYPE_CHOICES, WEEKDAY_CHOICES, month_collection_progress, ensure_month_scmar
from .forms import (
    CollectionForm, CollectionStatusForm, ComplaintForm, ComplaintStatusForm, RegisterForm,
    AccomplishmentForm, ActionPlanForm, ActionPlanSubmissionForm, ActionPlanScheduleForm,
    SCMARForm, SCMARReviewForm, ProfileAvatarForm, ProfileEditForm,
    ConfirmCodeForm, ReviewForm, RecurringCollectionScheduleForm, EmailChangeForm,
)

PAGE_SIZE = 15
logger = logging.getLogger(__name__)


def is_admin(user):
    return user.is_superuser or (hasattr(user, "profile") and user.profile.role == "admin")


def get_user_barangay(user):
    """Returns the barangay a Barangay User is scoped to, or None (unrestricted)."""
    if user.is_superuser:
        return None
    if hasattr(user, "profile") and user.profile.role == "user":
        return user.profile.barangay
    return None


# ---------------------------------------------------------------------------
# Barangay -> MENRO Admin submission/review workflow
#
# The Barangay is always the SENDER/SUBMITTER of Action Plans and
# Accomplishment Reports. MENRO Admin is always the RECEIVER/REVIEWER.
# The Barangay is never the receiver or reviewer of its own submission.
# ---------------------------------------------------------------------------

def get_menro_admin_emails():
    """Email addresses of every active MENRO Admin account."""
    return list(
        AuthUser.objects.filter(is_active=True)
        .filter(Q(is_superuser=True) | Q(profile__role="admin"))
        .exclude(email="")
        .values_list("email", flat=True)
        .distinct()
    )


def notify_menro_of_submission(record, kind, detail_url_name):
    """Notify MENRO Admin that a Barangay submitted an Action Plan / Accomplishment Report."""
    emails = get_menro_admin_emails()
    if not emails:
        return
    submitter = record.submitted_by
    message = (
        f"New {kind} Submission\n\n"
        f"Barangay: {record.barangay}\n"
        f"Submitted By: {submitter.username if submitter else '-'}\n"
        f"{kind}: {record.title}\n"
        f"Submitted: {timezone.localdate().strftime('%b %d, %Y')}\n"
        f"Status: For Review\n\n"
        f"Please log in to SWMS to review this submission."
    )
    try:
        send_mail(
            subject=f"New {kind} Submission - {record.barangay}",
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=emails,
            fail_silently=True,
        )
    except Exception:
        pass


def notify_barangay_of_decision(record, kind):
    """Notify the submitting Barangay user that MENRO Admin approved/rejected their submission."""
    submitter = record.submitted_by
    if not submitter or not submitter.email:
        return
    message = (
        f"Your {kind} \"{record.title}\" submitted to MENRO Admin has been "
        f"{record.review_status}.\n\n"
        f"Reviewed By: MENRO Admin\n"
        f"Review Date: {record.review_date.strftime('%b %d, %Y') if record.review_date else '-'}\n"
        f"Remarks: {record.review_remarks or '-'}\n"
    )
    try:
        send_mail(
            subject=f"Your {kind} was {record.review_status} - {record.title}",
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[submitter.email],
            fail_silently=True,
        )
    except Exception:
        pass


@login_required
def dashboard(request):
    my_barangay = get_user_barangay(request.user)

    collections_qs = Collection.objects.all()
    complaints_qs = Complaint.objects.all()
    accomplishments_qs = Accomplishment.objects.all()
    if my_barangay:
        collections_qs = collections_qs.filter(barangay=my_barangay)
        complaints_qs = complaints_qs.filter(barangay=my_barangay)
        accomplishments_qs = accomplishments_qs.filter(barangay=my_barangay)

    total_weight = collections_qs.aggregate(total=Sum("weight_kg"))["total"] or 0
    total_collections = collections_qs.count()
    total_complaints = complaints_qs.count()
    pending_complaints = complaints_qs.filter(status="Pending").count()
    total_accomplishments = accomplishments_qs.count()
    if my_barangay:
        # Barangay Users follow their collections week by week.
        week_start, week_end = week_bounds(timezone.localdate())
        recent_collections = collections_qs.filter(
            scheduled_date__date__gte=week_start, scheduled_date__date__lte=week_end,
        ).order_by("scheduled_date")[:5]
    else:
        recent_collections = collections_qs[:5]
    recent_complaints = complaints_qs[:5]
    recent_accomplishments = accomplishments_qs[:5]

    context = {
        "total_weight": total_weight,
        "total_collections": total_collections,
        "total_complaints": total_complaints,
        "pending_complaints": pending_complaints,
        "total_accomplishments": total_accomplishments,
        "recent_collections": recent_collections,
        "recent_complaints": recent_complaints,
        "recent_accomplishments": recent_accomplishments,
        "my_barangay": my_barangay,
    }
    return render(request, "waste/dashboard.html", context)



# "Next week" only becomes available from this weekday at 12:00 AM
# (0 = Monday ... 5 = Saturday, 6 = Sunday). Change to 6 for Sunday.
NEXT_WEEK_UNLOCK_WEEKDAY = 5


def latest_visible_week_start(today):
    """Monday of the furthest week a barangay user may browse to: the current
    week, plus the next one once the unlock day (12 AM) has arrived."""
    monday = today - timedelta(days=today.weekday())
    if today.weekday() >= NEXT_WEEK_UNLOCK_WEEKDAY:
        return monday + timedelta(days=7)
    return monday


def collection_local_day(c):
    """Local calendar day a collection belongs to (scheduled, else collected)."""
    stamp = c.scheduled_date or c.date_collected
    return timezone.localtime(stamp).date() if stamp else None


def barangay_can_edit(c, today=None):
    """Barangay users may only edit THIS week's collections that are already
    due (scheduled today or earlier). Past weeks and later days are view-only."""
    today = today or timezone.localdate()
    day = collection_local_day(c)
    if day is None:
        return True
    week_start, _ = week_bounds(today)
    return week_start <= day <= today


def group_collections(collections):
    """Combine collections of the same barangay, day and frequency into one
    summary row (one pickup day = one row). Single collections stay as-is.
    Each group exposes the children plus pre-computed combined values."""
    groups = {}
    for c in collections:
        stamp = c.scheduled_date or c.date_collected
        day = timezone.localtime(stamp).date() if stamp else None
        key = (c.barangay, day, c.frequency) if day else ("single", c.pk)
        groups.setdefault(key, []).append(c)

    result = []
    for key, items in groups.items():
        barangay, day, frequency = items[0].barangay, key[1] if key[0] != "single" else None, items[0].frequency
        items.sort(key=lambda c: c.waste_type)
        statuses = {c.status for c in items}
        completed = sum(1 for c in items if c.status == "Completed")
        weights = [c.weight_kg for c in items if c.weight_kg is not None]
        collectors = {c.collector for c in items if c.collector}
        if len(statuses) == 1:
            status = next(iter(statuses))
            status_text = status
        else:
            status = "Ongoing" if "Ongoing" in statuses or completed else "Scheduled"
            status_text = f"{completed} of {len(items)} completed"
        result.append({
            "items": items,
            "first": items[0],
            "is_group": len(items) > 1,
            "count": len(items),
            "barangay": barangay,
            "day": day,
            "scheduled_date": items[0].scheduled_date,
            "frequency": frequency,
            "status": status,
            "status_text": status_text,
            "weight": sum(weights, Decimal("0")) if weights else None,
            "collector": next(iter(collectors)) if len(collectors) == 1 else ("Multiple" if collectors else ""),
            "types": ", ".join(c.waste_type for c in items),
        })
    return result

@login_required
def collection_list(request):
    # Auto-generate due Collections (weekly and monthly) from any active
    # recurring schedules. Cheap no-op once they already exist, so it's safe
    # to run on every page load - no cron or Celery needed for this to work.
    generate_due_collections()

    collections = Collection.objects.all()
    my_barangay = get_user_barangay(request.user)
    if my_barangay:
        collections = collections.filter(barangay=my_barangay)

    barangay = request.GET.get("barangay", "")
    waste_type = request.GET.get("waste_type", "")
    frequency = request.GET.get("frequency", "")
    period = request.GET.get("period", "")
    schedule_day = request.GET.get("day", "")
    if not my_barangay:
        # MENRO Admin filters by barangay, schedule day (Mon-Sun) and month.
        waste_type = ""
        frequency = ""
    else:
        schedule_day = ""
    if barangay and not my_barangay:
        collections = collections.filter(barangay=barangay)
    if schedule_day in {str(n) for n, _ in WEEKDAY_CHOICES}:
        # 0 = Monday ... 6 = Sunday. Django's week_day is 1 = Sunday ... 7 = Saturday.
        collections = collections.filter(scheduled_date__week_day=(int(schedule_day) + 1) % 7 + 1)
    else:
        schedule_day = ""
    if waste_type:
        collections = collections.filter(waste_type=waste_type)
    if frequency in ("Weekly", "Monthly"):
        collections = collections.filter(frequency=frequency)
    else:
        frequency = ""

    week_context = {}
    period_choices = []
    if my_barangay:
        # ---- Barangay User: only their own barangay, shown WEEK BY WEEK ----
        period = ""
        today = timezone.localdate()
        try:
            anchor = date.fromisoformat(request.GET.get("week", ""))
        except ValueError:
            anchor = today
        max_week_start = latest_visible_week_start(today)
        week_start, week_end = week_bounds(anchor)
        if week_start > max_week_start:  # e.g. a hand-edited ?week= URL
            week_start, week_end = week_bounds(max_week_start)
        collections = collections.filter(
            Q(scheduled_date__date__gte=week_start, scheduled_date__date__lte=week_end) |
            Q(scheduled_date__isnull=True, date_collected__date__gte=week_start, date_collected__date__lte=week_end)
        ).order_by("scheduled_date", "waste_type")

        # The month this week belongs to (the week's Thursday decides, like
        # ISO weeks do) and its roll-up. This is the same data that flows
        # into the barangay's monthly SCMAR.
        ref_day = week_start + timedelta(days=3)
        month_start = date(ref_day.year, ref_day.month, 1)
        month_end = date(ref_day.year, ref_day.month, calendar.monthrange(ref_day.year, ref_day.month)[1])
        month_qs = Collection.objects.filter(barangay=my_barangay).filter(
            Q(scheduled_date__date__gte=month_start, scheduled_date__date__lte=month_end) |
            Q(scheduled_date__isnull=True, date_collected__date__gte=month_start, date_collected__date__lte=month_end)
        )
        month_total = month_qs.count()
        month_completed = month_qs.filter(status="Completed").count()
        month_weight = month_qs.aggregate(total=Sum("weight_kg"))["total"] or 0
        month_scmar = SCMAR.objects.filter(barangay=my_barangay, period_start=month_start).first()
        month_progress = month_collection_progress(my_barangay, month_start)
        week_context = {
            "week_start": week_start,
            "week_end": week_end,
            "prev_week": week_start - timedelta(days=7),
            "next_week": week_start + timedelta(days=7),
            "is_current_week": week_start <= today <= week_end,
            # Next week: step forward through past weeks, but skip the hop onto
            # the current week ("This week" does that) and only reach the
            # upcoming week once it unlocks (Saturday 12 AM by default).
            "can_go_next": (
                (week_start + timedelta(days=7)) < week_bounds(today)[0]
                or (
                    (week_start + timedelta(days=7)) > week_bounds(today)[0]
                    and (week_start + timedelta(days=7)) <= max_week_start
                )
            ),
            "month_label": month_start.strftime("%B %Y"),
            "month_key": month_start.strftime("%Y-%m"),
            "month_total": month_total,
            "month_completed": month_completed,
            "month_weight": month_weight,
            "month_ended": today > month_end,
            "month_scmar": month_scmar,
            "month_progress": month_progress,
        }
    else:
        if period:
            try:
                period_year, period_month = (int(p) for p in period.split("-"))
                collections = collections.filter(
                    scheduled_date__year=period_year, scheduled_date__month=period_month
                )
            except (ValueError, TypeError):
                period = ""

        # Build the Month dropdown: every year that has at least one collection
        # gets all 12 months listed (even months with no data yet), newest
        # year/month first.
        months_qs = Collection.objects.filter(scheduled_date__isnull=False)
        years_with_data = sorted(
            {d.year for d in months_qs.dates("scheduled_date", "year")}, reverse=True
        )
        period_choices = [
            (date(year, month, 1).strftime("%Y-%m"), date(year, month, 1).strftime("%B %Y"))
            for year in years_with_data
            for month in range(12, 0, -1)
        ]

    # Compact summary counts for the current filtered result set - real
    # numbers derived from the same queryset the table renders, never
    # fabricated. Computed before pagination slices it.
    total_count = collections.count()
    completed_count = collections.filter(status="Completed").count()
    ongoing_count = collections.filter(status="Ongoing").count()
    scheduled_count = collections.filter(status="Scheduled").count()
    completed_pct = round((completed_count / total_count) * 100) if total_count else 0

    # MENRO Admin's table lists only Completed collections (the summary cards
    # above still count every status so scheduled/ongoing work stays visible).
    if not my_barangay:
        collections = collections.filter(status="Completed")

    # One row per pickup day: group first, then paginate the groups so a
    # day's collections are never split across pages.
    rows = list(collections)
    if my_barangay:
        today_local = timezone.localdate()
        for c in rows:
            c.can_edit = barangay_can_edit(c, today_local)
    paginator = Paginator(group_collections(rows), PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "collections": page_obj,
        "page_obj": page_obj,
        "barangay_choices": BARANGAY_CHOICES,
        "waste_type_choices": Collection._meta.get_field("waste_type").choices,
        "period_choices": period_choices,
        "selected_barangay": my_barangay or barangay,
        "selected_waste_type": waste_type,
        "selected_frequency": frequency,
        "selected_period": period,
        "selected_day": schedule_day,
        "weekday_choices": WEEKDAY_CHOICES,
        "my_barangay": my_barangay,
        "total_count": total_count,
        "completed_count": completed_count,
        "ongoing_count": ongoing_count,
        "scheduled_count": scheduled_count,
        "completed_pct": completed_pct,
    }
    context.update(week_context)
    return render(request, "waste/collection_list.html", context)


@login_required
def collection_day_detail(request):
    """Details page for a combined row: every collection of one barangay on
    one day (same frequency)."""
    my_barangay = get_user_barangay(request.user)
    barangay = my_barangay or request.GET.get("barangay", "")
    frequency = request.GET.get("frequency", "")
    try:
        day = date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        return redirect("collection_list")

    qs = Collection.objects.filter(barangay=barangay, frequency=frequency)
    if not my_barangay:  # admin lists show Completed collections only
        qs = qs.filter(status="Completed")
    qs = qs.filter(
        Q(scheduled_date__date=day) |
        Q(scheduled_date__isnull=True, date_collected__date=day)
    )
    groups = group_collections(qs)
    if not groups:
        messages.error(request, "No collections found for that day.")
        return redirect("collection_list")
    group = groups[0]
    for c in group["items"]:
        c.can_edit = (not my_barangay) or barangay_can_edit(c)
    if not group["is_group"]:
        return redirect("collection_detail", pk=group["first"].pk)

    completed = sum(1 for c in group["items"] if c.status == "Completed")
    return render(request, "waste/collection_day_detail.html", {
        "group": group,
        "day": day,
        "completed_count": completed,
    })


@login_required
def collection_detail(request, pk):
    collection = get_object_or_404(Collection, pk=pk)
    my_barangay = get_user_barangay(request.user)
    if my_barangay and collection.barangay != my_barangay:
        messages.error(request, "You can only view records for your own barangay.")
        return redirect("collection_list")
    can_edit = (not my_barangay) or barangay_can_edit(collection)
    return render(request, "waste/collection_detail.html", {"collection": collection, "can_edit": can_edit})


@login_required
@user_passes_test(is_admin, login_url="dashboard")
def collection_edit(request, pk):
    collection = get_object_or_404(Collection, pk=pk)
    if request.method == "POST":
        form = CollectionForm(request.POST, instance=collection)
        if form.is_valid():
            form.save()
            messages.success(request, f"Collection #{collection.id} updated successfully.")
            return redirect("collection_list")
    else:
        form = CollectionForm(instance=collection)
    return render(request, "waste/collection_form.html", {"form": form, "editing": True, "collection": collection})


@login_required
@user_passes_test(is_admin, login_url="dashboard")
def collection_delete(request, pk):
    collection = get_object_or_404(Collection, pk=pk)
    if request.method == "POST":
        collection.delete()
        messages.success(request, f"Collection #{pk} deleted.")
        return redirect("collection_list")
    return render(request, "waste/collection_confirm_delete.html", {"collection": collection})


@login_required
def collection_update_status(request, pk):
    collection = get_object_or_404(Collection, pk=pk)
    my_barangay = get_user_barangay(request.user)
    if my_barangay and collection.barangay != my_barangay:
        messages.error(request, "You can only update records for your own barangay.")
        return redirect("collection_list")
    if my_barangay and not barangay_can_edit(collection):
        messages.error(request, "This collection is view-only. Only this week's collections that are already due can be updated.")
        return redirect("collection_detail", pk=collection.pk)

    if request.method == "POST":
        form = CollectionStatusForm(request.POST, instance=collection)
        if form.is_valid():
            updated = form.save(commit=False)
            if updated.status == "Completed" and not updated.date_collected:
                updated.date_collected = timezone.now()
            updated.updated_by = request.user
            updated.save()
            messages.success(request, f"Collection #{collection.id} updated to '{updated.status}'.")
            _auto_create_scmars(request, [updated])
            return redirect("collection_list")
    else:
        form = CollectionStatusForm(instance=collection)

    return render(request, "waste/collection_update.html", {"form": form, "collection": collection})


def _auto_create_scmars(request, collections):
    """
    After a Barangay records collections, check each month they belong to.
    Once 4 weeks of that month are complete (or all of its collections are),
    the month's SCMAR is created automatically and the user is told.
    """
    seen = set()
    for c in collections:
        when = c.scheduled_date or c.date_collected
        if not when:
            continue
        day = timezone.localtime(when).date()
        key = (c.barangay, day.year, day.month)
        if key in seen:
            continue
        seen.add(key)
        scmar, created = ensure_month_scmar(c.barangay, date(day.year, day.month, 1), request.user)
        if created:
            messages.success(
                request,
                f"{scmar.reporting_period} is complete - your SCMAR for that month was created "
                f"automatically with your collection figures. Open it, add your assessment, and save to submit it to MENRO.",
            )


@login_required
def collection_week_input(request):
    """
    Weekly input for Barangay Users. The barangay records how much waste it
    actually collected this week, per waste type, depending on its own trash.
    If MENRO already scheduled a pickup of that type this week, the weight
    completes it; otherwise a new Completed collection is created from what
    the barangay entered. Saving may complete the month and automatically
    create its SCMAR.
    """
    my_barangay = get_user_barangay(request.user)
    if not my_barangay:
        messages.error(request, "Weekly collection input is done by Barangay Users for their own barangay.")
        return redirect("collection_list")

    generate_due_collections()
    today = timezone.localdate()
    try:
        anchor = date.fromisoformat(request.POST.get("week") or request.GET.get("week", ""))
    except ValueError:
        anchor = today
    week_start, week_end = week_bounds(anchor)
    if week_start != week_bounds(today)[0]:
        messages.info(request, "Only this week's collection can be entered. Other weeks are view-only.")
        return redirect(f"{reverse('collection_list')}?week={week_start.isoformat()}")
    items = list(Collection.objects.filter(
        barangay=my_barangay,
        scheduled_date__date__gte=week_start, scheduled_date__date__lte=week_end,
    ).order_by("scheduled_date"))

    # Default collection date: today if it falls in this week, else the closest day in it.
    default_date = min(max(today, week_start), week_end)
    max_date = min(week_end, today)

    rows = []
    for key, label in WASTE_TYPE_CHOICES:
        of_type = [c for c in items if c.waste_type == key]
        open_items = [c for c in of_type if c.status != "Completed"]
        # A pickup scheduled for a later day this week stays view-only until its day.
        pending = [c for c in open_items if (collection_local_day(c) or today) <= today]
        upcoming = [c for c in open_items if (collection_local_day(c) or today) > today]
        done = [c for c in of_type if c.status == "Completed"]
        rows.append({
            "key": key, "label": label,
            "pending": pending[0] if pending else None,
            "upcoming": upcoming[0] if upcoming else None,
            "done_weight": sum((c.weight_kg or 0) for c in done),
            "done_count": len(done),
            "locked": (bool(done) or bool(upcoming)) and not pending,
            "weight": "", "error": "",
        })

    collected_on = default_date
    # Pre-fill the collector / truck with whatever this barangay used last.
    last_collector = (
        Collection.objects.filter(barangay=my_barangay).exclude(collector="")
        .order_by("-id").values_list("collector", flat=True).first()
    ) or ""
    collector_value = last_collector
    notes_value = ""
    if request.method == "POST":
        collector_value = request.POST.get("collector", "").strip()[:100]
        notes_value = request.POST.get("notes", "").strip()[:1000]
        has_error = False
        try:
            collected_on = date.fromisoformat(request.POST.get("collected_on", ""))
            if not week_start <= collected_on <= max_date:
                raise ValueError
        except ValueError:
            collected_on = default_date
            has_error = True
            messages.error(request, "Pick a collection date inside this week (not in the future).")

        entries = []
        for row in rows:
            if row["locked"]:
                continue
            raw = request.POST.get(f"weight_{row['key']}", "").strip()
            row["weight"] = raw
            if not raw:
                continue
            try:
                weight = Decimal(raw)
                if weight <= 0 or weight > Decimal("999999.99"):
                    raise InvalidOperation
                weight = weight.quantize(Decimal("0.01"))
            except InvalidOperation:
                row["error"] = "Enter a weight in kg greater than 0."
                has_error = True
                continue
            entries.append((row, weight))

        if not has_error and not entries:
            messages.info(request, "Nothing to save - enter a weight for at least one waste type.")
            has_error = True

        if not has_error:
            when = timezone.make_aware(
                datetime.combine(collected_on, datetime.min.time().replace(hour=12)),
                timezone.get_current_timezone(),
            )
            saved = []
            for row, weight in entries:
                c = row["pending"]
                if c is None:
                    c = Collection(
                        barangay=my_barangay,
                        waste_type=row["key"],
                        collector=collector_value or request.user.get_full_name() or request.user.username,
                        frequency="Weekly",
                        logged_by=request.user,
                        scheduled_date=timezone.make_aware(
                            datetime.combine(collected_on, datetime.min.time()),
                            timezone.get_current_timezone(),
                        ),
                    )
                if collector_value:
                    c.collector = collector_value
                if notes_value:
                    c.notes = notes_value
                c.weight_kg = weight
                c.status = "Completed"
                c.date_collected = when
                c.updated_by = request.user
                c.save()
                saved.append(c)
            messages.success(
                request,
                f"Saved {len(saved)} waste type{'s' if len(saved) != 1 else ''} for the week of {week_start:%b %d}.",
            )
            _auto_create_scmars(request, saved)
            return redirect(f"{reverse('collection_list')}?week={week_start.isoformat()}")

    return render(request, "waste/collection_week_input.html", {
        "rows": rows,
        "week_start": week_start,
        "week_end": week_end,
        "prev_week": week_start - timedelta(days=7),
        "next_week": week_start + timedelta(days=7),
        "is_current_week": week_start <= today <= week_end,
        "my_barangay": my_barangay,
        "collected_on": collected_on,
        "collector_value": collector_value,
        "notes_value": notes_value,
        "min_date": week_start,
        "max_date": max_date,
        "can_save": any(not r["locked"] for r in rows) and week_start <= today,
    })


@login_required
@user_passes_test(is_admin, login_url="dashboard")
def recurring_schedule_list(request):
    schedules = RecurringCollectionSchedule.objects.all()
    return render(request, "waste/recurring_schedule_list.html", {"schedules": schedules})


@login_required
@user_passes_test(is_admin, login_url="dashboard")
def recurring_schedule_add(request):
    if request.method == "POST":
        form = RecurringCollectionScheduleForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            # One schedule for the barangay covers EVERY waste type: create a
            # schedule row per type (skipping any identical one that exists).
            created, skipped = [], []
            for key, label in WASTE_TYPE_CHOICES:
                if RecurringCollectionSchedule.objects.filter(
                    barangay=data["barangay"], waste_type=key, frequency=data["frequency"],
                    day_of_week=data["day_of_week"], day_of_month=data["day_of_month"],
                ).exists():
                    skipped.append(label)
                    continue
                created.append(RecurringCollectionSchedule.objects.create(
                    barangay=data["barangay"], waste_type=key, collector=data["collector"],
                    frequency=data["frequency"], day_of_week=data["day_of_week"],
                    day_of_month=data["day_of_month"], is_active=data["is_active"],
                    created_by=request.user,
                ))
            # Create the collections that are already due right away, so the
            # barangay sees them without waiting for the next page load.
            generate_due_collections()
            if created:
                messages.success(
                    request,
                    f"{data['frequency']} schedule saved for {data['barangay']} - all {len(created)} waste types "
                    f"will be auto-created {created[0].when_label}."
                    + (f" Already scheduled and skipped: {', '.join(skipped)}." if skipped else ""),
                )
            else:
                messages.info(request, "That schedule already exists for this barangay - nothing new was created.")
            return redirect("recurring_schedule_list")
    else:
        form = RecurringCollectionScheduleForm(initial={"frequency": "Weekly"})
    return render(request, "waste/recurring_schedule_form.html", {"form": form})


@login_required
@user_passes_test(is_admin, login_url="dashboard")
def recurring_schedule_edit(request, pk):
    schedule = get_object_or_404(RecurringCollectionSchedule, pk=pk)
    if request.method == "POST":
        form = RecurringCollectionScheduleForm(request.POST, instance=schedule)
        if form.is_valid():
            form.save()
            generate_due_collections()
            messages.success(request, "Recurring schedule updated.")
            return redirect("recurring_schedule_list")
    else:
        form = RecurringCollectionScheduleForm(instance=schedule)
    return render(request, "waste/recurring_schedule_form.html", {"form": form, "editing": True, "schedule": schedule})


@login_required
@user_passes_test(is_admin, login_url="dashboard")
def recurring_schedule_delete(request, pk):
    schedule = get_object_or_404(RecurringCollectionSchedule, pk=pk)
    if request.method == "POST":
        schedule.delete()
        messages.success(request, "Recurring schedule deleted.")
        return redirect("recurring_schedule_list")
    return render(request, "waste/recurring_schedule_confirm_delete.html", {"schedule": schedule})


@login_required
def complaint_list(request):
    complaints = Complaint.objects.all()
    my_barangay = get_user_barangay(request.user)
    if my_barangay:
        complaints = complaints.filter(barangay=my_barangay)

    barangay = request.GET.get("barangay", "")
    status = request.GET.get("status", "")
    if barangay and not my_barangay:
        complaints = complaints.filter(barangay=barangay)
    if status:
        complaints = complaints.filter(status=status)

    # Compact summary counts for the current filtered result set - real
    # numbers derived from the same queryset the table renders, never
    # fabricated. Computed before pagination slices it.
    total_count = complaints.count()
    pending_count = complaints.filter(status="Pending").count()
    in_progress_count = complaints.filter(status="In Progress").count()
    resolved_count = complaints.filter(status="Resolved").count()

    paginator = Paginator(complaints, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "waste/complaint_list.html", {
        "complaints": page_obj,
        "page_obj": page_obj,
        "barangay_choices": BARANGAY_CHOICES,
        "status_choices": Complaint._meta.get_field("status").choices,
        "selected_barangay": my_barangay or barangay,
        "selected_status": status,
        "my_barangay": my_barangay,
        "total_count": total_count,
        "pending_count": pending_count,
        "in_progress_count": in_progress_count,
        "resolved_count": resolved_count,
    })


@login_required
def complaint_detail(request, pk):
    complaint = get_object_or_404(Complaint, pk=pk)
    my_barangay = get_user_barangay(request.user)
    if my_barangay and complaint.barangay != my_barangay:
        messages.error(request, "You can only view records for your own barangay.")
        return redirect("complaint_list")
    return render(request, "waste/complaint_detail.html", {"complaint": complaint})


@login_required
def complaint_add(request):
    if is_admin(request.user):
        messages.error(request, "Administrators receive complaints filed by Barangay Users and do not file new ones.")
        return redirect("complaint_list")
    if request.method == "POST":
        form = ComplaintForm(request.POST, user=request.user)
        if form.is_valid():
            complaint = form.save(commit=False)
            complaint.filed_by = request.user
            complaint.save()
            messages.success(request, "Complaint filed successfully. Status: Pending")
            return redirect("complaint_list")
    else:
        form = ComplaintForm(user=request.user)
    return render(request, "waste/complaint_form.html", {"form": form})


@login_required
@user_passes_test(is_admin, login_url="dashboard")
def complaint_update_status(request, pk):
    complaint = get_object_or_404(Complaint, pk=pk)
    if request.method == "POST":
        form = ComplaintStatusForm(request.POST, instance=complaint)
        if form.is_valid():
            form.save()
            messages.success(request, f"Complaint #{complaint.id} updated to '{complaint.status}'.")
            return redirect("complaint_list")
    else:
        form = ComplaintStatusForm(instance=complaint)
    return render(request, "waste/complaint_update.html", {"form": form, "complaint": complaint})


@login_required
def accomplishment_list(request):
    accomplishments = Accomplishment.objects.all()
    my_barangay = get_user_barangay(request.user)
    if my_barangay:
        accomplishments = accomplishments.filter(barangay=my_barangay)

    barangay = request.GET.get("barangay", "")
    if barangay and not my_barangay:
        accomplishments = accomplishments.filter(barangay=barangay)

    paginator = Paginator(accomplishments, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "waste/accomplishment_list.html", {
        "accomplishments": page_obj,
        "page_obj": page_obj,
        "barangay_choices": BARANGAY_CHOICES,
        "selected_barangay": my_barangay or barangay,
        "my_barangay": my_barangay,
    })


@login_required
def accomplishment_detail(request, pk):
    accomplishment = get_object_or_404(Accomplishment, pk=pk)
    my_barangay = get_user_barangay(request.user)
    if my_barangay and accomplishment.barangay != my_barangay:
        messages.error(request, "You can only view records for your own barangay.")
        return redirect("accomplishment_list")
    return render(request, "waste/accomplishment_detail.html", {
        "accomplishment": accomplishment,
        "is_menro_admin": is_admin(request.user),
        "is_owner": accomplishment.logged_by_id == request.user.id,
    })


@login_required
def accomplishment_add(request):
    # The Barangay is the sender/submitter. MENRO Admin receives and
    # reviews - it never creates its own accomplishment reports.
    if is_admin(request.user):
        messages.error(request, "MENRO Admin receives Accomplishment Reports submitted by Barangay Users and does not log new ones.")
        return redirect("accomplishment_list")
    if request.method == "POST":
        form = AccomplishmentForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            accomplishment = form.save(commit=False)
            accomplishment.logged_by = request.user
            # Submission date is system-controlled, never user-editable:
            # attaching the report file is what counts as "submitting".
            if accomplishment.report_file and not accomplishment.submission_date:
                accomplishment.submission_date = timezone.localdate()
            accomplishment.review_status = "For Review"
            accomplishment.save()
            notify_menro_of_submission(accomplishment, "Accomplishment Report", "accomplishment_detail")
            messages.success(request, "Accomplishment Report submitted to MENRO Admin for review.")
            return redirect("accomplishment_list")
    else:
        form = AccomplishmentForm(user=request.user)
    return render(request, "waste/accomplishment_form.html", {"form": form})


@login_required
def accomplishment_edit(request, pk):
    accomplishment = get_object_or_404(Accomplishment, pk=pk)
    my_barangay = get_user_barangay(request.user)

    if is_admin(request.user):
        form_user = None
    else:
        # Barangay can only edit its OWN submission, and only while it is
        # still awaiting review. Once MENRO Admin has approved/rejected it,
        # the Barangay can no longer edit it (they can only view the decision).
        if accomplishment.logged_by_id != request.user.id or accomplishment.barangay != my_barangay:
            messages.error(request, "You can only edit your own submissions.")
            return redirect("accomplishment_list")
        if accomplishment.review_status == "Approved":
            messages.error(request, "This Accomplishment Report has already been approved by MENRO Admin and can no longer be edited.")
            return redirect("accomplishment_detail", pk=pk)
        form_user = request.user

    if request.method == "POST":
        form = AccomplishmentForm(request.POST, request.FILES, instance=accomplishment, user=form_user)
        if form.is_valid():
            updated = form.save(commit=False)
            if updated.report_file and not updated.submission_date:
                updated.submission_date = timezone.localdate()
            if not is_admin(request.user) and updated.review_status == "Rejected":
                # Resubmission after rejection goes back to MENRO Admin for review.
                updated.review_status = "For Review"
            updated.save()
            messages.success(request, f"Accomplishment #{accomplishment.id} updated successfully.")
            return redirect("accomplishment_list")
    else:
        form = AccomplishmentForm(instance=accomplishment, user=form_user)
    return render(request, "waste/accomplishment_form.html", {
        "form": form, "editing": True, "accomplishment": accomplishment,
    })


@login_required
@user_passes_test(is_admin, login_url="dashboard")
def accomplishment_review(request, pk):
    """
    MENRO Admin only: approve or reject a Barangay's Accomplishment Report
    submission. The Barangay is never the receiver/reviewer of its own
    submission, so this view is admin-gated the same way approve/reject
    actions are gated everywhere else in this workflow.
    """
    accomplishment = get_object_or_404(Accomplishment, pk=pk)
    if request.method == "POST":
        form = ReviewForm(request.POST)
        if form.is_valid():
            decision = form.cleaned_data["decision"]
            accomplishment.review_status = decision
            accomplishment.reviewed_by = request.user
            accomplishment.review_date = timezone.now()
            accomplishment.review_remarks = form.cleaned_data["review_remarks"]
            accomplishment.save()
            notify_barangay_of_decision(accomplishment, "Accomplishment Report")
            messages.success(request, f"Accomplishment Report {decision.lower()}.")
        else:
            messages.error(request, "Invalid review submission.")
    return redirect("accomplishment_detail", pk=pk)


@login_required
@user_passes_test(is_admin, login_url="dashboard")
def accomplishment_delete(request, pk):
    accomplishment = get_object_or_404(Accomplishment, pk=pk)
    if request.method == "POST":
        accomplishment.delete()
        messages.success(request, f"Accomplishment #{pk} deleted.")
        return redirect("accomplishment_list")
    return render(request, "waste/accomplishment_confirm_delete.html", {"accomplishment": accomplishment})


@login_required
def action_plan_list(request):
    action_plans = ActionPlan.objects.all()
    my_barangay = get_user_barangay(request.user)
    if my_barangay:
        action_plans = action_plans.filter(barangay=my_barangay)

    barangay = request.GET.get("barangay", "")
    status = request.GET.get("status", "")
    compliance = request.GET.get("compliance", "")
    search = request.GET.get("q", "").strip()
    if barangay and not my_barangay:
        action_plans = action_plans.filter(barangay=barangay)
    if search:
        action_plans = action_plans.filter(
            Q(title__icontains=search) | Q(responsible_person__icontains=search)
        )
    today = timezone.localdate()

    if status:
        # get_display_status() is computed (derived from compliance), not a
        # DB field, so filter in Python - same approach as compliance below.
        matching_ids = [
            a.id for a in action_plans if a.get_display_status(today) == status
        ]
        action_plans = action_plans.filter(id__in=matching_ids)

    if compliance:
        # get_submission_status() is computed, not a DB field, so filter in Python.
        matching_ids = [
            a.id for a in action_plans if a.get_submission_status(today) == compliance
        ]
        action_plans = action_plans.filter(id__in=matching_ids)

    paginator = Paginator(action_plans, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "waste/action_plan_list.html", {
        "action_plans": page_obj,
        "page_obj": page_obj,
        "barangay_choices": BARANGAY_CHOICES,
        "status_choices": ActionPlan._meta.get_field("status").choices + [
            ("Late Submission", "Late Submission"),
            ("No Submission", "No Submission"),
        ],
        "selected_barangay": my_barangay or barangay,
        "selected_status": status,
        "selected_compliance": compliance,
        "selected_search": search,
        "my_barangay": my_barangay,
    })


@login_required
def action_plan_detail(request, pk):
    action_plan = get_object_or_404(ActionPlan, pk=pk)
    my_barangay = get_user_barangay(request.user)
    if my_barangay and action_plan.barangay != my_barangay:
        messages.error(request, "You can only view records for your own barangay.")
        return redirect("action_plan_list")
    return render(request, "waste/action_plan_detail.html", {
        "action_plan": action_plan,
        "is_menro_admin": is_admin(request.user),
        "can_submit": bool(my_barangay) and my_barangay == action_plan.barangay,
    })


@login_required
def action_plan_add(request):
    # The Barangay is the sender/submitter of its own Action Plan. MENRO
    # Admin only receives, reviews, and schedules it (sets the due date) -
    # it does not create new Action Plans itself. See action_plan_edit for
    # how MENRO Admin's edit is restricted to the schedule date only.
    if is_admin(request.user):
        messages.error(request, "MENRO Admin receives Action Plans submitted by Barangay Users and does not create new ones.")
        return redirect("action_plan_list")
    if request.method == "POST":
        form = ActionPlanForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            action_plan = form.save(commit=False)
            action_plan.submitted_by = request.user
            action_plan.submission_date = timezone.localdate()
            action_plan.review_status = "For Review"
            action_plan.save()
            notify_menro_of_submission(action_plan, "Action Plan", "action_plan_detail")
            messages.success(request, "Action Plan submitted to MENRO Admin for review.")
            return redirect("action_plan_list")
    else:
        form = ActionPlanForm(user=request.user)
    return render(request, "waste/action_plan_form.html", {"form": form})


@login_required
def action_plan_edit(request, pk):
    action_plan = get_object_or_404(ActionPlan, pk=pk)
    my_barangay = get_user_barangay(request.user)

    if is_admin(request.user):
        # MENRO Admin can only set/update the schedule (due) date - the
        # Action Plan itself (title, budget, files, etc.) belongs to the
        # Barangay that created and submitted it.
        if request.method == "POST":
            form = ActionPlanScheduleForm(request.POST, instance=action_plan)
            if form.is_valid():
                form.save()
                messages.success(request, f"Schedule date for Action Plan #{action_plan.id} updated.")
                return redirect("action_plan_list")
        else:
            form = ActionPlanScheduleForm(instance=action_plan)
        return render(request, "waste/action_plan_schedule_form.html", {
            "form": form, "action_plan": action_plan,
        })

    # Barangay: can create/edit/resubmit its OWN Action Plan (title,
    # description, budget, responsible person, remarks, document, evidence).
    # It never sets the schedule/due date - only MENRO Admin does. Once
    # MENRO Admin has approved it, it's locked - only "For Review" or
    # "Rejected" (needs resubmission) plans can still be edited.
    if action_plan.barangay != my_barangay:
        messages.error(request, "You can only edit Action Plans for your own barangay.")
        return redirect("action_plan_list")
    if action_plan.review_status == "Approved":
        messages.error(request, "This Action Plan has already been approved by MENRO Admin and can no longer be edited.")
        return redirect("action_plan_detail", pk=pk)

    if request.method == "POST":
        form = ActionPlanForm(request.POST, request.FILES, instance=action_plan, user=request.user)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.submitted_by = request.user
            updated.submission_date = timezone.localdate()
            updated.review_status = "For Review"
            # Compliance and status are linked: once the Barangay submits on
            # or before the due date, the Action Plan is considered Completed.
            if updated.get_submission_status() == "Submitted On Time":
                updated.status = "Completed"
            updated.save()
            notify_menro_of_submission(updated, "Action Plan", "action_plan_detail")
            messages.success(request, "Action Plan updated and submitted to MENRO Admin for review.")
            return redirect("action_plan_detail", pk=pk)
    else:
        form = ActionPlanForm(instance=action_plan, user=request.user)
    return render(request, "waste/action_plan_form.html", {
        "form": form, "editing": True, "action_plan": action_plan,
    })


@login_required
@user_passes_test(is_admin, login_url="dashboard")
def action_plan_review(request, pk):
    """
    MENRO Admin only: approve or reject a Barangay's Action Plan submission.
    The Barangay is never the receiver/reviewer of its own submission.
    """
    action_plan = get_object_or_404(ActionPlan, pk=pk)
    if request.method == "POST":
        form = ReviewForm(request.POST)
        if form.is_valid():
            decision = form.cleaned_data["decision"]
            action_plan.review_status = decision
            action_plan.reviewed_by = request.user
            action_plan.review_date = timezone.now()
            action_plan.review_remarks = form.cleaned_data["review_remarks"]
            action_plan.save()
            notify_barangay_of_decision(action_plan, "Action Plan")
            messages.success(request, f"Action Plan {decision.lower()}.")
        else:
            messages.error(request, "Invalid review submission.")
    return redirect("action_plan_detail", pk=pk)


@login_required
@user_passes_test(is_admin, login_url="dashboard")
def action_plan_delete(request, pk):
    action_plan = get_object_or_404(ActionPlan, pk=pk)
    if request.method == "POST":
        action_plan.delete()
        messages.success(request, f"Action plan #{pk} deleted.")
        return redirect("action_plan_list")
    return render(request, "waste/action_plan_confirm_delete.html", {"action_plan": action_plan})


# ============================================================
# SCMAR - Solid Waste Collection and Management Assessment Report
#
# A formal assessment report the Barangay prepares and submits to MENRO
# Admin. Distinct from the system-generated Monthly Summary Report under
# Reports (see reports() below) - SCMAR carries its own Draft -> Submitted
# -> Under Review -> Approved / Returned for Revision workflow.
#
# Role responsibility (never reversed):
#   Barangay User = Creator / Submitter
#   MENRO Admin   = Receiver / Reviewer / Approver
# ============================================================

def notify_menro_of_scmar_submission(scmar):
    emails = get_menro_admin_emails()
    if not emails:
        return
    submitter = scmar.submitted_by
    message = (
        f"New SCMAR Submission\n\n"
        f"Barangay: {scmar.barangay}\n"
        f"Reporting Period: {scmar.reporting_period}\n"
        f"Submitted By: {submitter.username if submitter else '-'}\n"
        f"Status: {scmar.status}\n\n"
        f"Please log in to SWMS to review this SCMAR."
    )
    try:
        send_mail(
            subject=f"New SCMAR Submission - {scmar.barangay}",
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=emails,
            fail_silently=True,
        )
    except Exception:
        pass


def notify_barangay_of_scmar_decision(scmar):
    submitter = scmar.submitted_by
    if not submitter or not submitter.email:
        return
    message = (
        f"Your SCMAR for {scmar.reporting_period} has been {scmar.status}.\n\n"
        f"Reviewed By: MENRO Admin\n"
        f"Review Date: {scmar.review_date.strftime('%b %d, %Y') if scmar.review_date else '-'}\n"
        f"Remarks: {scmar.review_remarks or '-'}\n"
    )
    try:
        send_mail(
            subject=f"Your SCMAR was {scmar.status} - {scmar.reporting_period}",
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[submitter.email],
            fail_silently=True,
        )
    except Exception:
        pass


@login_required
def scmar_list(request):
    scmars = SCMAR.objects.all()
    my_barangay = get_user_barangay(request.user)
    if my_barangay:
        # Barangay Users only ever see their own barangay's SCMARs.
        scmars = scmars.filter(barangay=my_barangay)
    else:
        # MENRO Admin never sees Drafts - those are still being prepared
        # by the Barangay and have not been submitted yet.
        scmars = scmars.exclude(status="Draft")

    barangay = request.GET.get("barangay", "")
    status = request.GET.get("status", "")
    search = request.GET.get("q", "").strip()
    if barangay and not my_barangay:
        scmars = scmars.filter(barangay=barangay)
    if status:
        scmars = scmars.filter(status=status)
    if search:
        scmars = scmars.filter(
            Q(reporting_period__icontains=search) | Q(prepared_by__icontains=search)
        )

    paginator = Paginator(scmars, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "waste/scmar_list.html", {
        "scmars": page_obj,
        "page_obj": page_obj,
        "barangay_choices": BARANGAY_CHOICES,
        "status_choices": SCMAR._meta.get_field("status").choices,
        "selected_barangay": my_barangay or barangay,
        "selected_status": status,
        "selected_search": search,
        "my_barangay": my_barangay,
        "is_menro_admin": is_admin(request.user),
    })


@login_required
def scmar_detail(request, pk):
    scmar = get_object_or_404(SCMAR, pk=pk)
    my_barangay = get_user_barangay(request.user)
    if my_barangay and scmar.barangay != my_barangay:
        messages.error(request, "You can only view SCMARs for your own barangay.")
        return redirect("scmar_list")
    if not my_barangay and scmar.status == "Draft":
        messages.error(request, "This SCMAR is still a draft and has not been submitted yet.")
        return redirect("scmar_list")
    # The moment MENRO Admin opens a freshly submitted SCMAR, it moves from
    # "Submitted" to "Under Review" so the Barangay can see it's being looked at.
    if is_admin(request.user) and scmar.status == "Submitted":
        scmar.status = "Under Review"
        scmar.save(update_fields=["status"])
    return render(request, "waste/scmar_detail.html", {
        "scmar": scmar,
        "is_menro_admin": is_admin(request.user),
        "can_edit": bool(my_barangay) and my_barangay == scmar.barangay and scmar.is_editable,
        # Combined-assessment data, pulled live from the existing modules -
        # see SCMAR.complaints_summary / collections_summary / etc.
        "complaints": scmar.complaints_summary,
        "collections": scmar.collections_summary,
        "action_plans": scmar.action_plans_summary,
        "accomplishments": scmar.accomplishments_summary,
    })


@login_required
def scmar_add(request):
    # The Barangay is the creator/submitter of its own SCMAR. MENRO Admin
    # only receives, reviews, and approves/returns it - it never creates
    # or submits a SCMAR on the Barangay's behalf.
    if is_admin(request.user):
        messages.error(request, "MENRO Admin receives SCMARs submitted by Barangay Users and does not create new ones.")
        return redirect("scmar_list")
    if request.method == "POST":
        form = SCMARForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            scmar = form.save(commit=False)
            scmar.created_by = request.user
            # Every save is a submission to MENRO Admin (no drafts).
            scmar.submitted_by = request.user
            scmar.submission_date = timezone.now()
            scmar.status = "Submitted"
            scmar.save()
            notify_menro_of_scmar_submission(scmar)
            messages.success(request, "SCMAR submitted to MENRO Admin for review.")
            return redirect("scmar_detail", pk=scmar.pk)
    else:
        initial = {}
        # Coming from the weekly Collections page ("Prepare SCMAR for this
        # month"): start with that month's period already filled in.
        month_param = request.GET.get("month", "")
        try:
            month_start = datetime.strptime(month_param, "%Y-%m").date()
        except ValueError:
            month_start = None
        if month_start:
            month_end = date(month_start.year, month_start.month, calendar.monthrange(month_start.year, month_start.month)[1])
            initial = {
                "reporting_period": month_start.strftime("%B %Y"),
                "period_start": month_start,
                "period_end": month_end,
            }
        form = SCMARForm(user=request.user, initial=initial)
    return render(request, "waste/scmar_form.html", {"form": form, "prefill_month": month_param if initial else ""})


@login_required
def scmar_edit(request, pk):
    scmar = get_object_or_404(SCMAR, pk=pk)
    my_barangay = get_user_barangay(request.user)

    # MENRO Admin never creates or edits the Barangay's SCMAR content -
    # it only reviews it (see scmar_review below).
    if is_admin(request.user):
        messages.error(request, "MENRO Admin reviews SCMARs but cannot edit their content.")
        return redirect("scmar_detail", pk=pk)

    if scmar.barangay != my_barangay:
        messages.error(request, "You can only edit SCMARs for your own barangay.")
        return redirect("scmar_list")
    if not scmar.is_editable:
        messages.error(request, f"This SCMAR is {scmar.status} and can no longer be edited.")
        return redirect("scmar_detail", pk=pk)

    if request.method == "POST":
        form = SCMARForm(request.POST, request.FILES, instance=scmar, user=request.user)
        if form.is_valid():
            updated = form.save(commit=False)
            # Every save is a (re)submission to MENRO Admin (no drafts).
            updated.submitted_by = request.user
            updated.submission_date = timezone.now()
            updated.status = "Submitted"
            # Clear the previous review decision now that it's been revised.
            updated.reviewed_by = None
            updated.review_date = None
            updated.save()
            notify_menro_of_scmar_submission(updated)
            messages.success(request, "SCMAR submitted to MENRO Admin for review.")
            return redirect("scmar_detail", pk=pk)
    else:
        form = SCMARForm(instance=scmar, user=request.user)
    return render(request, "waste/scmar_form.html", {
        "form": form, "editing": True, "scmar": scmar,
    })


@login_required
@user_passes_test(is_admin, login_url="dashboard")
def scmar_review(request, pk):
    """MENRO Admin only: approve or return a Barangay's SCMAR for revision."""
    scmar = get_object_or_404(SCMAR, pk=pk)
    if scmar.status == "Draft":
        messages.error(request, "This SCMAR has not been submitted yet.")
        return redirect("scmar_list")
    if request.method == "POST":
        form = SCMARReviewForm(request.POST)
        if form.is_valid():
            decision = form.cleaned_data["decision"]
            scmar.status = decision
            scmar.reviewed_by = request.user
            scmar.review_date = timezone.now()
            scmar.review_remarks = form.cleaned_data["review_remarks"]
            scmar.save()
            notify_barangay_of_scmar_decision(scmar)
            messages.success(request, f"SCMAR {decision.lower()}.")
        else:
            for error in form.errors.get("review_remarks", []):
                messages.error(request, error)
    return redirect("scmar_detail", pk=pk)


@login_required
def scmar_delete(request, pk):
    scmar = get_object_or_404(SCMAR, pk=pk)
    my_barangay = get_user_barangay(request.user)
    # Only the owning Barangay may delete its own SCMAR, and only while
    # it is still a Draft - once submitted it belongs to the review record.
    if is_admin(request.user) or scmar.barangay != my_barangay:
        messages.error(request, "You can only delete drafts for your own barangay.")
        return redirect("scmar_list")
    if scmar.status != "Draft":
        messages.error(request, "Only draft SCMARs can be deleted.")
        return redirect("scmar_detail", pk=pk)
    if request.method == "POST":
        scmar.delete()
        messages.success(request, "Draft SCMAR deleted.")
        return redirect("scmar_list")
    return render(request, "waste/scmar_confirm_delete.html", {"scmar": scmar})


def _build_report_context(request):
    """Shared query logic used by both the on-screen report and the Excel export."""
    today = timezone.localdate()

    # Determine which month/year the report covers.
    # Accepts ?period=YYYY-MM (from an <input type="month">); defaults to the current month.
    period = request.GET.get("period")
    report_year, report_month = today.year, today.month
    if period:
        try:
            parsed = datetime.strptime(period, "%Y-%m")
            report_year, report_month = parsed.year, parsed.month
        except ValueError:
            pass

    report_start = date(report_year, report_month, 1)
    last_day = calendar.monthrange(report_year, report_month)[1]
    report_end = date(report_year, report_month, last_day)

    # The report for a given month is due on the 5th day of the following month.
    if report_month == 12:
        due_year, due_month = report_year + 1, 1
    else:
        due_year, due_month = report_year, report_month + 1
    due_date = date(due_year, due_month, 5)
    is_overdue = today > due_date

    collections_qs = Collection.objects.filter(
        date_collected__date__gte=report_start, date_collected__date__lte=report_end
    )
    complaints_qs = Complaint.objects.filter(
        date_filed__date__gte=report_start, date_filed__date__lte=report_end
    )

    by_barangay = (
        collections_qs.values("barangay")
        .annotate(total_weight=Sum("weight_kg"))
        .order_by("-total_weight")
    )
    by_type = (
        collections_qs.values("waste_type")
        .annotate(total_weight=Sum("weight_kg"))
        .order_by("-total_weight")
    )
    complaint_status = (
        complaints_qs.values("status").annotate(count=Count("id")).order_by("status")
    )
    total_weight = collections_qs.aggregate(total=Sum("weight_kg"))["total"] or 0

    return {
        "by_barangay": by_barangay,
        "by_type": by_type,
        "complaint_status": complaint_status,
        "total_weight": total_weight,
        "report_period_value": f"{report_year:04d}-{report_month:02d}",
        "report_period_label": report_start.strftime("%B %Y"),
        "due_date": due_date,
        "is_overdue": is_overdue,
        "today": today,
        "collections_qs": collections_qs,
        "complaints_qs": complaints_qs,
    }


@login_required
def reports(request):
    context = _build_report_context(request)
    return render(request, "waste/reports.html", context)


@login_required
def reports_export_excel(request):
    """Export the currently viewed monthly report as an .xlsx workbook."""
    ctx = _build_report_context(request)

    wb = Workbook()

    header_fill = PatternFill(start_color="15803D", end_color="15803D", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    title_font = Font(bold=True, size=14, color="15803D")
    subtitle_font = Font(italic=True, color="475569")
    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )

    def style_header_row(ws, row_idx, num_cols):
        for col_idx in range(1, num_cols + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="left", vertical="center")
            cell.border = thin_border

    def autosize(ws, num_cols, min_width=12, max_width=45):
        for col_idx in range(1, num_cols + 1):
            letter = get_column_letter(col_idx)
            longest = min_width
            for cell in ws[letter]:
                if cell.value is not None:
                    longest = max(longest, len(str(cell.value)) + 2)
            ws.column_dimensions[letter].width = min(longest, max_width)

    # ---------- Summary sheet ----------
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = "SWMS Carigara – Monthly Summary Report"
    ws["A1"].font = title_font
    ws.merge_cells("A1:B1")
    ws["A2"] = f"Report Period: {ctx['report_period_label']}"
    ws["A2"].font = subtitle_font
    ws.merge_cells("A2:B2")
    ws["A3"] = f"Due Date: {ctx['due_date'].strftime('%B %d, %Y')} ({'Overdue' if ctx['is_overdue'] else 'On Track'})"
    ws["A3"].font = subtitle_font
    ws.merge_cells("A3:B3")

    ws["A5"] = "Metric"
    ws["B5"] = "Value"
    style_header_row(ws, 5, 2)
    ws["A6"] = "Total Waste Collected (kg)"
    ws["B6"] = float(ctx["total_weight"])
    ws["A7"] = "Total Collection Entries"
    ws["B7"] = ctx["collections_qs"].count()
    ws["A8"] = "Total Complaints Filed"
    ws["B8"] = ctx["complaints_qs"].count()
    for row in (6, 7, 8):
        ws.cell(row=row, column=1).border = thin_border
        ws.cell(row=row, column=2).border = thin_border
    autosize(ws, 2)

    # ---------- By Barangay sheet ----------
    ws = wb.create_sheet("By Barangay")
    ws.append(["Barangay", "Total Weight (kg)"])
    style_header_row(ws, 1, 2)
    for row in ctx["by_barangay"]:
        ws.append([row["barangay"], float(row["total_weight"] or 0)])
    for r in range(2, ws.max_row + 1):
        for c in (1, 2):
            ws.cell(row=r, column=c).border = thin_border
    autosize(ws, 2)

    # ---------- By Waste Type sheet ----------
    ws = wb.create_sheet("By Waste Type")
    ws.append(["Waste Type", "Total Weight (kg)"])
    style_header_row(ws, 1, 2)
    for row in ctx["by_type"]:
        ws.append([row["waste_type"], float(row["total_weight"] or 0)])
    for r in range(2, ws.max_row + 1):
        for c in (1, 2):
            ws.cell(row=r, column=c).border = thin_border
    autosize(ws, 2)

    # ---------- Complaint Status sheet ----------
    ws = wb.create_sheet("Complaint Status")
    ws.append(["Status", "Count"])
    style_header_row(ws, 1, 2)
    for row in ctx["complaint_status"]:
        ws.append([row["status"], row["count"]])
    for r in range(2, ws.max_row + 1):
        for c in (1, 2):
            ws.cell(row=r, column=c).border = thin_border
    autosize(ws, 2)

    # ---------- Collection Details sheet ----------
    ws = wb.create_sheet("Collection Details")
    ws.append(["ID", "Date Collected", "Barangay", "Waste Type", "Weight (kg)", "Collector", "Logged By"])
    style_header_row(ws, 1, 7)
    for c in ctx["collections_qs"].order_by("date_collected"):
        ws.append([
            c.id,
            c.date_collected.strftime("%Y-%m-%d %H:%M") if c.date_collected else "",
            c.barangay,
            c.waste_type,
            float(c.weight_kg or 0),
            c.collector,
            c.logged_by.username if c.logged_by else "",
        ])
    for r in range(2, ws.max_row + 1):
        for col in range(1, 8):
            ws.cell(row=r, column=col).border = thin_border
    autosize(ws, 7)

    filename = f"SWMS_Report_{ctx['report_period_value']}.xlsx"
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    purge_unverified_accounts()

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            # New accounts must confirm their email via OTP before they can
            # reach the dashboard. Don't log them in yet - send the code and
            # route through the same confirm_login_view used for that step.
            sent = send_login_code(user)
            request.session["pending_user_id"] = user.id
            if sent:
                messages.info(
                    request,
                    f"We've sent a confirmation code to {user.email}. "
                    f"Enter it below to activate your account.",
                )
            else:
                messages.error(
                    request,
                    "We couldn't send the confirmation code right now. "
                    "Please press Resend code in a moment.",
                )
            return redirect("confirm_login")
    else:
        form = RegisterForm()
    return render(request, "registration/register.html", {"form": form})


@login_required
def profile(request):
    profile_obj, _ = Profile.objects.get_or_create(user=request.user)
    initial = {
        "username": request.user.username,
        "full_name": request.user.get_full_name(),
        "email": request.user.email,
        "phone_number": profile_obj.phone_number,
    }

    if request.method == "POST":
        form = ProfileEditForm(request.POST, request.FILES, user=request.user, initial=initial)
        if form.is_valid():
            # SECURITY: only username, full name, avatar, email, and phone
            # number are ever applied here. Role, barangay, account status,
            # and date_joined are NOT fields on ProfileEditForm, so they can
            # never be changed via this endpoint - not even by a
            # tampered/forged POST request.
            request.user.username = form.cleaned_data["username"]
            full_name = form.cleaned_data["full_name"].strip()
            if full_name:
                first, _, last = full_name.partition(" ")
                request.user.first_name = first
                request.user.last_name = last
            else:
                request.user.first_name = ""
                request.user.last_name = ""
            update_fields = ["username", "first_name", "last_name"]

            # The email is NOT changed here. If the user typed a different
            # address, we email a confirmation code to that NEW address and
            # only switch the account over once the code is entered
            # (see change_email()).
            new_email = form.cleaned_data.get("email")
            email_change_requested = (
                bool(new_email) and new_email != (request.user.email or "").lower()
            )

            request.user.save(update_fields=update_fields)

            avatar_file = form.cleaned_data.get("avatar")
            profile_update_fields = []
            if avatar_file:
                profile_obj.avatar = avatar_file
                profile_update_fields.append("avatar")

            new_phone = form.cleaned_data.get("phone_number", "")
            if new_phone != (profile_obj.phone_number or ""):
                profile_obj.phone_number = new_phone
                profile_update_fields.append("phone_number")

            if profile_update_fields:
                profile_obj.save(update_fields=profile_update_fields)

            if email_change_requested:
                try:
                    _clear_email_change_state(request)
                    if _is_real_email(request.user.email):
                        # Step 1: prove ownership of the CURRENT email first.
                        _send_old_email_code(request, request.user)
                        request.session[REQUESTED_EMAIL_KEY] = new_email
                        messages.info(
                            request,
                            f"Your other changes were saved. To change your email, first enter "
                            f"the code we sent to your current email {request.user.email}.",
                        )
                    else:
                        # No real email on file yet - go straight to the new one.
                        _start_email_change(request, request.user, new_email)
                        messages.info(
                            request,
                            f"Your other changes were saved. We sent a confirmation code to "
                            f"{new_email} - enter it to finish.",
                        )
                    return redirect("change_email")
                except Exception:
                    messages.error(
                        request,
                        "Your other changes were saved, but we couldn't send the "
                        "confirmation code. Please try again.",
                    )
                    return redirect("profile")

            messages.success(request, "Profile updated.")
            return redirect("profile")
    else:
        form = ProfileEditForm(user=request.user, initial=initial)

    return render(request, "waste/profile.html", {
        "form": form,
        "profile_obj": profile_obj,
        "can_change_email": True,
    })


PLACEHOLDER_EMAIL_DOMAIN = "@swms-carigara.local"
EMAIL_EDIT_WINDOW_SECONDS = 10 * 60

# Session keys used by the email-change flow.
OLD_SENT_KEY = "email_old_code_sent"          # code was mailed to the CURRENT email
OLD_VERIFIED_KEY = "email_old_verified_until" # current email's code was confirmed
OLD_ATTEMPTS_KEY = "email_old_attempts"
REQUESTED_EMAIL_KEY = "requested_new_email"   # typed on the Profile page, waiting for step 1
PENDING_EMAIL_KEY = "pending_new_email"       # code was mailed to this NEW email
NEW_ATTEMPTS_KEY = "email_new_attempts"
_EMAIL_FLOW_KEYS = (
    OLD_SENT_KEY, OLD_VERIFIED_KEY, OLD_ATTEMPTS_KEY,
    REQUESTED_EMAIL_KEY, PENDING_EMAIL_KEY, NEW_ATTEMPTS_KEY,
)


def _is_real_email(email):
    email = (email or "").strip()
    return bool(email) and not email.lower().endswith(PLACEHOLDER_EMAIL_DOMAIN)


def _clear_email_change_state(request):
    for key in _EMAIL_FLOW_KEYS:
        request.session.pop(key, None)


def _send_old_email_code(request, user):
    """Step 1: email a confirmation code to the account's CURRENT email."""
    try:
        send_login_code(user)
    except Exception:
        logger.exception("Could not email the confirmation code to the current email of user %s", user.pk)
        raise
    request.session[OLD_SENT_KEY] = user.pk
    request.session.pop(OLD_ATTEMPTS_KEY, None)


def _start_email_change(request, user, new_email):
    """Step 3 setup: email a fresh confirmation code to `new_email` and
    remember it as the pending address. The account's email is only switched
    after that code is verified in change_email()."""
    try:
        send_login_code(user, email=new_email)
    except Exception:
        logger.exception("Could not email the confirmation code to the new email %s", new_email)
        raise
    request.session[PENDING_EMAIL_KEY] = new_email
    request.session.pop(NEW_ATTEMPTS_KEY, None)


@login_required
def change_email(request):
    """
    Email change (any logged-in account) - the email only changes after BOTH
    addresses are proven:
      1. A code is emailed to the CURRENT email and must be entered
         (proves the real owner is making the change).
      2. The user enters the NEW email.
      3. A code is emailed to the NEW email and must be entered
         (proves the new address is real). Only then is the email changed.
    Accounts with no real email (blank or placeholder) skip step 1.
    """
    user = request.user
    current = (user.email or "").strip()
    needs_old_check = _is_real_email(current)

    old_verified = (not needs_old_check) or time.time() < request.session.get(OLD_VERIFIED_KEY, 0)
    old_code_sent = request.session.get(OLD_SENT_KEY) == user.pk
    pending = request.session.get(PENDING_EMAIL_KEY)

    code_form = ConfirmCodeForm()
    email_form = EmailChangeForm(user=user)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "cancel":
            _clear_email_change_state(request)
            return redirect("profile")

        # ---- Step 1: code to the CURRENT email (send / resend) ----
        if action in ("send_old", "resend_old") and needs_old_check and not old_verified:
            try:
                _send_old_email_code(request, user)
                messages.success(request, f"A confirmation code was sent to your current email {current}.")
            except Exception:
                messages.error(request, "We couldn't send the code. Please try again.")
            return redirect("change_email")

        # ---- Step 1: verify the CURRENT email's code ----
        if action == "verify_old" and needs_old_check and not old_verified and old_code_sent:
            code_form = ConfirmCodeForm(request.POST)
            if code_form.is_valid():
                error = verify_emailed_code(
                    request, user, code_form.cleaned_data["code"], OLD_ATTEMPTS_KEY
                )
                if error:
                    messages.error(request, error)
                else:
                    request.session[OLD_VERIFIED_KEY] = time.time() + EMAIL_EDIT_WINDOW_SECONDS
                    request.session.pop(OLD_SENT_KEY, None)
                    request.session.pop(OLD_ATTEMPTS_KEY, None)
                    # If the new email was already typed on the Profile page,
                    # go straight to sending it its code.
                    requested = request.session.pop(REQUESTED_EMAIL_KEY, None)
                    if requested and requested.lower() != current.lower() and not (
                        AuthUser.objects.filter(email__iexact=requested).exclude(pk=user.pk).exists()
                    ):
                        try:
                            _start_email_change(request, user, requested)
                            messages.success(
                                request,
                                f"Current email confirmed. We sent a code to your new email {requested}.",
                            )
                        except Exception:
                            messages.error(request, "We couldn't send the code to the new email. Please enter it again.")
                    else:
                        messages.success(request, "Current email confirmed. Now enter your new email.")
                    return redirect("change_email")

        # ---- Step 2: enter the NEW email -> code to the NEW email ----
        elif action == "send_new" and old_verified:
            email_form = EmailChangeForm(request.POST, user=user)
            if email_form.is_valid():
                new_email = email_form.cleaned_data["email"]
                try:
                    _start_email_change(request, user, new_email)
                    messages.success(request, f"A confirmation code was sent to {new_email}.")
                except Exception:
                    messages.error(request, "We couldn't send the code. Please try again.")
                return redirect("change_email")

        elif action == "resend_new" and old_verified and pending:
            try:
                _start_email_change(request, user, pending)
                messages.success(request, f"A new confirmation code was sent to {pending}.")
            except Exception:
                messages.error(request, "We couldn't send the code. Please try again.")
            return redirect("change_email")

        elif action == "restart" and old_verified:
            request.session.pop(PENDING_EMAIL_KEY, None)
            request.session.pop(NEW_ATTEMPTS_KEY, None)
            return redirect("change_email")

        # ---- Step 3: verify the NEW email's code, then apply the change ----
        elif action == "verify_new" and old_verified and pending:
            code_form = ConfirmCodeForm(request.POST)
            if code_form.is_valid():
                error = verify_emailed_code(
                    request, user, code_form.cleaned_data["code"], NEW_ATTEMPTS_KEY
                )
                if error:
                    messages.error(request, error)
                elif AuthUser.objects.filter(email__iexact=pending).exclude(pk=user.pk).exists():
                    request.session.pop(PENDING_EMAIL_KEY, None)
                    messages.error(request, "An account with this email already exists.")
                    return redirect("change_email")
                else:
                    old_email = current
                    user.email = pending
                    user.save(update_fields=["email"])
                    _clear_email_change_state(request)

                    if _is_real_email(old_email):
                        try:
                            send_mail(
                                subject="Your SWMS account email was changed",
                                message=(
                                    f"The email on your SWMS Carigara account was changed to {user.email}.\n\n"
                                    "If you did not do this, contact the system administrator immediately."
                                ),
                                from_email=settings.DEFAULT_FROM_EMAIL,
                                recipient_list=[old_email],
                            )
                        except Exception:
                            pass

                    messages.success(request, "Your email has been updated.")
                    return redirect("profile")

        # Server-side guard: nobody reaches the save step without step 1.
        elif action in ("send_new", "verify_new", "resend_new"):
            messages.error(request, "Please confirm the code sent to your current email first.")
            return redirect("change_email")

    # Work out which screen to show.
    if needs_old_check and not old_verified:
        stage = "verify_old" if old_code_sent else "send_old"
    elif pending:
        stage = "verify_new"
    else:
        stage = "enter_new"

    if needs_old_check:
        step = {"send_old": 1, "verify_old": 1, "enter_new": 2, "verify_new": 3}[stage]
        total_steps = 3
    else:
        step = {"enter_new": 1, "verify_new": 2}[stage]
        total_steps = 2

    return render(request, "waste/change_email.html", {
        "stage": stage,
        "step": step,
        "total_steps": total_steps,
        "current_email": current,
        "pending_email": request.session.get(PENDING_EMAIL_KEY, ""),
        "requested_email": request.session.get(REQUESTED_EMAIL_KEY, ""),
        "code_form": code_form,
        "email_form": email_form,
    })


# ---------------------------------------------------------------------------
# Login / registration flow
#
# OTP confirmation is only required ONCE per account: right after
# registration, to prove the email address is real (see register(), which
# routes new accounts through confirm_login_view instead of logging them in
# directly). Profile.email_verified is set True the first time that code is
# confirmed.
#
# Regular logins (username or email as the identifier) after that are a
# normal single-step login - no OTP. EmailOrUsernameBackend already accepts
# either a username or an email address as the identifier, so login_view
# doesn't need to know or care which one was typed.
# ---------------------------------------------------------------------------

def send_login_code(user, email=None):
    """Create a new LoginVerification code for `user` and email it to them
    (or to `email` when given). Any previously-issued, still-unused codes
    for that user are discarded first so only the latest code is ever valid."""
    LoginVerification.objects.filter(user=user, is_used=False).delete()
    code = LoginVerification.generate_code()
    LoginVerification.objects.create(user=user, code=code)
    try:
        send_mail(
            subject="Your SWMS Carigara confirmation code",
            message=(
                f"Your confirmation code is {code}. It expires in 10 minutes.\n\n"
                f"If you didn't request this, you can safely ignore this email."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email or user.email],
        )
        return True
    except Exception:
        # Never turn a mail problem into a 500 page.
        import logging
        logging.getLogger(__name__).exception("Could not send confirmation code to %s", email or user.email)
        return False


UNVERIFIED_ACCOUNT_MINUTES = 15


def purge_unverified_accounts():
    """Delete sign-ups that never confirmed their emailed code.

    A new account stays inactive until its code is confirmed. If no code has
    been sent for it in the last UNVERIFIED_ACCOUNT_MINUTES (pressing Resend
    code counts), the account is removed so the username, email and barangay
    are free again - it is as if the account was never made.
    """
    cutoff = timezone.now() - timedelta(minutes=UNVERIFIED_ACCOUNT_MINUTES)
    recent_codes = LoginVerification.objects.filter(user=OuterRef("pk"), created_at__gte=cutoff)
    (
        AuthUser.objects.filter(
            is_active=False,
            is_superuser=False,
            profile__email_verified=False,
            profile__role="user",
        )
        .annotate(has_recent_code=Exists(recent_codes))
        .filter(has_recent_code=False)
        .delete()
    )


MAX_CODE_ATTEMPTS = 5


def verify_emailed_code(request, user, code, attempts_key):
    """Checks a one-time emailed code. Returns None on success (and marks the
    code used), otherwise a user-facing error message. After
    MAX_CODE_ATTEMPTS wrong tries the user must request a fresh code."""
    tries = request.session.get(attempts_key, 0)
    if tries >= MAX_CODE_ATTEMPTS:
        return "Too many incorrect attempts. Please request a new code."
    verification = LoginVerification.objects.filter(
        user=user, code=code, is_used=False
    ).order_by("-created_at").first()
    if verification is None:
        request.session[attempts_key] = tries + 1
        return "Incorrect code. Please try again."
    if verification.is_expired():
        return "That code expired. Please request a new one."
    verification.is_used = True
    verification.save(update_fields=["is_used"])
    request.session.pop(attempts_key, None)
    return None


def login_view(request):
    # Only bounce away-from-login on a plain page view. If credentials were
    # just submitted (POST), always evaluate them, even if a different
    # account happens to already be logged in on this session.
    if request.user.is_authenticated and request.method == "GET":
        return redirect("dashboard")

    form_errors = False

    if request.method == "POST":
        identifier = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(request, username=identifier, password=password)

        if user is None:
            form_errors = True
        else:
            auth_login(request, user)
            return redirect("dashboard")

    return render(request, "registration/login.html", {"form_errors": form_errors})


def confirm_login_view(request):
    """
    Finishes either:
      - a fresh registration (marks Profile.email_verified = True), or
      - a resend/retry of that same pending confirmation.
    Reached only via register() or resend_code_view() setting
    session['pending_user_id'] - never from a normal login.
    """
    purge_unverified_accounts()
    user_id = request.session.get("pending_user_id")
    if not user_id:
        return redirect("login")

    user = AuthUser.objects.filter(id=user_id).first()
    if not user:
        request.session.pop("pending_user_id", None)
        messages.error(request, "That sign-up expired because the code wasn't confirmed in time. Please register again.")
        return redirect("register")

    if request.method == "POST":
        form = ConfirmCodeForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data["code"]
            verification = LoginVerification.objects.filter(
                user=user, code=code, is_used=False
            ).order_by("-created_at").first()

            if verification is None:
                messages.error(request, "Incorrect code. Please try again.")
            elif verification.is_expired():
                messages.error(request, "That code expired. We've sent you a new one.")
                send_login_code(user)
            else:
                verification.is_used = True
                verification.save(update_fields=["is_used"])

                profile, _ = Profile.objects.get_or_create(user=user)
                if not profile.email_verified:
                    profile.email_verified = True
                    profile.save(update_fields=["email_verified"])

                user.is_active = True
                user.save(update_fields=["is_active"])

                auth_login(request, user)
                del request.session["pending_user_id"]
                messages.success(request, f"Welcome, {user.username}!")
                return redirect("dashboard")
    else:
        form = ConfirmCodeForm()

    return render(request, "registration/confirm_login.html", {"form": form, "email": user.email})


def resend_code_view(request):
    purge_unverified_accounts()
    user_id = request.session.get("pending_user_id")
    if user_id:
        user = AuthUser.objects.filter(id=user_id).first()
        if user:
            send_login_code(user)
            messages.success(request, "A new code has been sent.")
    return redirect("confirm_login")