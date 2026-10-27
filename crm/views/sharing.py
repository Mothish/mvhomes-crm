"""Tracked project sharing (staff side + public client page) and the projects map."""
import mimetypes
from urllib.parse import quote

from django.contrib import messages
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from ..access import (
    ADMIN, LEADER, MANAGER, MGMT, SALES_ROLES, can_view_lead, get_role, post_only, role_required, visible_leads,
)
from ..forms import ShareForm
from ..locale_data import city_center, format_money_short
from ..matching import suggest_projects
from ..models import Lead, LinkOpen, Profile, Project, ProjectDocument, ShareLink
from ..services import lead_url, log_activity, notify
from ..templatetags.crm_tags import wa_number
from .leads import get_visible_lead

TIER_COLORS = {"area": "#16a34a", "city": "#2563eb", "nearby": "#d97706", "country": "#64748b", "any": "#2563eb"}


def project_pin(project, color="#1f3a68", **extra):
    return {
        "lat": float(project.latitude), "lng": float(project.longitude), "title": project.name,
        "lines": [project.place, f"{format_money_short(project.price_from)} – {format_money_short(project.price_to)}",
                  project.get_status_display() + (f" · handover {project.handover}" if project.handover else "")],
        "color": color, **extra,
    }


def lead_map_data(lead, suggestions):
    center = city_center(lead.country, lead.city)
    pins = [project_pin(s["project"], TIER_COLORS.get(s["tier"], "#64748b"), tag=s["tier_label"])
            for s in suggestions if s["project"].has_coordinates]
    if not pins:
        return None
    return {"center": list(center) if center else None, "centerLabel": f"Client's area: {lead.city}", "pins": pins}


def _managers_for(user):
    """Who hears about an off-suggestion share: the sender's team leader plus admins and managers."""
    ids = set(Profile.objects.filter(role__in=MGMT, user__is_active=True).values_list("user_id", flat=True))
    leader_id = Profile.objects.filter(user=user).values_list("team__leader_id", flat=True).first()
    if leader_id:
        ids.add(leader_id)
    ids.discard(user.pk)
    return Profile.objects.filter(user_id__in=ids).select_related("user")


@role_required(*SALES_ROLES)
@post_only
def lead_share(request, pk):
    lead = get_visible_lead(request, pk)
    form = ShareForm(request.POST)
    if not form.is_valid():
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
        return redirect(lead_url(lead))
    project, docs = form.cleaned_data["project"], list(form.cleaned_data["documents"])
    reason = form.cleaned_data["reason"].strip()
    off = project.pk not in {s["project"].pk for s in suggest_projects(lead, limit=None)}
    if off and not reason:
        messages.error(request, f"{project.name} doesn't match this client's requirement. Add a reason to share it.")
        return redirect(lead_url(lead))

    link = ShareLink.objects.create(lead=lead, project=project, sent_by=request.user, off_suggestion=off,
                                    reason=reason if off else "")
    link.documents.set(docs)
    page = request.build_absolute_uri(reverse("share_page", args=[link.token]))
    agent = request.user.get_full_name() or request.user.username
    text = f"Hi {lead.name.split()[0]}, here are the details of {project.name} as discussed: {page}\n- {agent}, MV Homes"
    what = ", ".join(d.title for d in docs) or "project page"
    note = f"Shared {project.name} ({what}) via tracked link"
    if off:
        note += f". Outside suggestions: {reason}"
        for profile in _managers_for(request.user):
            notify(profile.user, f"⚠ {agent} shared {project.name} with {lead.name} (outside suggestions): {reason}",
                   lead_url(lead))
    log_activity(lead, "whatsapp", request.user, note=note)
    return redirect(f"https://wa.me/{wa_number(lead.tel)}?text={quote(text)}")


@role_required(*SALES_ROLES)
@post_only
def share_revoke(request, pk):
    link = get_object_or_404(ShareLink.objects.select_related("lead"), pk=pk)
    role = get_role(request.user)
    allowed = can_view_lead(request.user, link.lead) and (
        role in (ADMIN, MANAGER, LEADER) or link.sent_by_id == request.user.pk)
    if not allowed:
        raise Http404
    if not link.is_revoked:
        link.revoked_at, link.revoked_by = timezone.now(), request.user
        link.save(update_fields=["revoked_at", "revoked_by"])
        log_activity(link.lead, "system", request.user, note=f"Disabled the shared link for {link.project.name}")
        messages.success(request, "Link disabled. The client now sees that it is no longer valid.")
    return redirect(lead_url(link.lead))


@role_required(ADMIN, MANAGER, LEADER)
def share_report(request):
    links = (ShareLink.objects.filter(lead__in=visible_leads(request.user))
             .select_related("lead", "project", "sent_by").prefetch_related("documents"))
    show = request.GET.get("show", "")
    if show == "flagged":
        links = links.filter(off_suggestion=True)
    elif show == "unopened":
        links = links.filter(open_count=0, revoked_at__isnull=True)
    elif show == "interested":
        links = links.exclude(interest="")
    stats = ShareLink.objects.filter(lead__in=visible_leads(request.user)).aggregate(
        total=Count("id"), opened=Count("id", filter=Q(open_count__gt=0)),
        flagged=Count("id", filter=Q(off_suggestion=True)), interested=Count("id", filter=~Q(interest="")))
    return render(request, "crm/share_report.html", {"links": links[:300], "show": show, "stats": stats})


@role_required(*SALES_ROLES)
def projects_map(request):
    projects = Project.objects.filter(is_active=True)
    pins = [project_pin(p, url=reverse("project_edit", args=[p.pk]) if get_role(request.user) == ADMIN else "")
            for p in projects if p.has_coordinates]
    demand = []
    counts = (visible_leads(request.user).filter(stage__in=Lead.OPEN_STAGES).exclude(city="")
              .values("country", "city").annotate(n=Count("id")))
    for row in counts:
        center = city_center(row["country"], row["city"])
        if center:
            demand.append({"lat": center[0], "lng": center[1], "count": row["n"], "label": row["city"]})
    return render(request, "crm/projects_map.html", {
        "map_data": {"pins": pins, "demand": demand},
        "missing": [p for p in projects if not p.has_coordinates],
    })


# ---------------------------------------------------------------- public client page (no login, token only)

def _device(request):
    agent = request.META.get("HTTP_USER_AGENT", "")
    for key, label in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"),
                       ("Macintosh", "Mac"), ("Linux", "Linux")):
        if key in agent:
            return label
    return "Other"


def _record_open(request, link, document=None):
    now = timezone.now()
    LinkOpen.objects.create(link=link, document=document, device=_device(request))
    first = link.first_opened_at is None
    link.open_count += 1
    link.last_opened_at = now
    link.first_opened_at = link.first_opened_at or now
    link.save(update_fields=["open_count", "first_opened_at", "last_opened_at"])
    if first and link.sent_by:
        notify(link.sent_by, f"👁 {link.lead.name} opened {link.project.name}", lead_url(link.lead))


def _live_link(token):
    link = ShareLink.objects.select_related("lead", "project", "sent_by").filter(token=token).first()
    if link is None:
        raise Http404
    return link


def _private(response):
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Cache-Control"] = "private, no-store"
    return response


def share_page(request, token):
    link = _live_link(token)
    if link.is_revoked:
        return _private(render(request, "crm/public/share_revoked.html", {"link": link}, status=410))
    if request.method == "GET":
        _record_open(request, link)
    docs = []
    for doc in link.documents.all():
        current = doc.current()
        docs.append({"original": doc, "current": current, "updated": current is not None and current.pk != doc.pk})
    project = link.project
    return _private(render(request, "crm/public/share_page.html", {
        "link": link, "project": project, "docs": docs, "thanks": request.GET.get("thanks"),
        "agent": link.sent_by.get_full_name() if link.sent_by else "MV Homes",
        "map_data": {"pins": [project_pin(project)], "center": None} if project.has_coordinates else None,
    }))


def share_doc(request, token, doc_id):
    link = _live_link(token)
    if link.is_revoked:
        return redirect("share_page", token=token)
    original = get_object_or_404(link.documents, pk=doc_id)
    doc = original.current()
    if doc is None:
        raise Http404
    _record_open(request, link, doc)
    if doc.url:
        return redirect(doc.url)
    return _private(_file_response(doc))


@post_only
def share_interest(request, token):
    link = _live_link(token)
    if link.is_revoked:
        return redirect("share_page", token=token)
    choice = request.POST.get("interest")
    if choice in dict(ShareLink.INTEREST) and link.interest != "visit":
        link.interest, link.interest_at = choice, timezone.now()
        link.save(update_fields=["interest", "interest_at"])
        label = dict(ShareLink.INTEREST)[choice]
        log_activity(link.lead, "system", None, note=f"Client tapped “{label}” on the shared {link.project.name} page")
        for user in {u for u in (link.lead.owner, link.sent_by) if u}:
            notify(user, f"🔥 {link.lead.name}: {label.lower()} – {link.project.name}", lead_url(link.lead))
    return redirect(reverse("share_page", args=[token]) + "?thanks=1")


def _file_response(doc):
    content_type = mimetypes.guess_type(doc.file.name)[0] or "application/octet-stream"
    ext = doc.file.name.rsplit(".", 1)[-1]
    return FileResponse(doc.file.open("rb"), content_type=content_type,
                        filename=f"{doc.project.name} - {doc.title}.{ext}")


@role_required(ADMIN, MANAGER)
def project_doc_open(request, pk):
    doc = get_object_or_404(ProjectDocument.objects.select_related("project"), pk=pk)
    if doc.url:
        return redirect(doc.url)
    if not doc.file:
        raise Http404
    return _private(_file_response(doc))


def lead_share_context(lead):
    """Context for the suggestions + shares panels on the lead page."""
    suggestions = suggest_projects(lead) if lead.is_open else []
    suggested_ids = {s["project"].pk for s in suggest_projects(lead, limit=None)} if lead.is_open else set()
    projects = list(Project.objects.filter(is_active=True).prefetch_related("documents"))
    docs = {p.pk: [d for d in p.documents.all() if d.is_active] for p in projects}
    for s in suggestions:
        s["docs"] = docs.get(s["project"].pk, [])
    return {
        "suggestions": suggestions,
        "share_projects": [{"project": p, "docs": docs[p.pk], "suggested": p.pk in suggested_ids} for p in projects],
        "shares": lead.shares.select_related("project", "sent_by").prefetch_related("documents"),
        "suggest_map": lead_map_data(lead, suggestions) if suggestions else None,
    }
