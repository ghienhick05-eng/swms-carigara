from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Collection, Complaint, Accomplishment, ActionPlan, SCMAR, Profile, BARANGAY_CHOICES, RecurringCollectionSchedule


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
        fields = ["barangay", "waste_type", "scheduled_date", "collector"]
        widgets = {
            "barangay": forms.Select(attrs={"class": "form-control"}),
            "waste_type": forms.Select(attrs={"class": "form-control"}),
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
    Used by MENRO Admin to set up a monthly recurring collection: pick a
    barangay + waste type + day of month, and a Collection gets auto-created
    for that combination every month going forward.
    """

    class Meta:
        model = RecurringCollectionSchedule
        fields = ["barangay", "waste_type", "collector", "day_of_month", "is_active"]
        widgets = {
            "barangay": forms.Select(attrs={"class": "form-control"}),
            "waste_type": forms.Select(attrs={"class": "form-control"}),
            "collector": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. LGU Truck"}),
            "day_of_month": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 28}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        help_texts = {
            "day_of_month": "1-28, so it stays valid even in February.",
        }

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get("status")
        weight_kg = cleaned_data.get("weight_kg")
        if status == "Completed" and weight_kg in (None, ""):
            self.add_error("weight_kg", "Enter the actual weight collected before marking this as Completed.")
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


class RegisterForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": "auth-input", "autocomplete": "email"}),
        help_text="You'll use this to log in and to receive login notifications.",
    )
    barangay = forms.ChoiceField(
        choices=BARANGAY_CHOICES,
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

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.role = "user"
            profile.barangay = self.cleaned_data["barangay"]
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
    account status (is_active), or date_joined. Those are protected
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

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

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


class ConfirmCodeForm(forms.Form):
    """
    Used on the "check your email" screen shown after a user logs in with
    the Email option. See waste.views.confirm_login_view().
    """
    code = forms.CharField(
        max_length=6,
        widget=forms.TextInput(attrs={
            "class": "auth-input",
            "placeholder": "6-digit code",
            "autocomplete": "one-time-code",
            "inputmode": "numeric",
        })
    )