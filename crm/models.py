from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

phone_validator = RegexValidator(r"^\d{10,15}$", "Enter a valid phone number (10-15 digits).")


def normalize_phone(value):
    """Canonical form used for duplicate detection: +91 98400 12345 / 098400 12345 -> 9840012345."""
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits


def month_start(d):
    return d.replace(day=1)


class Team(models.Model):
    name = models.CharField(max_length=60, unique=True)
    leader = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="led_teams"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Project(models.Model):
    name = models.CharField(max_length=100, unique=True)
    location = models.CharField(max_length=120)
    property_types = models.CharField(max_length=100, help_text="e.g. 2 BHK, 3 BHK, Villa")
    price_from = models.DecimalField("Price from (₹ lakh)", max_digits=8, decimal_places=2)
    price_to = models.DecimalField("Price to (₹ lakh)", max_digits=8, decimal_places=2)
    brochure_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Profile(models.Model):
    ADMIN, MANAGER, LEADER, EXECUTIVE = "admin", "manager", "leader", "executive"
    ROLE_CHOICES = [
        (ADMIN, "Admin"),
        (MANAGER, "Sales Manager"),
        (LEADER, "Team Leader"),
        (EXECUTIVE, "Sales Executive"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=EXECUTIVE)
    team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL, related_name="members")
    phone = models.CharField(max_length=15, blank=True)
    accepts_leads = models.BooleanField("Include in auto-assignment", default=True)
    projects = models.ManyToManyField(
        Project, blank=True, related_name="executives", help_text="Leave empty to receive leads for any project."
    )
    last_assigned_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user} ({self.get_role_display()})"


class Lead(models.Model):
    NEW, CONTACTED, INTERESTED = "new", "contacted", "interested"
    SV_SCHEDULED, SV_DONE, NEGOTIATION = "sv_scheduled", "sv_done", "negotiation"
    BOOKED, LOST = "booked", "lost"
    STAGES = [
        (NEW, "New"),
        (CONTACTED, "Contacted"),
        (INTERESTED, "Interested"),
        (SV_SCHEDULED, "Site Visit Scheduled"),
        (SV_DONE, "Site Visit Done"),
        (NEGOTIATION, "Negotiation"),
        (BOOKED, "Booked"),
        (LOST, "Lost"),
    ]
    STAGE_RANK = {NEW: 0, CONTACTED: 1, INTERESTED: 2, SV_SCHEDULED: 3, SV_DONE: 4, NEGOTIATION: 5, BOOKED: 6, LOST: -1}
    OPEN_STAGES = (NEW, CONTACTED, INTERESTED, SV_SCHEDULED, SV_DONE, NEGOTIATION)

    SOURCES = [
        ("facebook", "Facebook Ads"),
        ("google", "Google Ads"),
        ("website", "Website"),
        ("99acres", "99acres"),
        ("magicbricks", "MagicBricks"),
        ("walk_in", "Walk-in"),
        ("referral", "Referral"),
        ("channel_partner", "Channel Partner"),
        ("print", "Hoarding / Newspaper"),
        ("other", "Other"),
    ]
    PROPERTY_TYPES = [("2bhk", "2 BHK"), ("3bhk", "3 BHK"), ("4bhk", "4 BHK"), ("villa", "Villa"), ("plot", "Plot")]
    BUDGETS = [
        ("lt50", "Below ₹50 L"),
        ("50_75", "₹50 - 75 L"),
        ("75_100", "₹75 L - 1 Cr"),
        ("100_150", "₹1 - 1.5 Cr"),
        ("gt150", "Above ₹1.5 Cr"),
    ]
    HOT, WARM, COLD = "hot", "warm", "cold"
    TEMPERATURES = [(HOT, "Hot"), (WARM, "Warm"), (COLD, "Cold")]
    LOST_REASONS = [
        ("budget", "Budget issue"),
        ("location", "Location"),
        ("bought_elsewhere", "Bought elsewhere"),
        ("not_reachable", "Not reachable"),
        ("not_interested", "Not interested"),
        ("loan_rejected", "Loan rejected"),
        ("other", "Other"),
    ]
    LANGUAGES = [("en", "English"), ("ta", "Tamil")]

    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=15, unique=True, validators=[phone_validator])
    alt_phone = models.CharField("Alternate phone", max_length=15, blank=True, validators=[phone_validator])
    email = models.EmailField(blank=True)
    area = models.CharField("City / area", max_length=100, blank=True)
    budget = models.CharField(max_length=10, choices=BUDGETS, blank=True)
    property_type = models.CharField(max_length=10, choices=PROPERTY_TYPES, blank=True)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, related_name="leads")
    source = models.CharField(max_length=20, choices=SOURCES)
    stage = models.CharField(max_length=15, choices=STAGES, default=NEW)
    max_stage_rank = models.PositiveSmallIntegerField(default=0)
    stage_changed_at = models.DateTimeField(default=timezone.now)
    temperature = models.CharField(max_length=5, choices=TEMPERATURES, default=WARM)
    lost_reason = models.CharField(max_length=20, choices=LOST_REASONS, blank=True)
    lost_note = models.CharField(max_length=200, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="owned_leads"
    )
    language = models.CharField("WhatsApp language", max_length=2, choices=LANGUAGES, default="en")
    notes = models.TextField(blank=True)
    next_followup = models.DateTimeField("Next follow-up", null=True, blank=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    enquiry_count = models.PositiveSmallIntegerField(default=1)
    last_enquiry_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["stage"]), models.Index(fields=["next_followup"])]

    def __str__(self):
        return self.name

    @property
    def is_open(self):
        return self.stage in self.OPEN_STAGES

    @property
    def is_overdue(self):
        return self.is_open and self.next_followup is not None and self.next_followup < timezone.now()

    @property
    def response_minutes(self):
        if not self.first_response_at:
            return None
        return int((self.first_response_at - self.created_at).total_seconds() // 60)


class Activity(models.Model):
    KINDS = [
        ("call", "Call"),
        ("whatsapp", "WhatsApp"),
        ("meeting", "Meeting"),
        ("site_visit", "Site visit"),
        ("email", "Email"),
        ("note", "Note"),
        ("system", "System"),
    ]
    RESPONSE_KINDS = ("call", "whatsapp", "meeting", "email")
    OUTCOMES = [
        ("connected", "Connected"),
        ("no_answer", "No answer"),
        ("busy", "Busy - call back"),
        ("switched_off", "Switched off"),
        ("interested", "Interested"),
        ("not_interested", "Not interested"),
    ]

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="activities")
    kind = models.CharField(max_length=12, choices=KINDS)
    outcome = models.CharField(max_length=15, choices=OUTCOMES, blank=True)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "activities"


class Assignment(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="assignments")
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    to_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reason = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]


class SiteVisit(models.Model):
    SCHEDULED, DONE, NO_SHOW, CANCELLED = "scheduled", "done", "no_show", "cancelled"
    STATUSES = [(SCHEDULED, "Scheduled"), (DONE, "Done"), (NO_SHOW, "No-show"), (CANCELLED, "Cancelled")]

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="site_visits")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="site_visits")
    scheduled_at = models.DateTimeField()
    executive = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="site_visits",
        verbose_name="Accompanied by",
    )
    status = models.CharField(max_length=10, choices=STATUSES, default=SCHEDULED)
    feedback = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["scheduled_at"]


class Booking(models.Model):
    lead = models.OneToOneField(Lead, on_delete=models.CASCADE, related_name="booking")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="bookings")
    unit_no = models.CharField("Unit number", max_length=30)
    deal_value = models.DecimalField("Deal value (₹)", max_digits=12, decimal_places=2, validators=[MinValueValidator(1)])
    booking_amount = models.DecimalField(
        "Booking amount (₹)", max_digits=12, decimal_places=2, validators=[MinValueValidator(1)]
    )
    booking_date = models.DateField(default=timezone.localdate)
    executive = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="bookings")
    notes = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-booking_date", "-id"]


class AdSpend(models.Model):
    month = models.DateField()
    source = models.CharField(max_length=20, choices=Lead.SOURCES)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        unique_together = [("month", "source")]


class Target(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="targets")
    month = models.DateField()
    site_visits = models.PositiveIntegerField(default=0)
    bookings = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("user", "month")]


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    text = models.CharField(max_length=200)
    url = models.CharField(max_length=200, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]


class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=30)
    object_type = models.CharField(max_length=30)
    object_id = models.CharField(max_length=20, blank=True)
    summary = models.CharField(max_length=300)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]
