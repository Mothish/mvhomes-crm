from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt

from ..access import MGMT, role_required
from ..forms import EnquiryForm
from ..locale_data import country_for_dial
from ..models import Lead, Project
from ..services import capture_lead

RATE_LIMIT = 5  # submissions per IP per hour


def _client_ip(request):
    return request.META.get("REMOTE_ADDR", "unknown")


def _process(request, channel):
    """Validate and capture a public enquiry. Returns (form, error, submitted)."""
    form = EnquiryForm(request.POST or None, initial={"project": request.GET.get("project")})
    if request.method != "POST":
        return form, None, False
    key = f"enquiry-rate:{_client_ip(request)}"
    attempts = cache.get(key, 0)
    if attempts >= RATE_LIMIT:
        return form, "Too many enquiries from this device. Please call us instead.", False
    if not form.is_valid():
        return form, None, False
    cache.set(key, attempts + 1, 3600)
    d = form.cleaned_data
    if not d["website"]:  # honeypot filled in: silently drop bot submissions
        capture_lead(
            {
                "name": d["name"], "phone_code": d["phone_code"], "phone": d["phone"], "email": d["email"],
                "country": country_for_dial(d["phone_code"]), "project": d["project"],
                "property_type": d["property_type"], "budget_amount": d["budget_amount"], "source": "website",
                "notes": d["message"], "temperature": Lead.WARM,
            },
            channel=channel,
        )
    return form, None, True


def _company():
    return {"company": settings.COMPANY_NAME, "company_phone": settings.COMPANY_PHONE}


def enquire(request):
    form, error, submitted = _process(request, "Website enquiry page")
    if submitted:
        return redirect("enquiry_thanks")
    return render(request, "crm/public/enquire.html", {
        "form": form, "error": error, "projects": Project.objects.filter(is_active=True), **_company(),
    })


# Embedded on third-party pages, where the CSRF cookie is never sent; protected by honeypot + rate limit instead.
@csrf_exempt
@xframe_options_exempt
def enquire_widget(request):
    form, error, submitted = _process(request, "Website widget")
    return render(request, "crm/public/widget.html", {
        "form": form, "error": error, "submitted": submitted, **_company(),
    })


def enquiry_thanks(request):
    return render(request, "crm/public/thanks.html", _company())


@role_required(*MGMT)
def website_form(request):
    now = timezone.now()
    today = timezone.localdate()
    web = Lead.objects.filter(source="website")
    stats = web.aggregate(
        today=Count("id", filter=Q(created_at__date=today)),
        week=Count("id", filter=Q(created_at__gte=now - timedelta(days=7))),
        month=Count("id", filter=Q(created_at__gte=now - timedelta(days=30))),
        month_booked=Count("id", filter=Q(created_at__gte=now - timedelta(days=30), stage=Lead.BOOKED)),
        month_contacted=Count("id", filter=Q(created_at__gte=now - timedelta(days=30), first_response_at__isnull=False)),
    )
    widget_url = request.build_absolute_uri(reverse("enquire_widget"))
    return render(request, "crm/website_form.html", {
        "stats": stats,
        "recent": web.select_related("owner", "project").order_by("-created_at")[:10],
        "page_url": request.build_absolute_uri(reverse("enquire")),
        "widget_url": widget_url,
        "embed_code": f'<iframe src="{widget_url}" title="{settings.COMPANY_NAME} enquiry" '
                      'style="width:100%;max-width:420px;height:660px;border:0;border-radius:16px"></iframe>',
    })
