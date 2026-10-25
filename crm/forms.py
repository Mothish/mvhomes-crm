from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone

from .access import assignable_users, get_role
from .models import Activity, Booking, Lead, Profile, Project, SiteVisit, Team, normalize_phone, phone_validator


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format="%Y-%m-%d")


class DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format="%Y-%m-%dT%H:%M")


class PhoneField(forms.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 20)
        kwargs.setdefault("validators", [phone_validator])
        super().__init__(**kwargs)

    def to_python(self, value):
        return normalize_phone(super().to_python(value))


class StyledMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple)):
                continue
            widget.attrs.setdefault("class", "input")
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 3)


def user_label(u):
    return u.get_full_name() or u.username


class LeadForm(StyledMixin, forms.ModelForm):
    phone = PhoneField(label="Phone")
    alt_phone = PhoneField(label="Alternate phone", required=False)
    owner = forms.ModelChoiceField(
        queryset=None, required=False, label="Assign to", empty_label="Auto-assign (round-robin)"
    )

    class Meta:
        model = Lead
        fields = [
            "name", "phone", "alt_phone", "email", "area", "budget", "property_type", "project", "source",
            "temperature", "language", "next_followup", "notes",
        ]
        widgets = {"next_followup": DateTimeInput(), "notes": forms.Textarea}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = Project.objects.filter(is_active=True)
        self.fields["project"].empty_label = "Not decided"
        if self.instance.pk or user is None or not user.is_authenticated:
            del self.fields["owner"]
        else:
            self.fields["owner"].queryset = assignable_users(user)
            self.fields["owner"].label_from_instance = user_label
            if get_role(user) == Profile.EXECUTIVE:
                self.fields["owner"].queryset = self.fields["owner"].queryset.filter(pk=user.pk)
                self.fields["owner"].initial = user.pk
                self.fields["owner"].empty_label = None

    def validate_unique(self):
        # Duplicates are handled as re-enquiries by the view, not as form errors.
        if self.instance.pk:
            super().validate_unique()


class ActivityForm(StyledMixin, forms.Form):
    kind = forms.ChoiceField(choices=[(k, v) for k, v in Activity.KINDS if k not in ("system", "site_visit")],
                             label="Activity")
    outcome = forms.ChoiceField(choices=[("", "-")] + Activity.OUTCOMES, required=False)
    note = forms.CharField(widget=forms.Textarea, required=False, label="Notes")
    next_followup = forms.DateTimeField(required=False, widget=DateTimeInput(), label="Next follow-up")
    temperature = forms.ChoiceField(choices=Lead.TEMPERATURES, label="Lead temperature")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("kind") == "note" and not cleaned.get("note"):
            self.add_error("note", "Please write the note.")
        nf = cleaned.get("next_followup")
        if nf and nf < timezone.now() - timezone.timedelta(minutes=5):
            self.add_error("next_followup", "Follow-up time must be in the future.")
        return cleaned


class LostForm(StyledMixin, forms.Form):
    reason = forms.ChoiceField(choices=[("", "Select a reason")] + Lead.LOST_REASONS, label="Why was it lost?")
    note = forms.CharField(required=False, max_length=200, label="Details (optional)")


class SiteVisitForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = SiteVisit
        fields = ["project", "scheduled_at", "executive"]
        widgets = {"scheduled_at": DateTimeInput()}
        labels = {"scheduled_at": "Date & time"}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = Project.objects.filter(is_active=True)
        self.fields["executive"].queryset = assignable_users(user) if user else get_user_model().objects.none()
        self.fields["executive"].label_from_instance = user_label

    def clean_scheduled_at(self):
        value = self.cleaned_data["scheduled_at"]
        if value < timezone.now() - timezone.timedelta(hours=1):
            raise forms.ValidationError("Choose a time in the future.")
        return value


class VisitResultForm(StyledMixin, forms.Form):
    status = forms.ChoiceField(choices=[(SiteVisit.DONE, "Done"), (SiteVisit.NO_SHOW, "No-show"),
                                        (SiteVisit.CANCELLED, "Cancelled")])
    feedback = forms.CharField(widget=forms.Textarea, required=False, label="Customer feedback")


class BookingForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Booking
        fields = ["project", "unit_no", "deal_value", "booking_amount", "booking_date", "notes"]
        widgets = {"booking_date": DateInput()}

    def clean(self):
        cleaned = super().clean()
        deal, amount = cleaned.get("deal_value"), cleaned.get("booking_amount")
        if deal and amount and amount > deal:
            self.add_error("booking_amount", "Booking amount can't exceed the deal value.")
        if cleaned.get("booking_date") and cleaned["booking_date"] > timezone.localdate():
            self.add_error("booking_date", "Booking date can't be in the future.")
        return cleaned


class ReassignForm(StyledMixin, forms.Form):
    to_user = forms.ModelChoiceField(queryset=None, label="Reassign to")
    reason = forms.CharField(required=False, max_length=120)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["to_user"].queryset = assignable_users(user)
        self.fields["to_user"].label_from_instance = user_label


class ImportForm(StyledMixin, forms.Form):
    file = forms.FileField(label="Excel or CSV file", help_text=".xlsx or .csv, up to 5 MB")

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if not upload.name.lower().endswith((".xlsx", ".csv")):
            raise forms.ValidationError("Only .xlsx or .csv files are supported.")
        if upload.size > 5 * 1024 * 1024:
            raise forms.ValidationError("File is larger than 5 MB.")
        return upload


class ProjectForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "location", "property_types", "price_from", "price_to", "brochure_url", "is_active"]


class TeamForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name", "leader"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["leader"].queryset = get_user_model().objects.filter(profile__role=Profile.LEADER, is_active=True)
        self.fields["leader"].label_from_instance = user_label


class UserForm(StyledMixin, forms.Form):
    username = forms.SlugField(max_length=30)
    first_name = forms.CharField(max_length=60)
    last_name = forms.CharField(max_length=60, required=False)
    email = forms.EmailField(required=False)
    phone = forms.CharField(max_length=15, required=False)
    role = forms.ChoiceField(choices=Profile.ROLE_CHOICES)
    team = forms.ModelChoiceField(queryset=Team.objects.all(), required=False)
    projects = forms.ModelMultipleChoiceField(
        queryset=Project.objects.filter(is_active=True), required=False, widget=forms.CheckboxSelectMultiple,
        help_text="Projects this executive specialises in (empty = all).",
    )
    accepts_leads = forms.BooleanField(required=False, initial=True, label="Include in auto-assignment")
    is_active = forms.BooleanField(required=False, initial=True, label="Active (can log in)")
    password = forms.CharField(widget=forms.PasswordInput, required=False,
                               help_text="Required for new users. Leave blank to keep the current password.")

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        if instance is not None and "initial" not in kwargs:
            p = instance.profile
            kwargs["initial"] = {
                "username": instance.username, "first_name": instance.first_name, "last_name": instance.last_name,
                "email": instance.email, "phone": p.phone, "role": p.role, "team": p.team_id,
                "projects": list(p.projects.values_list("pk", flat=True)), "accepts_leads": p.accepts_leads,
                "is_active": instance.is_active,
            }
        super().__init__(*args, **kwargs)

    def clean_username(self):
        name = self.cleaned_data["username"]
        qs = get_user_model().objects.filter(username__iexact=name)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("This username is taken.")
        return name

    def clean_password(self):
        pw = self.cleaned_data.get("password")
        if not self.instance and not pw:
            raise forms.ValidationError("Set a password for the new user.")
        if pw:
            validate_password(pw)
        return pw

    def save(self):
        d = self.cleaned_data
        user = self.instance or get_user_model()(username=d["username"])
        user.username, user.first_name, user.last_name, user.email = d["username"], d["first_name"], d["last_name"], d["email"]
        user.is_active = d["is_active"]
        if d.get("password"):
            user.set_password(d["password"])
        user.save()
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.role, profile.team, profile.phone, profile.accepts_leads = d["role"], d["team"], d["phone"], d["accepts_leads"]
        profile.save()
        profile.projects.set(d["projects"])
        return user


class TransferForm(StyledMixin, forms.Form):
    to_user = forms.ModelChoiceField(queryset=None, required=False, label="Transfer to",
                                     empty_label="Distribute round-robin to other executives")
    deactivate = forms.BooleanField(required=False, initial=True, label="Deactivate this user after transfer")

    def __init__(self, *args, from_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["to_user"].queryset = get_user_model().objects.filter(
            is_active=True, profile__role__in=(Profile.EXECUTIVE, Profile.LEADER)
        ).exclude(pk=from_user.pk)
        self.fields["to_user"].label_from_instance = user_label


class EnquiryForm(forms.Form):
    """Public website form."""
    name = forms.CharField(max_length=120, widget=forms.TextInput(attrs={"class": "input", "placeholder": "Your name"}))
    phone = PhoneField(label="Mobile number", widget=forms.TextInput(attrs={"class": "input", "placeholder": "10-digit mobile"}))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={"class": "input", "placeholder": "Email (optional)"}))
    project = forms.ModelChoiceField(queryset=Project.objects.filter(is_active=True), required=False,
                                     empty_label="Any project", widget=forms.Select(attrs={"class": "input"}))
    property_type = forms.ChoiceField(choices=[("", "Property type")] + Lead.PROPERTY_TYPES, required=False,
                                      widget=forms.Select(attrs={"class": "input"}))
    budget = forms.ChoiceField(choices=[("", "Budget")] + Lead.BUDGETS, required=False,
                               widget=forms.Select(attrs={"class": "input"}))
    message = forms.CharField(required=False, max_length=500,
                              widget=forms.Textarea(attrs={"class": "input", "rows": 3, "placeholder": "Anything we should know?"}))
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))
    consent = forms.BooleanField(label=f"I agree to be contacted by {settings.COMPANY_NAME} by call / WhatsApp.")
