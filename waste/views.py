import calendar
from datetime import date, datetime

from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import authenticate, login as auth_login
from django.contrib.auth.models import User as AuthUser
from django.core.paginator import Paginator
from django.core.mail import send_mail
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.http import HttpResponse

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from .models import Collection, Complaint, Profile, Accomplishment, ActionPlan, SCMAR, BARANGAY_CHOICES, LoginVerification, RecurringCollectionSchedule, generate_due_collections
from .forms import (
    CollectionForm, CollectionStatusForm, ComplaintForm, ComplaintStatusForm, RegisterForm,
    AccomplishmentForm, ActionPlanForm, ActionPlanSubmissionForm, ActionPlanScheduleForm,
    SCMARForm, SCMARReviewForm, ProfileAvatarForm, ProfileEditForm,
    ConfirmCodeForm, ReviewForm, RecurringCollectionScheduleForm,
)

PAGE_SIZE = 15


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


@login_required
def collection_list(request):
    # Auto-generate this month's Collections from any active recurring
    # schedules. Cheap no-op once a schedule has already been generated for
    # the current month, so it's safe to run on every page load - no cron
    # or Celery needed for this to work.
    generate_due_collections()

    collections = Collection.objects.all()
    my_barangay = get_user_barangay(request.user)
    if my_barangay:
        collections = collections.filter(barangay=my_barangay)

    barangay = request.GET.get("barangay", "")
    waste_type = request.GET.get("waste_type", "")
    period = request.GET.get("period", "")
    if barangay and not my_barangay:
        collections = collections.filter(barangay=barangay)
    if waste_type:
        collections = collections.filter(waste_type=waste_type)
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
    # year/month first. Scoped to barangay only, so picking a period doesn't
    # shrink the dropdown itself.
    months_qs = Collection.objects.filter(scheduled_date__isnull=False)
    if my_barangay:
        months_qs = months_qs.filter(barangay=my_barangay)
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

    paginator = Paginator(collections, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "waste/collection_list.html", {
        "collections": page_obj,
        "page_obj": page_obj,
        "barangay_choices": BARANGAY_CHOICES,
        "waste_type_choices": Collection._meta.get_field("waste_type").choices,
        "period_choices": period_choices,
        "selected_barangay": my_barangay or barangay,
        "selected_waste_type": waste_type,
        "selected_period": period,
        "my_barangay": my_barangay,
        "total_count": total_count,
        "completed_count": completed_count,
        "ongoing_count": ongoing_count,
        "scheduled_count": scheduled_count,
        "completed_pct": completed_pct,
    })


@login_required
def collection_detail(request, pk):
    collection = get_object_or_404(Collection, pk=pk)
    my_barangay = get_user_barangay(request.user)
    if my_barangay and collection.barangay != my_barangay:
        messages.error(request, "You can only view records for your own barangay.")
        return redirect("collection_list")
    return render(request, "waste/collection_detail.html", {"collection": collection})


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

    if request.method == "POST":
        form = CollectionStatusForm(request.POST, instance=collection)
        if form.is_valid():
            updated = form.save(commit=False)
            if updated.status == "Completed" and not updated.date_collected:
                updated.date_collected = timezone.now()
            updated.updated_by = request.user
            updated.save()
            messages.success(request, f"Collection #{collection.id} updated to '{updated.status}'.")
            return redirect("collection_list")
    else:
        form = CollectionStatusForm(instance=collection)

    return render(request, "waste/collection_update.html", {"form": form, "collection": collection})


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
            schedule = form.save(commit=False)
            schedule.created_by = request.user
            schedule.save()
            messages.success(
                request,
                f"Recurring schedule saved. A Collection for {schedule.barangay} "
                f"({schedule.waste_type}) will be auto-created every month.",
            )
            return redirect("recurring_schedule_list")
    else:
        form = RecurringCollectionScheduleForm()
    return render(request, "waste/recurring_schedule_form.html", {"form": form})


@login_required
@user_passes_test(is_admin, login_url="dashboard")
def recurring_schedule_edit(request, pk):
    schedule = get_object_or_404(RecurringCollectionSchedule, pk=pk)
    if request.method == "POST":
        form = RecurringCollectionScheduleForm(request.POST, instance=schedule)
        if form.is_valid():
            form.save()
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
            if "submit" in request.POST:
                scmar.submitted_by = request.user
                scmar.submission_date = timezone.now()
                scmar.status = "Submitted"
            else:
                scmar.status = "Draft"
            scmar.save()
            if scmar.status == "Submitted":
                notify_menro_of_scmar_submission(scmar)
                messages.success(request, "SCMAR submitted to MENRO Admin for review.")
                return redirect("scmar_detail", pk=scmar.pk)
            messages.success(request, "SCMAR saved as draft.")
            return redirect("scmar_edit", pk=scmar.pk)
    else:
        form = SCMARForm(user=request.user)
    return render(request, "waste/scmar_form.html", {"form": form})


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
            if "submit" in request.POST:
                updated.submitted_by = request.user
                updated.submission_date = timezone.now()
                updated.status = "Submitted"
                # Clear the previous review decision now that it's been revised.
                updated.reviewed_by = None
                updated.review_date = None
            else:
                updated.status = "Draft"
            updated.save()
            if updated.status == "Submitted":
                notify_menro_of_scmar_submission(updated)
                messages.success(request, "SCMAR submitted to MENRO Admin for review.")
                return redirect("scmar_detail", pk=pk)
            messages.success(request, "Draft saved.")
            return redirect("scmar_edit", pk=pk)
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

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            # New accounts must confirm their email via OTP before they can
            # reach the dashboard. Don't log them in yet - send the code and
            # route through the same confirm_login_view used for that step.
            send_login_code(user)
            request.session["pending_user_id"] = user.id
            messages.info(
                request,
                f"We've sent a confirmation code to {user.email}. "
                f"Enter it below to activate your account.",
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
    }

    if request.method == "POST":
        form = ProfileEditForm(request.POST, request.FILES, user=request.user, initial=initial)
        if form.is_valid():
            # SECURITY: only username, full name, and avatar are ever applied
            # here. Role, barangay, account status, and date_joined are NOT
            # fields on ProfileEditForm, so they can never be changed via
            # this endpoint - not even by a tampered/forged POST request.
            request.user.username = form.cleaned_data["username"]
            full_name = form.cleaned_data["full_name"].strip()
            if full_name:
                first, _, last = full_name.partition(" ")
                request.user.first_name = first
                request.user.last_name = last
            else:
                request.user.first_name = ""
                request.user.last_name = ""
            request.user.save(update_fields=["username", "first_name", "last_name"])

            avatar_file = form.cleaned_data.get("avatar")
            if avatar_file:
                profile_obj.avatar = avatar_file
                profile_obj.save(update_fields=["avatar"])

            messages.success(request, "Profile updated.")
            return redirect("profile")
    else:
        form = ProfileEditForm(user=request.user, initial=initial)

    return render(request, "waste/profile.html", {"form": form, "profile_obj": profile_obj})


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

def send_login_code(user):
    """Create a new LoginVerification code for `user` and email it to them.
    Any previously-issued, still-unused codes for that user are discarded
    first so only the latest code is ever valid."""
    LoginVerification.objects.filter(user=user, is_used=False).delete()
    code = LoginVerification.generate_code()
    LoginVerification.objects.create(user=user, code=code)
    send_mail(
        subject="Your SWMS Carigara confirmation code",
        message=(
            f"Your confirmation code is {code}. It expires in 10 minutes.\n\n"
            f"If you didn't request this, you can safely ignore this email."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )


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
    user_id = request.session.get("pending_user_id")
    if not user_id:
        return redirect("login")

    user = AuthUser.objects.filter(id=user_id).first()
    if not user:
        return redirect("login")

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

                auth_login(request, user)
                del request.session["pending_user_id"]
                messages.success(request, f"Welcome, {user.username}!")
                return redirect("dashboard")
    else:
        form = ConfirmCodeForm()

    return render(request, "registration/confirm_login.html", {"form": form, "email": user.email})


def resend_code_view(request):
    user_id = request.session.get("pending_user_id")
    if user_id:
        user = AuthUser.objects.filter(id=user_id).first()
        if user:
            send_login_code(user)
            messages.success(request, "A new code has been sent.")
    return redirect("confirm_login")