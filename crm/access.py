from functools import wraps

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from .locale_data import CURRENCY_CHOICES, current_currency
from .models import Lead, Notification, Profile

ADMIN, MANAGER, LEADER, EXECUTIVE = Profile.ADMIN, Profile.MANAGER, Profile.LEADER, Profile.EXECUTIVE
MGMT = (ADMIN, MANAGER)
SALES_ROLES = (ADMIN, MANAGER, LEADER, EXECUTIVE)


def post_only(view):
    """Like require_POST, but a plain visit (e.g. the redirect after re-login) lands on a real page, not a 405."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.method == "POST":
            return view(request, *args, **kwargs)
        if request.path.startswith("/leads/"):
            pk = kwargs.get("pk")
            if pk and Lead.objects.filter(pk=pk).exists():
                return redirect("lead_detail", pk=pk)
            return redirect("lead_list")
        return redirect("home")
    return wrapper


def get_role(user):
    if user is None or not user.is_authenticated:
        return None
    if not hasattr(user, "_crm_role"):
        try:
            user._crm_role = user.profile.role
        except Profile.DoesNotExist:
            user._crm_role = ADMIN if user.is_superuser else None
    return user._crm_role


def team_user_ids(user):
    """Users whose leads a team leader can see: own team members plus himself."""
    ids = set(Profile.objects.filter(team__leader=user).values_list("user_id", flat=True))
    ids.add(user.pk)
    return ids


def visible_leads(user, queryset=None):
    queryset = Lead.objects.all() if queryset is None else queryset
    role = get_role(user)
    if role in MGMT:
        return queryset
    if role == LEADER:
        return queryset.filter(owner_id__in=team_user_ids(user))
    if role == EXECUTIVE:
        return queryset.filter(owner=user)
    return queryset.none()


def visible_users(user):
    """Sales users the current user may see in filters and reports."""
    users = get_user_model().objects.filter(is_active=True, profile__isnull=False).select_related("profile")
    role = get_role(user)
    if role in MGMT:
        return users.order_by("first_name")
    if role == LEADER:
        return users.filter(pk__in=team_user_ids(user)).order_by("first_name")
    return users.filter(pk=user.pk)


def can_view_lead(user, lead):
    return visible_leads(user).filter(pk=lead.pk).exists()


def assignable_users(user):
    """Who the current user may hand a lead to."""
    users = get_user_model().objects.filter(
        is_active=True, profile__role__in=(LEADER, EXECUTIVE, MANAGER)
    ).select_related("profile").order_by("first_name")
    if get_role(user) == LEADER:
        users = users.filter(pk__in=team_user_ids(user))
    return users


def role_required(*roles):
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if get_role(request.user) not in roles:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def access_context(request):
    user = getattr(request, "user", None)
    role = get_role(user)
    ctx = {
        "role": role,
        "role_label": dict(Profile.ROLE_CHOICES).get(role, ""),
        "is_admin": role == ADMIN,
        "is_mgmt": role in MGMT,
        "is_leader": role == LEADER,
        "is_exec": role == EXECUTIVE,
        "can_export": role in MGMT,
        "can_reassign": role in (ADMIN, MANAGER, LEADER),
        "can_delete": role == ADMIN,
    }
    if role:
        ctx["unread_count"] = Notification.objects.filter(user=user, is_read=False).count()
    return ctx


def _asset_version():
    # Changes whenever app.js/app.css change, so browsers never run a stale cached copy.
    root = settings.BASE_DIR / "static"
    try:
        return int(max((root / "js/app.js").stat().st_mtime, (root / "css/app.css").stat().st_mtime))
    except OSError:
        return 0


def brand_context(request):
    return {
        "asset_version": _asset_version(),
        "company": settings.COMPANY_NAME,
        "brand_mark": settings.BRAND_MARK,
        "brand_word": settings.BRAND_WORD,
        "company_tagline": settings.COMPANY_TAGLINE,
        "company_phone": settings.COMPANY_PHONE,
        "company_website": settings.COMPANY_WEBSITE,
        "currency": current_currency.get(),
        "currency_choices": CURRENCY_CHOICES,
    }
