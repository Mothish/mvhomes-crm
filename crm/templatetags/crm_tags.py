from decimal import Decimal, InvalidOperation

from django import template

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


def _decimal(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None


@register.filter
def inr(value):
    """Indian grouping: 1234567 -> ₹12,34,567"""
    amount = _decimal(value)
    if amount is None:
        return ""
    sign = "-" if amount < 0 else ""
    whole = f"{abs(amount):.0f}"
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}₹{whole}"


@register.filter
def crore(value):
    """Compact real-estate format: 8500000 -> ₹85 L, 12500000 -> ₹1.25 Cr"""
    amount = _decimal(value)
    if amount is None:
        return "₹0"
    if abs(amount) >= 10_000_000:
        return f"₹{amount / 10_000_000:.2f} Cr".replace(".00 ", " ")
    if abs(amount) >= 100_000:
        return f"₹{amount / 100_000:.1f} L".replace(".0 ", " ")
    return inr(amount)


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
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    return f"91{digits}" if len(digits) == 10 else digits


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
