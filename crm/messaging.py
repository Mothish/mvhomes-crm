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
        "ta": "வணக்கம் {name}, {company}-இன் {project} மீது ஆர்வம் காட்டியதற்கு நன்றி! நான் {agent}, உங்கள் "
              "சொத்து ஆலோசகர். ஃப்ளோர் பிளான் மற்றும் விலை விவரங்களை பகிர உங்களுக்கு வசதியான நேரம் எது?",
    },
    "visit_confirm": {
        "label": "Site visit confirmation",
        "en": "Hi {name}, your site visit to {project} is confirmed for {visit_time}. {agent} will meet you at the "
              "site. Location: {location}. See you there!",
        "ta": "வணக்கம் {name}, {project} தள பார்வை {visit_time} அன்று உறுதி செய்யப்பட்டுள்ளது. {agent} உங்களை "
              "தளத்தில் சந்திப்பார். இடம்: {location}. சந்திப்போம்!",
    },
    "followup": {
        "label": "Follow-up",
        "en": "Hi {name}, just checking in about {project}. Prices are being revised soon and a few good units are "
              "still available. Shall I block a time to discuss? - {agent}, {company}",
        "ta": "வணக்கம் {name}, {project} பற்றி நினைவூட்டுகிறேன். விலைகள் விரைவில் மாற உள்ளன, சில நல்ல "
              "யூனிட்கள் இன்னும் உள்ளன. பேச ஒரு நேரத்தை ஒதுக்கட்டுமா? - {agent}, {company}",
    },
    "brochure": {
        "label": "Send brochure",
        "en": "Hi {name}, here is the brochure for {project} ({location}): {brochure}. Happy to answer any "
              "questions. - {agent}, {company}",
        "ta": "வணக்கம் {name}, {project} ({location}) பிரோஷர் இதோ: {brochure}. ஏதேனும் சந்தேகம் இருந்தால் "
              "கேளுங்கள். - {agent}, {company}",
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
        "project": project.name if project else ("எங்கள் திட்டங்கள்" if lang == "ta" else "our projects"),
        "location": project.location if project else "",
        "brochure": project.brochure_url if project and project.brochure_url else f"{settings.COMPANY_WEBSITE}/brochure",
        "agent": (owner.get_full_name() or owner.username) if owner else COMPANY,
        "visit_time": timezone.localtime(visit.scheduled_at).strftime(
            "%d-%m-%Y, %I:%M %p" if lang == "ta" else "%a %d %b, %I:%M %p"
        ) if visit else "",
    }
    return TEMPLATES[key][lang].format_map(_Safe(values))


def lead_previews(lead):
    return [
        {"key": k, "label": t["label"], "en": render_message(lead, k, "en"), "ta": render_message(lead, k, "ta")}
        for k, t in TEMPLATES.items()
    ]


@role_required(*SALES_ROLES)
def whatsapp(request, pk, key):
    from .views.leads import get_visible_lead
    from .services import log_activity

    if key not in TEMPLATES:
        raise Http404
    lead = get_visible_lead(request, pk)
    lang = request.GET.get("lang") or lead.language
    lang = lang if lang in ("en", "ta") else "en"
    text = render_message(lead, key, lang, agent=request.user)
    log_activity(lead, "whatsapp", request.user, note=f"WhatsApp sent: {TEMPLATES[key]['label']} ({lang.upper()})")
    return redirect(f"https://wa.me/{wa_number(lead.phone)}?text={quote(text)}")
