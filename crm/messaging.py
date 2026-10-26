from urllib.parse import quote

from django.conf import settings
from django.http import Http404
from django.shortcuts import redirect
from django.utils import timezone

from .access import SALES_ROLES, role_required
from .templatetags.crm_tags import wa_number

COMPANY = settings.COMPANY_NAME

TEMPLATES = {
    "first_response": {
        "label": "First response",
        "en": "Hi {name}, thank you for your interest in {project} by {company}! I'm {agent}, your property advisor. "
              "When is a good time to share the floor plans and pricing with you?",
        "ar": "مرحباً {name}، شكراً لاهتمامك بمشروع {project} من {company}! أنا {agent}، مستشارك العقاري. "
              "متى يناسبك أن أشاركك المخططات والأسعار؟",
    },
    "visit_confirm": {
        "label": "Site visit confirmation",
        "en": "Hi {name}, your site visit to {project} is confirmed for {visit_time}. {agent} will meet you at the "
              "site. Location: {location}. See you there!",
        "ar": "مرحباً {name}، تم تأكيد زيارتك لمشروع {project} بتاريخ {visit_time}. سيقابلك {agent} في "
              "الموقع. العنوان: {location}. بانتظارك!",
    },
    "followup": {
        "label": "Follow-up",
        "en": "Hi {name}, just checking in about {project}. Prices are being revised soon and a few good units are "
              "still available. Shall I block a time to discuss? - {agent}, {company}",
        "ar": "مرحباً {name}، أود المتابعة بخصوص مشروع {project}. سيتم تحديث الأسعار قريباً ولا تزال "
              "هناك وحدات مميزة متاحة. هل أحجز لك موعداً للنقاش؟ - {agent}، {company}",
    },
    "brochure": {
        "label": "Send brochure",
        "en": "Hi {name}, here is the brochure for {project} ({location}): {brochure}. Happy to answer any "
              "questions. - {agent}, {company}",
        "ar": "مرحباً {name}، إليك كتيب مشروع {project} ({location}): {brochure}. يسعدني الإجابة "
              "على أي استفسار. - {agent}، {company}",
    },
}


class _Safe(dict):
    def __missing__(self, key):
        return ""


def render_message(lead, key, lang, agent=None):
    project = lead.project
    visit = lead.site_visits.filter(status="scheduled").order_by("scheduled_at").first()
    owner = agent or lead.owner
    values = {
        "company": COMPANY,
        "name": lead.name.split()[0],
        "project": lead.project_label or ("مشاريعنا" if lang == "ar" else "our projects"),
        "location": project.location if project else "",
        "brochure": project.brochure_url if project and project.brochure_url else f"{settings.COMPANY_WEBSITE}/brochure",
        "agent": (owner.get_full_name() or owner.username) if owner else COMPANY,
        "visit_time": timezone.localtime(visit.scheduled_at).strftime(
            "%d-%m-%Y, %I:%M %p" if lang == "ar" else "%a %d %b, %I:%M %p"
        ) if visit else "",
    }
    return TEMPLATES[key][lang].format_map(_Safe(values))


def lead_previews(lead):
    return [
        {"key": k, "label": t["label"], "en": render_message(lead, k, "en")}
        for k, t in TEMPLATES.items()
    ]


@role_required(*SALES_ROLES)
def whatsapp(request, pk, key):
    from .models import Lead
    from .views.leads import get_visible_lead
    from .services import log_activity

    if key not in TEMPLATES:
        raise Http404
    lead = get_visible_lead(request, pk)
    lang = request.GET.get("lang") or lead.language
    lang = lang if lang in dict(Lead.LANGUAGES) else "en"
    text = render_message(lead, key, lang, agent=request.user)
    log_activity(lead, "whatsapp", request.user, note=f"WhatsApp sent: {TEMPLATES[key]['label']} ({lang.upper()})")
    return redirect(f"https://wa.me/{wa_number(lead.tel)}?text={quote(text)}")
