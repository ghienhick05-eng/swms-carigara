import hmac

from django import forms
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Collection, Complaint, Accomplishment, ActionPlan, SCMAR, Profile, BARANGAY_CHOICES, WEEKDAY_CHOICES, RecurringCollectionSchedule


class BarangayLockedFormMixin:
    """
    If the logged-in user is a Barangay User, hide the barangay field
    and force it to their own barangay on save.
    """

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.locked_barangay = None
        if user is not None and hasattr(user, "profile") and user.profile.role == "user":
            self.locked_barangay = user.profile.barangay
            if "barangay" in self.fields:
                self.fields["barangay"].initial = self.locked_barangay
                self.fields["barangay"].widget = forms.HiddenInput()
                self.fields["barangay"].disabled = True

    def clean_barangay(self):
        if self.locked_barangay:
            return self.locked_barangay
        return self.cleaned_data.get("barangay")


class CollectionForm(BarangayLockedFormMixin, forms.ModelForm):
    """Used by Admins to schedule a waste collection (barangay, type, when, collector/truck)."""

    class Meta:
        model = Collection
        fields = ["barangay", "scheduled_date", "collector"]
        widgets = {
            "barangay": forms.Select(attrs={"class": "form-control"}),
            "scheduled_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}, format="%Y-%m-%d"),
            "collector": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["scheduled_date"].input_formats = ["%Y-%m-%d"]


class CollectionStatusForm(forms.ModelForm):
    """Used by Barangay Users to mark a scheduled collection as Ongoing/Completed and log the actual weight."""

    class Meta:
        model = Collection
        fields = ["status", "weight_kg"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-control"}),
            "weight_kg": forms.NumberInput(attrs={
                "class": "form-control", "step": "0.01",
                "placeholder": "Actual weight collected (kg)",
            }),
        }


class RecurringCollectionScheduleForm(forms.ModelForm):
    """
    Used by MENRO Admin to set up a recurring collection for a barangay:
    pick the barangay (every waste type is scheduled together), then either
      - Weekly  -> a weekday (e.g. every Monday), or
      - Monthly -> a day of the month (1-28).
    Collections are then auto-created for that barangay on those dates.
    """

    class Meta:
        model = RecurringCollectionSchedule
        fields = ["barangay", "collector", "frequency", "day_of_week", "day_of_month", "is_active"]
        widgets = {
            "barangay": forms.Select(attrs={"class": "form-control"}),
            "collector": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. LGU Truck"}),
            "frequency": forms.Select(attrs={"class": "form-control", "id": "id_frequency"}),
            "day_of_week": forms.Select(attrs={"class": "form-control"}),
            "day_of_month": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 28}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        help_texts = {
            "day_of_week": "Collections repeat on this weekday every week.",
            "day_of_month": "1-28, so it stays valid even in February.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only the field that matches the chosen frequency is required.
        self.fields["day_of_week"].required = False
        self.fields["day_of_month"].required = False
        self.fields["day_of_week"].choices = [("", "Select weekday")] + list(WEEKDAY_CHOICES)

    def clean(self):
        cleaned_data = super().clean()
        frequency = cleaned_data.get("frequency")
        if frequency == "Weekly":
            if cleaned_data.get("day_of_week") is None:
                self.add_error("day_of_week", "Choose the weekday this barangay is collected on.")
            cleaned_data["day_of_month"] = cleaned_data.get("day_of_month") or 1
        elif frequency == "Monthly":
            day = cleaned_data.get("day_of_month")
            if day is None:
                self.add_error("day_of_month", "Enter the day of the month (1-28).")
            elif not 1 <= day <= 28:
                self.add_error("day_of_month", "Day of month must be between 1 and 28.")
            cleaned_data["day_of_week"] = None
        return cleaned_data


class ComplaintForm(BarangayLockedFormMixin, forms.ModelForm):
    class Meta:
        model = Complaint
        fields = ["barangay", "resident_name", "contact_number", "issue"]
        widgets = {
            "barangay": forms.Select(attrs={"class": "form-control"}),
            "resident_name": forms.TextInput(attrs={"class": "form-control"}),
            "contact_number": forms.TextInput(attrs={"class": "form-control"}),
            "issue": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }


class ComplaintStatusForm(forms.ModelForm):
    class Meta:
        model = Complaint
        fields = ["status"]
        widgets = {"status": forms.Select(attrs={"class": "form-control"})}


class AccomplishmentForm(BarangayLockedFormMixin, forms.ModelForm):
    class Meta:
        model = Accomplishment
        fields = ["title", "barangay", "description", "date_accomplished",
                  "due_date", "report_file", "supporting_image"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "list": "accomplishment-suggestions",
                "autocomplete": "off",
                "placeholder": "e.g. Establishment of MRF, HAPAG, Desilting, BARKADA Day",
            }),
            "barangay": forms.Select(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "date_accomplished": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "due_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "report_file": forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".pdf,.doc,.docx"}),
            "supporting_image": forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".jpg,.jpeg,.png"}),
        }


class ActionPlanForm(BarangayLockedFormMixin, forms.ModelForm):
    """
    Barangay Users submit Action Plans (title, barangay, description, budget,
    responsible person, remarks, file, supporting image) but do NOT set the
    due date - that's the MENRO Admin's call, made when they edit the plan
    (action_plan_edit, admin-only). The `target_date` field is removed
    entirely for non-admin users so it can't be set or tampered with from
    the submission form.
    """

    class Meta:
        model = ActionPlan
        fields = [
            "title", "barangay", "description", "budget", "target_date", "status",
            "responsible_person", "remarks", "file", "supporting_image",
        ]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "list": "action-plan-suggestions",
                "autocomplete": "off",
                "placeholder": "e.g. Establishment of MRF, HAPAG, Desilting, BARKADA Day",
            }),
            "barangay": forms.Select(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "budget": forms.NumberInput(attrs={
                "class": "form-control", "step": "0.01", "min": "0",
                "placeholder": "e.g. 15000.00",
            }),
            "target_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "status": forms.Select(attrs={"class": "form-control"}),
            "responsible_person": forms.TextInput(attrs={"class": "form-control"}),
            "remarks": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "file": forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".pdf,.doc,.docx"}),
            "supporting_image": forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".jpg,.jpeg,.png"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        is_admin_user = user is not None and (
            user.is_superuser or (hasattr(user, "profile") and user.profile.role == "admin")
        )
        if not is_admin_user:
            # Barangay Users never see or submit a due date - only MENRO sets it.
            self.fields.pop("target_date", None)


class ActionPlanScheduleForm(forms.ModelForm):
    """
    MENRO Admin's only lever on an Action Plan once the Barangay has
    submitted it: the schedule (due) date. Everything else about the plan
    - title, description, budget, responsible person, files - belongs to
    the Barangay that created and submitted it.
    """

    class Meta:
        model = ActionPlan
        fields = ["target_date"]
        widgets = {
            "target_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        }


class SCMARForm(BarangayLockedFormMixin, forms.ModelForm):
    """
    Barangay Users create, save as draft, edit, and submit the SCMAR
    (Solid Waste Collection and Management Assessment Report). MENRO Admin
    never fills this form out - it only reviews/approves/returns what the
    Barangay submits (see SCMARReviewForm).
    """

    class Meta:
        model = SCMAR
        fields = [
            "barangay", "reporting_period", "period_start", "period_end",
            "date_prepared", "prepared_by",
            "overall_summary", "major_issues", "improvement_areas", "positive_accomplishments",
            "recommended_action", "priority",
            "amount_spent", "budget_purpose",
            "evidence_photo", "evidence_document",
        ]
        widgets = {
            "barangay": forms.Select(attrs={"class": "form-control"}),
            "reporting_period": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Q3 2026"}),
            "period_start": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "period_end": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "date_prepared": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "prepared_by": forms.TextInput(attrs={"class": "form-control"}),

            "overall_summary": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "major_issues": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "improvement_areas": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "positive_accomplishments": forms.Textarea(attrs={"class": "form-control", "rows": 2}),

            "amount_spent": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "budget_purpose": forms.Textarea(attrs={"class": "form-control", "rows": 2}),

            "recommended_action": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "priority": forms.Select(attrs={"class": "form-control"}),

            "evidence_photo": forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".jpg,.jpeg,.png"}),
            "evidence_document": forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".pdf,.doc,.docx"}),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("period_start")
        end = cleaned.get("period_end")
        if start and end and start > end:
            self.add_error("period_end", "Period end date must be on or after the start date.")
        return cleaned


class SCMARReviewForm(forms.Form):
    """
    Used by MENRO Admin only, to approve or return a Barangay's SCMAR for
    revision. The Barangay never sees or uses this form - it cannot review
    or approve its own submission.
    """
    decision = forms.ChoiceField(
        choices=[("Approved", "Approve"), ("Returned for Revision", "Return for Revision")],
        widget=forms.HiddenInput(),
    )
    review_remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "class": "form-control", "rows": 3,
            "placeholder": "Remarks for the Barangay about this decision (required when returning for revision).",
        }),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == "Returned for Revision" and not cleaned.get("review_remarks"):
            self.add_error("review_remarks", "Please explain what needs to be revised.")
        return cleaned


class ActionPlanSubmissionForm(forms.ModelForm):
    """
    MENRO Admin creates the Action Plan assignment (title, barangay, due
    date, responsible person). The Barangay then fills in the estimated
    budget, uploads the Action Plan document and supporting evidence, and
    saves - which is what actually submits it to MENRO Admin for review.
    The Barangay cannot touch the title, barangay, target date, or status
    here; those belong to MENRO Admin.
    """

    class Meta:
        model = ActionPlan
        fields = ["budget", "file", "supporting_image"]
        widgets = {
            "budget": forms.NumberInput(attrs={
                "class": "form-control", "step": "0.01", "min": "0",
                "placeholder": "e.g. 15000.00",
            }),
            "file": forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".pdf,.doc,.docx"}),
            "supporting_image": forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".jpg,.jpeg,.png"}),
        }


class ReviewForm(forms.Form):
    """
    Used by MENRO Admin only, to approve or reject a Barangay's Action Plan
    or Accomplishment Report submission. The Barangay never sees or uses
    this form - it cannot review or approve its own submission.
    """
    decision = forms.ChoiceField(
        choices=[("Approved", "Approve"), ("Rejected", "Reject")],
        widget=forms.HiddenInput(),
    )
    review_remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "class": "form-control", "rows": 3,
            "placeholder": "Optional remarks for the Barangay about this decision",
        }),
    )


class TakenAwareSelect(forms.Select):
    """Select that shows barangays which already have an account as disabled."""
    taken = set()

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        if value in self.taken:
            option["attrs"]["disabled"] = True
            option["label"] = f"{label} (already has an account)"
        return option


class RegisterForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": "auth-input", "autocomplete": "email"}),
        help_text="You'll use this to log in and to receive login notifications. A personal email is fine.",
    )
    phone_number = forms.CharField(
        max_length=20,
        required=True,
        label="Mobile number",
        widget=forms.TextInput(attrs={
            "class": "auth-input",
            "autocomplete": "tel",
            "inputmode": "tel",
        }),
    )
    barangay = forms.ChoiceField(
        choices=BARANGAY_CHOICES,
        required=True,
        widget=forms.Select(attrs={"class": "auth-input"}),
        help_text="Select the barangay this account will manage.",
    )

    class Meta:
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"class": "auth-input"})
        self.fields["password1"].widget.attrs.update({"class": "auth-input"})
        self.fields["password2"].widget.attrs.update({"class": "auth-input"})
        # One account per barangay: hide barangays that already have one.
        taken = set(
            Profile.objects.filter(role="user", barangay__isnull=False)
            .exclude(barangay="")
            .values_list("barangay", flat=True)
        )
        # Barangays that already have an account are removed from the list
        # entirely, so only available ones can be picked.
        self.fields["barangay"].choices = [
            (value, label)
            for value, label in self.fields["barangay"].choices
            if value not in taken
        ]
        self.fields["barangay"].error_messages["invalid_choice"] = (
            "That barangay already has an account or isn't available."
        )

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_phone_number(self):
        phone = self.cleaned_data.get("phone_number", "").strip()
        digits = phone.replace(" ", "").replace("-", "").lstrip("+")
        if not digits.isdigit() or not (7 <= len(digits) <= 15):
            raise forms.ValidationError("Enter a valid mobile number.")
        return phone

    def clean_barangay(self):
        barangay = self.cleaned_data.get("barangay")
        if barangay and Profile.objects.filter(role="user", barangay=barangay).exists():
            raise forms.ValidationError("An account for this barangay already exists.")
        return barangay

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        # Inactive until the emailed code is confirmed; unconfirmed accounts are
        # deleted automatically (see purge_unverified_accounts in views.py).
        user.is_active = False
        if commit:
            user.save()
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.email_verified = False
            profile.role = "user"
            profile.barangay = self.cleaned_data["barangay"]
            profile.phone_number = self.cleaned_data["phone_number"]
            profile.save()
        return user


class ProfileAvatarForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["avatar"]
        widgets = {
            "avatar": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
        }


class ProfileEditForm(forms.Form):
    """
    Handles the fields a logged-in user is allowed to self-edit on the
    Profile page: username, full name, and avatar.

    SECURITY: this form intentionally has NO fields for role, barangay,
    account status (is_active), or date_joined. Email can be edited here, but
    a changed email is NOT saved directly: the profile view emails a code to
    the new address and only applies it after the code is confirmed. Those other fields are protected
    server-side - they are never read from this form and never written
    to the User/Profile objects in the profile view, regardless of what
    a tampered client request might contain.
    """
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "autocomplete": "username"}),
    )
    full_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "autocomplete": "name"}),
    )
    avatar = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={"class": "form-control", "autocomplete": "email"}),
    )
    phone_number = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "autocomplete": "tel",
            "placeholder": "e.g. 09171234567",
        }),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        # Every logged-in account (Barangay User, MENRO Admin, Staff) can
        # edit username, full name, avatar, email, and phone number here.

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if not email:
            raise forms.ValidationError("Email cannot be blank.")
        qs = User.objects.filter(email__iexact=email)
        if self.user is not None:
            qs = qs.exclude(pk=self.user.pk)
        if qs.exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        if not username:
            raise forms.ValidationError("Username cannot be blank.")
        qs = User.objects.filter(username__iexact=username)
        if self.user is not None:
            qs = qs.exclude(pk=self.user.pk)
        if qs.exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean_phone_number(self):
        phone = self.cleaned_data.get("phone_number", "").strip()
        if not phone:
            return ""
        digits = phone.replace(" ", "").replace("-", "").lstrip("+")
        if not digits.isdigit() or not (7 <= len(digits) <= 15):
            raise forms.ValidationError("Enter a valid phone number.")
        return phone


class ConfirmCodeForm(forms.Form):
    """
    Used on the "check your email" screen shown after a user logs in with
    the Email option. See waste.views.confirm_login_view().
    """
    code = forms.CharField(
        max_length=6,
        widget=forms.TextInput(attrs={
            "class": "auth-input",
            "autocomplete": "one-time-code",
            "inputmode": "numeric",
            "maxlength": "6",
            "aria-label": "6-digit confirmation code",
        })
    )


class EmailChangeForm(forms.Form):
    """
    New email address for any logged-in account. A confirmation code is sent
    to this new address and must be entered before the change is applied -
    see waste.views.change_email().
    """
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": "form-control", "autocomplete": "email"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if self.user is not None and email == (self.user.email or "").lower():
            raise forms.ValidationError("That is already your email.")
        qs = User.objects.filter(email__iexact=email)
        if self.user is not None:
            qs = qs.exclude(pk=self.user.pk)
        if qs.exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email