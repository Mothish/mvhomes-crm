from django import template

from ..locale_data import format_money, format_money_short

register = template.Library()

STAGE_COLORS = {
    "new": "blue",
    "contacted": "sky",
    "interested": "purple",
    "sv_scheduled": "amber",
    "sv_done": "orange",
    "negotiation": "pink",
    "booked": "green",
    "lost": "gray",
}
TEMP_COLORS = {"hot": "red", "warm": "amber", "cold": "sky"}


@register.filter
def money(value):
    """Base-currency amount shown in the user's chosen currency, e.g. QAR 1,250,000."""
    return format_money(value)


@register.filter
def money_short(value):
    """Compact form for KPIs and cards, e.g. QAR 1.25M / $343K / ₹2.86 Cr."""
    return format_money_short(value)


@register.filter
def stage_color(stage):
    return STAGE_COLORS.get(stage, "gray")


@register.filter
def temp_color(temp):
    return TEMP_COLORS.get(temp, "gray")


@register.filter
def person(user, fallback="Unassigned"):
    if not user:
        return fallback
    return user.get_full_name() or user.username


@register.filter
def first_word(text):
    return (text or "").split(" ")[0]


@register.filter
def initials(user):
    if not user:
        return "?"
    name = user.get_full_name() or user.username
    return "".join(p[0] for p in name.split()[:2]).upper()


@register.filter
def minutes(value):
    """Human readable duration from minutes."""
    if value is None or value == "":
        return "—"
    value = int(value)
    if value < 60:
        return f"{value} min"
    if value < 60 * 24:
        return f"{value // 60}h {value % 60}m"
    return f"{value // (60 * 24)}d {(value % (60 * 24)) // 60}h"


@register.filter
def wa_number(phone):
    """wa.me needs the full international number as digits only, e.g. '+974 5512 3456' -> '97455123456'."""
    return "".join(ch for ch in str(phone or "") if ch.isdigit())


@register.filter
def pct(part, whole):
    try:
        return round(float(part) * 100 / float(whole)) if float(whole) else 0
    except (TypeError, ValueError):
        return 0


@register.simple_tag(takes_context=True)
def url_with(context, **kwargs):
    params = context["request"].GET.copy()
    for key, value in kwargs.items():
        params[key] = value
    return params.urlencode()
