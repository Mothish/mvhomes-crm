from datetime import time
from decimal import ROUND_HALF_UP, Decimal
import re

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from django.utils.html import format_html

from .access import assignable_users, get_role
from .locale_data import (
    BASE_CURRENCY, CURRENCY_CHOICES, DEFAULT_COUNTRY, DEFAULT_DIAL, DIAL_CHOICES, currency_for, current_currency,
    from_base, to_base,
)
from .models import (
    Activity, Booking, Lead, Profile, Project, ProjectDocument, SiteVisit, Team, normalize_phone, phone_validator,
)


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format="%Y-%m-%d")


def _time_label(hhmm):
    h, m = map(int, hhmm.split(":"))
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


TIME_SLOTS = [(f"{h:02d}:{m:02d}", _time_label(f"{h:02d}:{m:02d}")) for h in range(24) for m in (0, 30)]


class TimeSlotSelect(forms.Select):
    def get_context(self, name, value, attrs):
        # Keep an existing off-slot time (e.g. 10:17) selectable instead of silently dropping it.
        if value and value not in dict(self.choices):
            self.choices = sorted([*self.choices, (value, _time_label(value))])
        return super().get_context(name, value, attrs)


class DateTimeInput(forms.MultiWidget):
    """Date picker + time dropdown; unlike a native datetime-local picker, each closes after one click."""

    def __init__(self, attrs=None):
        super().__init__([DateInput(), TimeSlotSelect(choices=[("", "Select time")] + TIME_SLOTS)], attrs)

    def decompress(self, value):
        if not value:
            return [None, ""]
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return [value.date(), value.strftime("%H:%M")]

    def render(self, name, value, attrs=None, renderer=None):
        return format_html('<div class="dt-pair">{}</div>', super().render(name, value, attrs, renderer))


class PickerDateTimeField(forms.SplitDateTimeField):
    widget = DateTimeInput

    def __init__(self, **kwargs):
        kwargs.setdefault("input_time_formats", ["%H:%M"])
        super().__init__(**kwargs)

    def compress(self, data_list):
        if data_list and data_list[0] and not data_list[1]:
            data_list = [data_list[0], time(10, 0)]
        return super().compress(data_list)


class PhoneField(forms.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 20)
        kwargs.setdefault("validators", [phone_validator])
        super().__init__(**kwargs)

    def to_python(self, value):
        return normalize_phone(super().to_python(value))


class ProjectOrOtherField(forms.ModelChoiceField):
    """Project dropdown that also accepts "other"; LeadForm.clean() turns it into project_other text."""

    def to_python(self, value):
        if value == LeadForm.OTHER:
            return value
        return super().to_python(value)


class StyledMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple)):
                continue
            widget.attrs.setdefault("class", "input")
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 3)
            placeholder = f"Select {(field.label or name.replace('_', ' ')).lower()}"
            if isinstance(field, forms.ModelChoiceField):
                if field.empty_label == "---------":
                    field.empty_label = placeholder
            elif isinstance(field, forms.ChoiceField) and type(widget) is forms.Select:
                choices = list(field.choices)
                if choices and choices[0] == ("", "---------"):
                    field.choices = [("", placeholder)] + choices[1:]
                elif len(choices) > 1 and choices[0][0] != "":
                    # A cleared select must re-render as empty, not silently show its first option.
                    field.choices = [("", placeholder)] + choices


def user_label(u):
    return u.get_full_name() or u.username


def strip_dial_code(phone, dial):
    """Drop the country code if the user typed it into the number field too (e.g. +974 with +974 selected)."""
    code = dial.lstrip("+")
    if phone and code and phone.startswith(code) and len(phone) - len(code) >= 6:
        return phone[len(code):]
    return phone


class MoneyFormMixin:
    """Adds a currency dropdown; money_fields are shown in that currency and saved in the base currency."""
    money_fields = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        currency = self.initial_currency()
        field = forms.ChoiceField(choices=[("", "Select currency")] + CURRENCY_CHOICES, initial=currency, label="Currency")
        field.widget.attrs["class"] = "input"
        self.fields["currency"] = field
        for name in self.money_fields:
            if self.initial.get(name) not in (None, ""):
                self.initial[name] = from_base(self.initial[name], currency)
        order = list(self.fields)
        order.remove("currency")
        order.insert(order.index(self.money_fields[0]), "currency")
        self.order_fields(order)

    def initial_currency(self):
        return current_currency.get()

    def clean(self):
        cleaned = super().clean()
        currency = cleaned.get("currency") or BASE_CURRENCY
        for name in self.money_fields:
            if cleaned.get(name) is not None:
                cleaned[name] = to_base(cleaned[name], currency)
        return cleaned


class LeadForm(MoneyFormMixin, StyledMixin, forms.ModelForm):
    money_fields = ("budget_amount",)
    OTHER = "other"
    OTHER_FIELDS = ("property_type", "project", "source")
    phone_code = forms.ChoiceField(choices=DIAL_CHOICES, initial=DEFAULT_DIAL, label="Country code")
    phone = PhoneField(label="Mobile number")
    alt_phone = PhoneField(label="Alternate phone", required=False)
    project = ProjectOrOtherField(queryset=Project.objects.none(), required=False, label="Project")
    owner = forms.ModelChoiceField(
        queryset=None, required=False, label="Assign to", empty_label="Auto-assign (round-robin)"
    )

    class Meta:
        model = Lead
        fields = [
            "name", "email", "phone_code", "phone", "alt_phone", "country", "city", "area", "property_type",
            "property_type_other", "project", "project_other", "budget_amount", "source", "source_other",
            "temperature", "language", "next_followup", "notes",
        ]
        widgets = {
            "notes": forms.Textarea,
            "city": forms.TextInput(attrs={"data-combo": "city", "autocomplete": "off",
                                           "placeholder": "Select or type a city"}),
            "area": forms.TextInput(attrs={"data-combo": "area", "autocomplete": "off",
                                           "placeholder": "Select or type an area"}),
            "source_other": forms.TextInput(attrs={"placeholder": "e.g. LinkedIn, TikTok, Cityscape exhibition"}),
            "property_type_other": forms.TextInput(attrs={"placeholder": "e.g. Duplex, Plot, Office, Shop"}),
            "project_other": forms.TextInput(attrs={"placeholder": "Project or building name"}),
        }
        labels = {"budget_amount": "Budget", "source_other": "Specify source",
                  "property_type_other": "Specify property type", "project_other": "Specify project"}
        field_classes = {"next_followup": PickerDateTimeField}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = Project.objects.filter(is_active=True)
        self.fields["project"].empty_label = "Not decided"
        self.fields["city"].required = True
        self.fields["area"].required = True
        for name in self.OTHER_FIELDS:
            field, label = self.fields[name], "Other (type your own)"
            if name == "project":
                field.widget.choices = [*field.choices, (self.OTHER, label)]
            else:
                field.choices = [(k, label if k == self.OTHER else v) for k, v in field.choices]
        if self.instance.pk and not self.instance.project and self.instance.project_other:
            self.initial["project"] = self.OTHER
        if self.instance.pk or user is None or not user.is_authenticated:
            del self.fields["owner"]
        else:
            self.fields["owner"].queryset = assignable_users(user)
            self.fields["owner"].label_from_instance = user_label
            if get_role(user) == Profile.EXECUTIVE:
                self.fields["owner"].queryset = self.fields["owner"].queryset.filter(pk=user.pk)
                self.fields["owner"].initial = user.pk
                self.fields["owner"].empty_label = None

    def initial_currency(self):
        return currency_for(self.instance.country or DEFAULT_COUNTRY)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("area") and not cleaned.get("city"):
            self.add_error("city", "Choose the city before the area.")
        if cleaned.get("phone") and cleaned.get("phone_code"):
            cleaned["phone"] = strip_dial_code(cleaned["phone"], cleaned["phone_code"])
            if len(cleaned["phone"]) < 6:
                self.add_error("phone", "Enter the number without the country code.")
        for name in self.OTHER_FIELDS:
            other = f"{name}_other"
            if cleaned.get(name) == self.OTHER:
                cleaned[other] = (cleaned.get(other) or "").strip()
                if not cleaned[other]:
                    self.add_error(other, "Please type it in.")
                if name == "project":
                    cleaned["project"] = None
            else:
                cleaned[other] = ""
        return cleaned

    def _get_validation_exclusions(self):
        exclude = super()._get_validation_exclusions()
        # New leads with a known number become re-enquiries in capture_lead(), so skip the unique check here.
        if not self.instance.pk:
            exclude.update({"phone", "phone_code"})
        return exclude


class ActivityForm(StyledMixin, forms.Form):
    kind = forms.ChoiceField(choices=[(k, v) for k, v in Activity.KINDS if k not in ("system", "site_visit")],
                             label="Activity")
    outcome = forms.ChoiceField(choices=[("", "-")] + Activity.OUTCOMES, required=False)
    note = forms.CharField(widget=forms.Textarea, required=False, label="Notes")
    next_followup = PickerDateTimeField(required=False, label="Next follow-up")
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
        field_classes = {"scheduled_at": PickerDateTimeField}
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
                                        (SiteVisit.CANCELLED, "Cancelled")], initial=SiteVisit.DONE)
    feedback = forms.CharField(widget=forms.Textarea, required=False, label="Customer feedback")


class BookingForm(MoneyFormMixin, StyledMixin, forms.ModelForm):
    money_fields = ("deal_value", "booking_amount")

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


MAPS_COORD_PATTERNS = [
    r"@(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)",
    r"!3d(-?\d{1,2}\.\d+)!4d(-?\d{1,3}\.\d+)",
    r"[?&](?:q|query|ll|destination)=(-?\d{1,2}\.\d+),\s*(-?\d{1,3}\.\d+)",
]


def coords_from_maps_link(link):
    """(lat, lng) from a full Google Maps URL, or None. The URL is only parsed, never fetched."""
    for pattern in MAPS_COORD_PATTERNS:
        match = re.search(pattern, link or "")
        if match:
            lat, lng = (Decimal(v).quantize(Decimal("0.000001"), ROUND_HALF_UP) for v in match.groups())
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
    return None


class ProjectForm(MoneyFormMixin, StyledMixin, forms.ModelForm):
    money_fields = ("price_from", "price_to")
    unit_types = forms.MultipleChoiceField(
        choices=[(k, v) for k, v in Lead.PROPERTY_TYPES if k != "other"], widget=forms.CheckboxSelectMultiple,
        required=False, label="Unit types available (used to suggest this project to matching leads)",
    )
    maps_link = forms.CharField(
        required=False, label="Google Maps link",
        help_text="Paste the full link from Google Maps to place the pin, or click on the map below.",
        widget=forms.TextInput(attrs={"placeholder": "https://www.google.com/maps/place/...@25.41,51.50,..."}),
    )
    field_order = ["name", "status", "handover", "country", "city", "area", "location", "maps_link",
                   "latitude", "longitude", "unit_types", "property_types"]

    class Meta:
        model = Project
        fields = ["name", "status", "handover", "country", "city", "area", "location", "latitude", "longitude",
                  "property_types", "price_from", "price_to", "cover_image_url", "brochure_url", "is_active"]
        widgets = {
            "city": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "Select or type a city"}),
            "area": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "Select or type an area"}),
            "latitude": forms.NumberInput(attrs={"step": "any", "placeholder": "e.g. 25.413000"}),
            "longitude": forms.NumberInput(attrs={"step": "any", "placeholder": "e.g. 51.509000"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial.setdefault("unit_types", self.instance.unit_type_list)

    def initial_currency(self):
        return currency_for(self.instance.country or DEFAULT_COUNTRY)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("price_from") and cleaned.get("price_to") and cleaned["price_from"] > cleaned["price_to"]:
            self.add_error("price_to", "'Price to' must be higher than 'Price from'.")
        link = (cleaned.get("maps_link") or "").strip()
        if link:
            coords = coords_from_maps_link(link)
            if coords:
                cleaned["latitude"], cleaned["longitude"] = coords
            else:
                self.add_error("maps_link", "No location found in this link. Open it in Google Maps and copy the full "
                                            "address-bar URL (short maps.app.goo.gl links can't be read).")
        if (cleaned.get("latitude") is None) != (cleaned.get("longitude") is None):
            self.add_error("longitude", "Enter both latitude and longitude, or neither.")
        return cleaned

    def save(self, commit=True):
        project = super().save(commit=False)
        project.unit_types = ",".join(self.cleaned_data.get("unit_types") or [])
        if commit:
            project.save()
        return project


FILE_SIGNATURES = {"pdf": (b"%PDF",), "jpg": (b"\xff\xd8\xff",), "jpeg": (b"\xff\xd8\xff",),
                   "png": (b"\x89PNG\r\n\x1a\n",)}


class ProjectDocumentForm(StyledMixin, forms.ModelForm):
    replaces = forms.BooleanField(required=False, initial=True,
                                  label="Replace the current document of this type (old shared links show the new one)")

    class Meta:
        model = ProjectDocument
        fields = ["kind", "title", "file", "url"]
        help_texts = {"file": "PDF, JPG or PNG.", "url": "Or link to a file hosted elsewhere (https)."}

    def clean_file(self):
        upload = self.cleaned_data.get("file")
        if not upload:
            return upload
        if upload.size > settings.DOCUMENT_MAX_MB * 1024 * 1024:
            raise forms.ValidationError(f"File is larger than {settings.DOCUMENT_MAX_MB} MB.")
        ext = upload.name.rsplit(".", 1)[-1].lower()
        head = upload.read(8)
        upload.seek(0)
        if not head.startswith(FILE_SIGNATURES.get(ext, (b"\0invalid",))):
            raise forms.ValidationError("The file content doesn't match its type. Upload a real PDF, JPG or PNG.")
        return upload

    def clean_url(self):
        url = self.cleaned_data.get("url", "")
        if url and not url.lower().startswith(("https://", "http://")):
            raise forms.ValidationError("Use an http(s) link.")
        return url

    def clean(self):
        cleaned = super().clean()
        if bool(cleaned.get("file")) == bool(cleaned.get("url")):
            raise forms.ValidationError("Upload a file or give a link (one of the two).")
        return cleaned


class ShareForm(forms.Form):
    project = forms.ModelChoiceField(queryset=Project.objects.filter(is_active=True))
    documents = forms.ModelMultipleChoiceField(queryset=ProjectDocument.objects.filter(is_active=True), required=False)
    reason = forms.CharField(max_length=200, required=False)

    def clean(self):
        cleaned = super().clean()
        project, docs = cleaned.get("project"), cleaned.get("documents") or []
        if project and any(d.project_id != project.pk for d in docs):
            raise forms.ValidationError("Pick documents of the selected project only.")
        return cleaned


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
    phone_code = forms.ChoiceField(choices=DIAL_CHOICES, initial=DEFAULT_DIAL, widget=forms.Select(attrs={"class": "input"}))
    phone = PhoneField(label="Mobile number", widget=forms.TextInput(attrs={"class": "input", "placeholder": "Mobile number", "inputmode": "tel"}))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={"class": "input", "placeholder": "Email (optional)"}))
    project = forms.ModelChoiceField(queryset=Project.objects.filter(is_active=True), required=False,
                                     empty_label="Any project", widget=forms.Select(attrs={"class": "input"}))
    property_type = forms.ChoiceField(choices=[("", "Property type")] + Lead.PROPERTY_TYPES, required=False,
                                      widget=forms.Select(attrs={"class": "input"}))
    currency = forms.ChoiceField(choices=[(code, code) for code, _l in CURRENCY_CHOICES], initial=BASE_CURRENCY,
                                 widget=forms.Select(attrs={"class": "input"}))
    budget_amount = forms.DecimalField(required=False, min_value=0, max_digits=14, decimal_places=2,
                                       widget=forms.NumberInput(attrs={"class": "input", "placeholder": "Budget (optional)"}))
    message = forms.CharField(required=False, max_length=500,
                              widget=forms.Textarea(attrs={"class": "input", "rows": 3, "placeholder": "Anything we should know?"}))
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))
    consent = forms.BooleanField(label=f"I agree to be contacted by {settings.COMPANY_NAME} by call / WhatsApp.")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("phone") and cleaned.get("phone_code"):
            cleaned["phone"] = strip_dial_code(cleaned["phone"], cleaned["phone_code"])
        cleaned["budget_amount"] = to_base(cleaned.get("budget_amount"), cleaned.get("currency") or BASE_CURRENCY)
        return cleaned
