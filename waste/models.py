import random
import calendar
from datetime import timedelta, date, datetime

from django.db import models
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError
import os
from decimal import Decimal

from .storage import document_storage

from .pdf_convert import convert_field_to_pdf


ZERO_DECIMAL = Decimal("0")

BARANGAY_CHOICES = [
    ("Bagong Lipunan", "Bagong Lipunan"),
    ("Balilit", "Balilit"),
    ("Barayong", "Barayong"),
    ("Barugohay Central", "Barugohay Central"),
    ("Barugohay Norte", "Barugohay Norte"),
    ("Barugohay Sur", "Barugohay Sur"),
    ("Baybay", "Baybay"),
    ("Binibihan", "Binibihan"),
    ("Bislig", "Bislig"),
    ("Caghalo", "Caghalo"),
    ("Camansi", "Camansi"),
    ("Canal", "Canal"),
    ("Candigahub", "Candigahub"),
    ("Canfabi", "Canfabi"),
    ("Canlampay", "Canlampay"),
    ("Cogon", "Cogon"),
    ("Cutay", "Cutay"),
    ("East Guindapunan", "East Guindapunan"),
    ("East Visoria", "East Visoria"),
    ("Hiluctogan", "Hiluctogan"),
    ("Jugaban", "Jugaban"),
    ("Libo", "Libo"),
    ("Lower Hiraan", "Lower Hiraan"),
    ("Lower Sogod", "Lower Sogod"),
    ("Macalpi", "Macalpi"),
    ("Manloy", "Manloy"),
    ("Nauguisan", "Nauguisan"),
    ("Paglaum", "Paglaum"),
    ("Pangna", "Pangna"),
    ("Parag-um", "Parag-um"),
    ("Parina", "Parina"),
    ("Piloro", "Piloro"),
    ("Ponong", "Ponong"),
    ("Rizal", "Rizal"),
    ("Sagkahan", "Sagkahan"),
    ("San Isidro", "San Isidro"),
    ("San Juan", "San Juan"),
    ("San Mateo", "San Mateo"),
    ("Sawang", "Sawang"),
    ("Sta. Fe", "Sta. Fe"),
    ("Tagak", "Tagak"),
    ("Tangnan", "Tangnan"),
    ("Tigbao", "Tigbao"),
    ("Tinaguban", "Tinaguban"),
    ("Upper Hiraan", "Upper Hiraan"),
    ("Upper Sogod", "Upper Sogod"),
    ("Uyawan", "Uyawan"),
    ("West Guindapunan", "West Guindapunan"),
    ("West Visoria", "West Visoria"),
]

WASTE_TYPE_CHOICES = [
    ("Biodegradable", "Biodegradable"),
    ("Non-biodegradable", "Non-biodegradable"),
    ("Recyclable", "Recyclable"),
    ("Hazardous", "Hazardous"),
]

COMPLAINT_STATUS_CHOICES = [
    ("Pending", "Pending"),
    ("In Progress", "In Progress"),
    ("Resolved", "Resolved"),
]

COLLECTION_STATUS_CHOICES = [
    ("Scheduled", "Scheduled"),
    ("Ongoing", "Ongoing"),
    ("Completed", "Completed"),
]

COLLECTION_FREQUENCY_CHOICES = [
    ("Weekly", "Weekly"),
    ("Monthly", "Monthly"),
]

WEEKDAY_CHOICES = [
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
]


def week_bounds(day):
    """Monday and Sunday (both dates) of the week that contains `day`."""
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


ROLE_CHOICES = [
    ("admin", "Administrator (MENRO)"),
    ("staff", "Collection Staff"),
    ("user", "Barangay User"),
]

ACTION_PLAN_STATUS_CHOICES = [
    ("Planned", "Planned"),
    ("Ongoing", "Ongoing"),
    ("Completed", "Completed"),
]

# ---- Barangay -> MENRO Admin submission/review workflow ----
# The Barangay is always the SENDER/SUBMITTER. MENRO Admin is always the
# RECEIVER/REVIEWER. Shared by ActionPlan and Accomplishment.
REVIEW_STATUS_CHOICES = [
    ("For Review", "For Review"),
    ("Approved", "Approved"),
    ("Rejected", "Rejected"),
]

# ---- Shared file-upload validation for Action Plan / Accomplishment reports ----
ALLOWED_REPORT_EXTENSIONS = [".pdf", ".doc", ".docx"]
MAX_REPORT_FILE_SIZE_MB = 10

# ---- Shared image-upload validation for supporting evidence images ----
ALLOWED_IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png"]
MAX_IMAGE_FILE_SIZE_MB = 5


def _is_new_upload(value):
    """Only size-check files being uploaded now.

    Files already stored (e.g. on Cloudinary) would need a network HEAD request
    just to read their size, which can fail and was causing HTTP 500 on edit.
    """
    return not getattr(value, "_committed", False)


def validate_report_file(value):
    """
    Validator reused by both ActionPlan.file and Accomplishment.report_file.
    Kept simple on purpose: extension whitelist + a max size, no cloud storage.
    """
    ext = os.path.splitext(value.name)[1].lower()
    if ext not in ALLOWED_REPORT_EXTENSIONS:
        raise ValidationError(
            "Unsupported file type. Only PDF, DOC, and DOCX files are allowed."
        )
    max_bytes = MAX_REPORT_FILE_SIZE_MB * 1024 * 1024
    if _is_new_upload(value) and value.size > max_bytes:
        raise ValidationError(
            f"File is too large. Maximum allowed size is {MAX_REPORT_FILE_SIZE_MB} MB."
        )


def validate_supporting_image(value):
    """
    Validator reused by both ActionPlan.supporting_image and
    Accomplishment.supporting_image. Extension whitelist + a max size,
    same pattern as validate_report_file.
    """
    ext = os.path.splitext(value.name)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError(
            "Unsupported image type. Only JPG, JPEG, and PNG files are allowed."
        )
    max_bytes = MAX_IMAGE_FILE_SIZE_MB * 1024 * 1024
    if _is_new_upload(value) and value.size > max_bytes:
        raise ValidationError(
            f"Image is too large. Maximum allowed size is {MAX_IMAGE_FILE_SIZE_MB} MB."
        )


class Profile(models.Model):
    """Extends the built-in User with a role for access control."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="staff")
    barangay = models.CharField(
        max_length=50, choices=BARANGAY_CHOICES, blank=True, null=True,
        help_text="Required for Barangay User accounts. Ignored for Admin/Staff.",
    )
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    phone_number = models.CharField(
        max_length=20, blank=True, null=True,
        help_text="Optional contact number, e.g. 09171234567.",
    )
    email_verified = models.BooleanField(
        default=False,
        help_text="True once the user has confirmed the OTP code sent at registration.",
    )

    def clean(self):
        # One Barangay User account per barangay (enforced here so the Django
        # admin and any ModelForm reject duplicates, same as the register page).
        super().clean()
        if self.role == "user" and self.barangay:
            dupes = Profile.objects.filter(role="user", barangay=self.barangay)
            if self.pk:
                dupes = dupes.exclude(pk=self.pk)
            if dupes.exists():
                from django.core.exceptions import ValidationError
                raise ValidationError({"barangay": "An account for this barangay already exists."})

    def __str__(self):
        if self.role == "user" and self.barangay:
            return f"{self.user.username} ({self.get_role_display()} - {self.barangay})"
        return f"{self.user.username} ({self.get_role_display()})"


class Collection(models.Model):
    barangay = models.CharField(max_length=50, choices=BARANGAY_CHOICES)
    waste_type = models.CharField(max_length=30, choices=WASTE_TYPE_CHOICES)
    weight_kg = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text="Actual weight collected. Filled in once the collection is marked Completed.",
    )
    collector = models.CharField(max_length=100, help_text="Collector name or truck ID")
    status = models.CharField(max_length=15, choices=COLLECTION_STATUS_CHOICES, default="Scheduled")
    scheduled_date = models.DateTimeField(
        null=True, blank=True,
        help_text="When this collection is scheduled to happen.",
    )
    date_collected = models.DateTimeField(
        null=True, blank=True,
        help_text="Set automatically once the collection is marked Completed.",
    )
    frequency = models.CharField(
        max_length=10, choices=COLLECTION_FREQUENCY_CHOICES, blank=True, default="",
        help_text="Weekly or Monthly. Filled in automatically when the collection comes from a recurring schedule.",
    )
    notes = models.TextField(
        blank=True, default="",
        help_text="Optional notes from the barangay about this collection.",
    )
    schedule = models.ForeignKey(
        "RecurringCollectionSchedule", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="collections",
        help_text="The recurring schedule that auto-created this collection (if any).",
    )
    logged_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="collections_scheduled",
        help_text="Admin who scheduled this collection.",
    )
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="collections_monitored",
        help_text="Barangay user who last updated the monitoring status.",
    )

    class Meta:
        ordering = ["-scheduled_date", "-date_collected"]

    def __str__(self):
        return f"{self.barangay} - {self.waste_type} ({self.status})"

    def get_absolute_url(self):
        return reverse("collection_list")


class Complaint(models.Model):
    barangay = models.CharField(max_length=50, choices=BARANGAY_CHOICES)
    resident_name = models.CharField(max_length=100)
    contact_number = models.CharField(max_length=20, blank=True)
    issue = models.TextField()
    date_filed = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=15, choices=COMPLAINT_STATUS_CHOICES, default="Pending")
    filed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-date_filed"]

    def __str__(self):
        return f"#{self.id} - {self.resident_name} ({self.status})"

    def get_absolute_url(self):
        return reverse("complaint_list")


class Accomplishment(models.Model):
    title = models.CharField(
        max_length=150,
        help_text="e.g. Establishment of MRF, HAPAG, Desilting, BARKADA Day",
    )
    barangay = models.CharField(max_length=50, choices=BARANGAY_CHOICES, blank=True)
    description = models.TextField(blank=True)
    date_accomplished = models.DateField()
    logged_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    date_logged = models.DateTimeField(auto_now_add=True)
    due_date = models.DateField(
        blank=True, null=True,
        help_text="Optional deadline for submitting this accomplishment report. Leave blank if there is no deadline to track.",
    )
    submission_date = models.DateField(
        blank=True, null=True,
        help_text="Date the accomplishment report was actually submitted. Leave blank if not yet submitted.",
    )
    report_file = models.FileField(
        upload_to="accomplishment_reports/", blank=True, null=True,
        storage=document_storage,
        validators=[validate_report_file],
        help_text="Upload the accomplishment report document (PDF, DOC, or DOCX).",
    )
    supporting_image = models.ImageField(
        upload_to="accomplishment_evidence/", blank=True, null=True,
        validators=[validate_supporting_image],
        help_text="Optional supporting photo/evidence (JPG, JPEG, or PNG).",
    )

    # ---- Submission / review workflow: Barangay (sender) -> MENRO Admin (receiver) ----
    review_status = models.CharField(
        max_length=15, choices=REVIEW_STATUS_CHOICES, default="For Review",
        help_text="Set by MENRO Admin. The Barangay cannot review or approve its own submission.",
    )
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="accomplishments_reviewed",
        help_text="MENRO Admin who reviewed this submission.",
    )
    review_date = models.DateTimeField(blank=True, null=True)
    review_remarks = models.TextField(
        blank=True, help_text="MENRO Admin's remarks on the approval/rejection decision.",
    )

    class Meta:
        ordering = ["-date_accomplished"]

    def save(self, *args, **kwargs):
        # Uploaded DOC/DOCX reports are converted to PDF when they are submitted.
        convert_field_to_pdf(self, "report_file")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} - {self.barangay or 'Municipal-wide'} ({self.date_accomplished})"

    def get_absolute_url(self):
        return reverse("accomplishment_list")

    @property
    def submitted_by(self):
        """The Barangay user who created/submitted this report. Alias of logged_by."""
        return self.logged_by

    def get_submission_status(self, today=None):
        """
        Mirrors ActionPlan.get_submission_status(). Returns None when there's
        no due_date set (e.g. older records), so callers can show
        "No deadline set" instead of a misleading status.
        """
        if not self.due_date:
            return None

        if today is None:
            today = timezone.localdate()

        if self.submission_date:
            if self.submission_date <= self.due_date:
                return "Submitted On Time"
            return "Submitted Late"

        if today > self.due_date:
            return "Overdue"
        return "Pending"


class ActionPlan(models.Model):
    title = models.CharField(
        max_length=150,
        help_text="e.g. Establishment of MRF, HAPAG, Desilting, BARKADA Day",
    )
    barangay = models.CharField(max_length=50, choices=BARANGAY_CHOICES, blank=True)
    description = models.TextField(blank=True)
    budget = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Estimated budget for this activity, submitted by the barangay (PHP).",
    )
    target_date = models.DateField(
        null=True, blank=True,
        help_text="Due date / deadline for this action plan report. Set by the MENRO Admin only.",
    )
    status = models.CharField(max_length=15, choices=ACTION_PLAN_STATUS_CHOICES, default="Planned")
    responsible_person = models.CharField(max_length=100, blank=True, help_text="Person or office in-charge")
    submission_date = models.DateField(
        blank=True, null=True,
        help_text="Date the barangay actually submitted the Action Plan / Accomplishment Report",
    )
    remarks = models.TextField(blank=True, help_text="Optional notes about the submission")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    date_created = models.DateTimeField(auto_now_add=True)
    file = models.FileField(
        upload_to="action_plans/", blank=True, null=True,
        storage=document_storage,
        validators=[validate_report_file],
        help_text="Upload the Action Plan document (PDF, DOC, or DOCX).",
    )
    supporting_image = models.ImageField(
        upload_to="action_plan_evidence/", blank=True, null=True,
        validators=[validate_supporting_image],
        help_text="Optional supporting photo/evidence (JPG, JPEG, or PNG).",
    )

    # ---- Submission / review workflow: Barangay (sender) -> MENRO Admin (receiver) ----
    review_status = models.CharField(
        max_length=15, choices=REVIEW_STATUS_CHOICES, default="For Review",
        help_text="Set by MENRO Admin. The Barangay cannot review or approve its own submission.",
    )
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="action_plans_reviewed",
        help_text="MENRO Admin who reviewed this submission.",
    )
    review_date = models.DateTimeField(blank=True, null=True)
    review_remarks = models.TextField(
        blank=True, help_text="MENRO Admin's remarks on the approval/rejection decision.",
    )
    submitted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="action_plans_submitted",
        help_text=(
            "The Barangay user who filled in and submitted this Action Plan "
            "(budget, document, supporting evidence) to MENRO Admin. MENRO "
            "Admin creates the assignment (title, barangay, due date); the "
            "Barangay is the one who submits it."
        ),
    )

    class Meta:
        ordering = ["target_date"]

    def save(self, *args, **kwargs):
        # Uploaded DOC/DOCX reports are converted to PDF when they are submitted.
        convert_field_to_pdf(self, "file")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} - {self.barangay or 'Municipal-wide'} ({self.status})"

    def get_absolute_url(self):
        return reverse("action_plan_list")

    def get_submission_status(self, today=None):
        """
        Determines compliance status based on target_date (deadline) and
        submission_date (when the barangay actually submitted), compared to today.
        Computed on the fly - never stored - so it's always accurate.
        """
        if today is None:
            today = timezone.localdate()

        if not self.target_date:
            # MENRO Admin hasn't set a due date yet.
            return "Awaiting Due Date"

        if self.submission_date:
            if self.submission_date <= self.target_date:
                return "Submitted On Time"
            return "Submitted Late"

        if today > self.target_date:
            return "Overdue"
        return "Pending"

    def get_display_status(self, today=None):
        """
        The Status shown to users is derived from Compliance, so the two
        can never fall out of sync (e.g. Overdue while Status still reads
        Ongoing). Computed on the fly - never stored - so it's always
        accurate, even for records created before this logic existed.

          - Compliance "Submitted On Time" -> Status "Completed"
          - Compliance "Submitted Late"    -> Status "Late Submission"
          - Compliance "Overdue"           -> Status "No Submission"
          - Otherwise                      -> whatever MENRO Admin set
                                               (Planned / Ongoing / Completed)
        """
        compliance = self.get_submission_status(today)
        if compliance == "Submitted On Time":
            return "Completed"
        if compliance == "Submitted Late":
            return "Late Submission"
        if compliance == "Overdue":
            return "No Submission"
        return self.status


# ---- SCMAR workflow statuses ----
# The Barangay is always the CREATOR / SUBMITTER. MENRO Admin is always the
# RECEIVER / REVIEWER / APPROVER. These two roles are never reversed.
SCMAR_STATUS_CHOICES = [
    ("Draft", "Draft"),
    ("Submitted", "Submitted"),
    ("Under Review", "Under Review"),
    ("Returned for Revision", "Returned for Revision"),
    ("Approved", "Approved"),
]

SCMAR_PRIORITY_CHOICES = [
    ("Low", "Low"),
    ("Medium", "Medium"),
    ("High", "High"),
]


class SCMAR(models.Model):
    """
    SCMAR = Solid Waste Collection and Management Assessment Report.

    IMPORTANT: SCMAR is NOT a separate data-entry module. It is a COMBINED
    ASSESSMENT that gathers and summarizes data already stored in the
    Complaints, Collection, ActionPlan, and Accomplishment models for a
    given Barangay + reporting period, and adds a narrative overall
    assessment on top of that. It stores no duplicate complaint,
    collection, action-plan, or accomplishment records - see
    `complaints_summary`, `collections_summary`, `action_plans_summary`,
    and `accomplishments_summary` below, which pull live from those
    modules using `period_start`/`period_end`.

    A formal assessment report PREPARED AND SUBMITTED BY A BARANGAY to the
    MENRO Admin for review and approval. This is distinct from the system-
    generated "Monthly Summary Report" under Reports:

    - SCMAR: Barangay-authored assessment that combines existing
      Complaints/Collections/Action Plans/Accomplishments data with a
      narrative overall assessment, recommendations, and budget summary.
      It goes through a Draft -> Submitted -> Under Review -> Approved /
      Returned workflow.
    - Reports: auto-generated statistics/monitoring views (see
      views.reports / templates/waste/reports.html). No submission workflow.

    Role responsibility (never reversed):
    - Barangay User  = Creator / Submitter
    - MENRO Admin    = Receiver / Reviewer / Approver
    """

    # ---- 1. Report information ----
    barangay = models.CharField(max_length=50, choices=BARANGAY_CHOICES, blank=True)
    reporting_period = models.CharField(
        max_length=50,
        help_text="e.g. Q3 2026 or September 2026",
    )
    period_start = models.DateField(
        null=True, blank=True,
        help_text="Start date of the reporting period. Used to pull the relevant Complaints, Collections, Action Plans, and Accomplishments.",
    )
    period_end = models.DateField(
        null=True, blank=True,
        help_text="End date of the reporting period.",
    )
    date_prepared = models.DateField(null=True, blank=True)
    prepared_by = models.CharField(max_length=100, blank=True, help_text="Name of the person who prepared this report")

    # ---- 6. Overall assessment (narrative, written by the Barangay after
    # reviewing the compiled data from the other modules) ----
    overall_summary = models.TextField(
        blank=True, help_text="Overall summary of the Barangay's solid waste management performance this period.",
    )
    major_issues = models.TextField(blank=True, help_text="Major issues identified across complaints/collections/action plans.")
    improvement_areas = models.TextField(blank=True, help_text="Areas needing improvement.")
    positive_accomplishments = models.TextField(blank=True, help_text="Positive accomplishments worth highlighting.")
    recommended_action = models.TextField(blank=True)
    priority = models.CharField(max_length=10, choices=SCMAR_PRIORITY_CHOICES, blank=True)

    # ---- 7. Budget summary ----
    # Allocated budget is NOT stored here - it is computed from the barangay's
    # ActionPlan.budget records for this period (see allocated_budget below).
    # Amount spent isn't tracked anywhere else in the system, so it's the one
    # figure genuinely entered on the SCMAR itself.
    amount_spent = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Actual amount spent this period (PHP).",
    )
    budget_purpose = models.TextField(blank=True, help_text="What the budget was/will be used for")

    # ---- 8. Supporting documents ----
    # Additional/supplementary evidence for the assessment as a whole. This is
    # separate from the evidence already attached to individual Action Plans /
    # Accomplishments, which SCMAR displays by reference (see
    # `action_plans_summary` / `accomplishments_summary`) rather than copying.
    evidence_photo = models.ImageField(
        upload_to="scmar_evidence/", blank=True, null=True,
        validators=[validate_supporting_image],
        help_text="Optional additional photo evidence (JPG, JPEG, or PNG).",
    )
    evidence_document = models.FileField(
        upload_to="scmar_reports/", blank=True, null=True,
        storage=document_storage,
        validators=[validate_report_file],
        help_text="Optional additional supporting document (PDF, DOC, or DOCX).",
    )

    # ---- Workflow: Barangay (creator/submitter) -> MENRO Admin (receiver/reviewer/approver) ----
    status = models.CharField(max_length=25, choices=SCMAR_STATUS_CHOICES, default="Draft")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="scmars_created")
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    submitted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="scmars_submitted",
        help_text="The Barangay user who submitted this SCMAR to MENRO Admin.",
    )
    submission_date = models.DateTimeField(blank=True, null=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="scmars_reviewed",
        help_text="MENRO Admin who reviewed this submission.",
    )
    review_date = models.DateTimeField(blank=True, null=True)
    review_remarks = models.TextField(
        blank=True, help_text="MENRO Admin's remarks for the Barangay (required when returning for revision).",
    )

    class Meta:
        ordering = ["-date_created"]
        verbose_name = "SCMAR"
        verbose_name_plural = "SCMARs"

    def save(self, *args, **kwargs):
        # Uploaded DOC/DOCX reports are converted to PDF when they are submitted.
        convert_field_to_pdf(self, "evidence_document")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"SCMAR - {self.barangay or 'Municipal-wide'} ({self.reporting_period}) - {self.status}"

    def get_absolute_url(self):
        return reverse("scmar_detail", args=[self.pk])

    @property
    def is_editable(self):
        """Barangay may only create/edit while a SCMAR is Draft or Returned for Revision."""
        return self.status in ("Draft", "Returned for Revision")

    # ------------------------------------------------------------------
    # Combined-assessment helpers.
    #
    # SCMAR does not store its own complaint/collection/action-plan/
    # accomplishment records. Instead, each of these pulls the relevant
    # rows straight from the existing modules, scoped to this SCMAR's
    # barangay and reporting period (period_start/period_end). If no
    # period is set, they fall back to "all records for this barangay".
    # ------------------------------------------------------------------

    def _scope(self, queryset, barangay_field="barangay"):
        if self.barangay:
            queryset = queryset.filter(**{barangay_field: self.barangay})
        return queryset

    def _in_period(self, queryset, date_field):
        if self.period_start:
            queryset = queryset.filter(**{f"{date_field}__gte": self.period_start})
        if self.period_end:
            queryset = queryset.filter(**{f"{date_field}__lte": self.period_end})
        return queryset

    @property
    def complaints_qs(self):
        qs = self._scope(Complaint.objects.all())
        return self._in_period(qs, "date_filed__date")

    @property
    def collections_qs(self):
        qs = self._scope(Collection.objects.all())
        if self.period_start or self.period_end:
            qs = qs.filter(
                models.Q(scheduled_date__date__range=(self.period_start or date.min, self.period_end or date.max)) |
                models.Q(date_collected__date__range=(self.period_start or date.min, self.period_end or date.max))
            )
        return qs

    @property
    def action_plans_qs(self):
        qs = self._scope(ActionPlan.objects.all())
        return self._in_period(qs, "date_created__date")

    @property
    def accomplishments_qs(self):
        qs = self._scope(Accomplishment.objects.all())
        return self._in_period(qs, "date_accomplished")

    @property
    def complaints_summary(self):
        """Pulled from the existing Complaints module - see complaints_qs."""
        qs = self.complaints_qs
        total = qs.count()
        pending = qs.filter(status="Pending").count()
        in_progress = qs.filter(status="In Progress").count()
        resolved = qs.filter(status="Resolved").count()
        top_issues = list(qs.order_by("-date_filed").values_list("issue", flat=True)[:5])
        return {
            "queryset": qs,
            "total": total,
            "pending": pending,
            "in_progress": in_progress,
            "resolved": resolved,
            "top_issues": top_issues,
        }

    @property
    def collections_summary(self):
        """Pulled from the existing Collections module - see collections_qs."""
        qs = self.collections_qs
        total = qs.count()
        scheduled = qs.filter(status="Scheduled").count()
        ongoing = qs.filter(status="Ongoing").count()
        completed = qs.filter(status="Completed").count()
        total_weight = qs.aggregate(total=models.Sum("weight_kg"))["total"]
        schedules = sorted({
            c for c in qs.exclude(collector="").values_list("waste_type", flat=True).distinct()
        })

        # Waste collected per waste type, computed from the Collection records
        # (weight_kg is filled in by the Barangay when it marks a pickup
        # Completed). Nothing here is typed in on the SCMAR itself.
        type_colors = {
            "Biodegradable": "#65A30D",
            "Non-biodegradable": "#64748B",
            "Recyclable": "#2563EB",
            "Hazardous": "#DC2626",
        }
        grand = total_weight or 0
        by_type = []
        for key, label in WASTE_TYPE_CHOICES:
            t_qs = qs.filter(waste_type=key)
            t_weight = t_qs.aggregate(total=models.Sum("weight_kg"))["total"] or 0
            by_type.append({
                "waste_type": label,
                "color": type_colors.get(key, "#94A3B8"),
                "count": t_qs.count(),
                "completed": t_qs.filter(status="Completed").count(),
                "weight_kg": t_weight,
                "pct": (float(t_weight) / float(grand) * 100) if grand else 0,
            })

        return {
            "queryset": qs,
            "total": total,
            "scheduled": scheduled,
            "ongoing": ongoing,
            "completed": completed,
            "not_completed": scheduled + ongoing,
            "total_weight_kg": total_weight,
            "waste_types_covered": schedules,
            "by_type": by_type,
            "by_week": self._collections_by_week(qs),
        }

    def _collections_by_week(self, qs):
        """
        Week-by-week (Monday-Sunday) breakdown of the collections in this
        SCMAR's period. Barangays see their collections weekly in the
        Collections module; this rolls those same weekly records up into
        the monthly SCMAR so nothing has to be typed in twice.
        A collection is counted in the week it was scheduled for (or, if it
        has no scheduled date, the week it was actually collected).
        """
        weeks = {}
        for c in qs:
            when = c.scheduled_date or c.date_collected
            if not when:
                continue
            day = timezone.localtime(when).date()
            monday, sunday = week_bounds(day)
            row = weeks.setdefault(monday, {
                "week_start": monday, "week_end": sunday,
                "total": 0, "completed": 0, "weight_kg": ZERO_DECIMAL,
            })
            row["total"] += 1
            if c.status == "Completed":
                row["completed"] += 1
            if c.weight_kg:
                row["weight_kg"] += c.weight_kg
        return [weeks[k] for k in sorted(weeks)]

    @property
    def action_plans_summary(self):
        """Pulled from the existing Action Plans module - see action_plans_qs."""
        qs = self.action_plans_qs
        total = qs.count()
        planned = qs.filter(status="Planned").count()
        ongoing = qs.filter(status="Ongoing").count()
        completed = qs.filter(status="Completed").count()
        total_budget = qs.aggregate(total=models.Sum("budget"))["total"]
        return {
            "queryset": qs,
            "total": total,
            "planned": planned,
            "ongoing": ongoing,
            "completed": completed,
            "total_budget": total_budget,
        }

    @property
    def accomplishments_summary(self):
        """Pulled from the existing Accomplishments module - see accomplishments_qs."""
        qs = self.accomplishments_qs
        total = qs.count()
        approved = qs.filter(review_status="Approved").count()
        for_review = qs.filter(review_status="For Review").count()
        rejected = qs.filter(review_status="Rejected").count()
        return {
            "queryset": qs,
            "total": total,
            "approved": approved,
            "for_review": for_review,
            "rejected": rejected,
        }

    @property
    def allocated_budget(self):
        """
        Sum of ActionPlan.budget for this SCMAR's barangay/period. Not
        stored on SCMAR itself - Action Plans remain the single source of
        truth for allocated budget (see action_plans_summary).
        """
        return self.action_plans_summary["total_budget"]

    @property
    def remaining_budget(self):
        allocated = self.allocated_budget
        if allocated is None or self.amount_spent is None:
            return None
        return allocated - self.amount_spent


class RecurringCollectionSchedule(models.Model):
    """
    Set up once by MENRO Admin for a barangay: "collect this waste type from
    this barangay every WEEK (on this weekday) or every MONTH (on this day)".
    Collection rows are auto-generated from every active schedule (see
    generate_due_collections() below), so the Admin doesn't have to add the
    same collection by hand every time.

    Barangay Users only ever see their own barangay's collections, week by
    week. At the end of the month those weekly records roll up into the
    barangay's monthly SCMAR (see SCMAR.collections_summary).
    """
    barangay = models.CharField(max_length=50, choices=BARANGAY_CHOICES)
    waste_type = models.CharField(max_length=30, choices=WASTE_TYPE_CHOICES)
    collector = models.CharField(max_length=100, help_text="Collector name or truck ID")
    frequency = models.CharField(
        max_length=10, choices=COLLECTION_FREQUENCY_CHOICES, default="Monthly",
        help_text="Weekly = every week on the chosen weekday. Monthly = once a month on the chosen day.",
    )
    day_of_week = models.PositiveSmallIntegerField(
        choices=WEEKDAY_CHOICES, null=True, blank=True,
        help_text="Weekday for Weekly schedules.",
    )
    day_of_month = models.PositiveSmallIntegerField(
        default=1,
        help_text="Day of the month for Monthly schedules (1-28, to stay valid in every month).",
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    date_created = models.DateTimeField(auto_now_add=True)
    last_generated_for = models.DateField(
        null=True, blank=True,
        help_text="Monthly schedules: the month (1st of month stored) this schedule last auto-created a Collection for.",
    )

    class Meta:
        ordering = ["barangay", "waste_type"]

    def __str__(self):
        return f"{self.barangay} - {self.waste_type} ({self.when_label})"

    @property
    def when_label(self):
        """Human-readable cadence, e.g. 'every Monday' or 'every month, day 5'."""
        if self.frequency == "Weekly":
            if self.day_of_week is None:
                return "every week"
            return f"every {self.get_day_of_week_display()}"
        return f"every month, day {self.day_of_month}"

    def month_already_generated(self, today=None):
        if today is None:
            today = timezone.localdate()
        return self.last_generated_for is not None and (
            self.last_generated_for.year == today.year and self.last_generated_for.month == today.month
        )

    def occurrence_dates(self, window_start, window_end):
        """Every date this schedule falls on between window_start and window_end (inclusive)."""
        dates = []
        if self.frequency == "Weekly":
            if self.day_of_week is None:
                return dates
            # Never back-fill weeks from before the schedule existed.
            created_on = timezone.localtime(self.date_created).date() if self.date_created else window_start
            day = max(window_start, created_on)
            day += timedelta(days=(self.day_of_week - day.weekday()) % 7)
            while day <= window_end:
                dates.append(day)
                day += timedelta(days=7)
        else:
            year, month = window_start.year, window_start.month
            while date(year, month, 1) <= window_end:
                last_day = calendar.monthrange(year, month)[1]
                occurrence = date(year, month, min(self.day_of_month, last_day))
                if window_start <= occurrence <= window_end:
                    dates.append(occurrence)
                month += 1
                if month > 12:
                    year, month = year + 1, 1
        return dates

    def make_collections(self, window_start, window_end):
        """
        Creates a Scheduled Collection for every occurrence of this schedule
        in the window that doesn't have one yet. Returns the new Collections.
        Safe to call repeatedly - existing ones are never duplicated.
        """
        if not self.is_active:
            return []
        created = []
        for day in self.occurrence_dates(window_start, window_end):
            if self.frequency == "Monthly" and self.last_generated_for is not None and (
                self.last_generated_for.year == day.year and self.last_generated_for.month == day.month
            ):
                continue
            if self.frequency == "Monthly":
                # One collection per month, even if the admin later moves the day.
                already = Collection.objects.filter(
                    schedule=self, scheduled_date__year=day.year, scheduled_date__month=day.month,
                ).exists()
            else:
                already = Collection.objects.filter(schedule=self, scheduled_date__date=day).exists()
            if already:
                continue
            naive_dt = datetime.combine(day, datetime.min.time())
            scheduled_date = timezone.make_aware(naive_dt, timezone.get_current_timezone())
            created.append(Collection.objects.create(
                barangay=self.barangay,
                waste_type=self.waste_type,
                collector=self.collector,
                status="Scheduled",
                scheduled_date=scheduled_date,
                frequency=self.frequency,
                schedule=self,
                logged_by=self.created_by,
            ))
            if self.frequency == "Monthly":
                self.last_generated_for = date(day.year, day.month, 1)
                self.save(update_fields=["last_generated_for"])
        return created

    def make_collection_for_current_month(self, today=None):
        """Kept for older callers: generate what is due for this schedule right now."""
        if today is None:
            today = timezone.localdate()
        window_start, window_end = generation_window(today)
        created = self.make_collections(window_start, window_end)
        return created[0] if created else None


def generation_window(today=None):
    """
    The date range schedules are generated for: the whole current month,
    stretched to at least 14 days ahead so next week's collections are
    already visible near the end of a month. Weekly schedules never
    back-fill dates from before the schedule was created.
    """
    if today is None:
        today = timezone.localdate()
    window_start = date(today.year, today.month, 1)
    month_end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    window_end = max(month_end, today + timedelta(days=14))
    return window_start, window_end


def generate_due_collections(today=None):
    """
    Runs through every active RecurringCollectionSchedule (weekly and
    monthly) and auto-creates the Collections that are due and don't exist
    yet. Safe to call repeatedly (e.g. every time the Collections page
    loads, or from a scheduled/cron management command) - it's a no-op for
    anything already generated.
    """
    if today is None:
        today = timezone.localdate()
    window_start, window_end = generation_window(today)
    created = []
    for schedule in RecurringCollectionSchedule.objects.filter(is_active=True):
        created.extend(schedule.make_collections(window_start, window_end))
    return created


# ---------------------------------------------------------------------------
# Weekly collection input -> automatic monthly SCMAR
#
# Each week the Barangay records its collections (status + weight). Once
# 4 weeks of the month are complete - or every collection scheduled for the
# month is complete - that month's SCMAR is created automatically for the
# barangay, with its period filled in. The collection figures themselves are
# never copied: the SCMAR keeps pulling them live (see SCMAR.collections_summary).
# ---------------------------------------------------------------------------
WEEKS_NEEDED_FOR_SCMAR = 4


def month_collection_progress(barangay, month_start, today=None):
    """
    Weekly progress of a barangay's collections in one month.

    A week (Monday-Sunday) is "complete" when it has at least one collection
    and every one of them is Completed. The month is ready for its SCMAR when
    at least WEEKS_NEEDED_FOR_SCMAR weeks are complete, or - once the month
    is over - when every week that has collections is complete (e.g.
    barangays on a monthly schedule, or ones that only recorded a few weeks).
    """
    if today is None:
        today = timezone.localdate()
    month_end = date(month_start.year, month_start.month, calendar.monthrange(month_start.year, month_start.month)[1])
    qs = Collection.objects.filter(barangay=barangay).filter(
        models.Q(scheduled_date__date__gte=month_start, scheduled_date__date__lte=month_end) |
        models.Q(scheduled_date__isnull=True, date_collected__date__gte=month_start, date_collected__date__lte=month_end)
    )
    weeks = {}
    for c in qs:
        when = c.scheduled_date or c.date_collected
        monday, _sunday = week_bounds(timezone.localtime(when).date())
        row = weeks.setdefault(monday, [0, 0])
        row[0] += 1
        if c.status == "Completed":
            row[1] += 1
    total_weeks = len(weeks)
    complete_weeks = sum(1 for total, done in weeks.values() if total == done)
    all_done = total_weeks > 0 and complete_weeks == total_weeks
    return {
        "total_weeks": total_weeks,
        "complete_weeks": complete_weeks,
        "weeks_needed": WEEKS_NEEDED_FOR_SCMAR,
        "ready": complete_weeks >= WEEKS_NEEDED_FOR_SCMAR or (all_done and today > month_end),
    }


def ensure_month_scmar(barangay, month_start, user=None):
    """
    Creates the barangay's SCMAR for `month_start`'s month if the month is
    ready (see month_collection_progress) and none exists yet.

    The new SCMAR is a Draft owned by the Barangay: the collection figures
    are already in it, and the Barangay only has to add its assessment and
    save, which submits it to MENRO Admin as usual.

    Returns (scmar, created). Safe to call repeatedly - it never duplicates.
    """
    month_start = date(month_start.year, month_start.month, 1)
    existing = SCMAR.objects.filter(barangay=barangay, period_start=month_start).first()
    if existing:
        return existing, False
    if not month_collection_progress(barangay, month_start)["ready"]:
        return None, False

    owner = user
    if owner is None or not hasattr(owner, "profile") or owner.profile.role != "user":
        owner = User.objects.filter(profile__role="user", profile__barangay=barangay).first() or owner
    month_end = date(month_start.year, month_start.month, calendar.monthrange(month_start.year, month_start.month)[1])
    scmar = SCMAR.objects.create(
        barangay=barangay,
        reporting_period=month_start.strftime("%B %Y"),
        period_start=month_start,
        period_end=month_end,
        date_prepared=timezone.localdate(),
        prepared_by=(owner.get_full_name() or owner.username) if owner else "",
        status="Draft",
        created_by=owner,
    )
    return scmar, True


class LoginVerification(models.Model):
    """
    A short-lived one-time code emailed to a user who logs in using the
    "Email" login mode. Created by waste.views.send_login_code() and
    checked by waste.views.confirm_login_view(). Not used for username
    logins, which log in immediately without this extra step.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Code for {self.user.username} ({'used' if self.is_used else 'active'})"

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=10)

    @staticmethod
    def generate_code():
        return str(random.randint(100000, 999999))
class ReminderLog(models.Model):
    """Remembers which reminder emails were already sent, so nobody gets duplicates."""
    model = models.CharField(max_length=50)
    object_id = models.PositiveIntegerField()
    stage = models.CharField(max_length=20)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("model", "object_id", "stage")

    def __str__(self):
        return f"{self.model} #{self.object_id} - {self.stage}"