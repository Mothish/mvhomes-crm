from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .. import geo
from ..access import ADMIN, post_only, role_required
from ..forms import ProjectDocumentForm, ProjectForm, TeamForm, TransferForm, UserForm
from ..locale_data import geo_data
from ..models import AuditLog, Lead, Project, ProjectDocument, Team
from ..services import audit, transfer_leads


@role_required(ADMIN)
def users(request):
    people = get_user_model().objects.filter(profile__isnull=False).select_related("profile__team").annotate(
        open_leads=Count("owned_leads", filter=Q(owned_leads__stage__in=Lead.OPEN_STAGES))
    ).order_by("-is_active", "profile__role", "first_name")
    return render(request, "crm/manage/users.html", {
        "people": people, "teams": Team.objects.select_related("leader").annotate(n=Count("members")),
        "team_form": TeamForm(),
    })


def _user_form(request, instance=None):
    form = UserForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        audit(request.user, "update" if instance else "create", user,
              f"{'Updated' if instance else 'Created'} user {user.username} ({user.profile.get_role_display()})")
        messages.success(request, f"User {user.get_full_name()} saved.")
        return redirect("users")
    return render(request, "crm/manage/user_form.html", {"form": form, "person": instance})


@role_required(ADMIN)
def user_create(request):
    return _user_form(request)


@role_required(ADMIN)
def user_edit(request, pk):
    return _user_form(request, get_object_or_404(get_user_model(), pk=pk, profile__isnull=False))


@role_required(ADMIN)
def user_transfer(request, pk):
    person = get_object_or_404(get_user_model(), pk=pk, profile__isnull=False)
    open_count = Lead.objects.filter(owner=person, stage__in=Lead.OPEN_STAGES).count()
    form = TransferForm(request.POST or None, from_user=person)
    if request.method == "POST" and form.is_valid():
        moved = transfer_leads(person, form.cleaned_data["to_user"], request.user)
        if form.cleaned_data["deactivate"]:
            person.is_active = False
            person.save(update_fields=["is_active"])
            person.profile.accepts_leads = False
            person.profile.save(update_fields=["accepts_leads"])
            audit(request.user, "deactivate", person, f"Deactivated {person.username}")
        messages.success(request, f"{moved} open lead(s) transferred from {person.get_full_name()}.")
        return redirect("users")
    return render(request, "crm/manage/transfer.html", {"form": form, "person": person, "open_count": open_count})


@role_required(ADMIN)
@post_only
def team_create(request):
    form = TeamForm(request.POST)
    if form.is_valid():
        team = form.save()
        audit(request.user, "create", team, f"Created team {team.name}")
        messages.success(request, f"Team {team.name} created. Assign members by editing users.")
    else:
        messages.error(request, "Could not create team: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect("users")


@role_required(ADMIN)
def projects(request):
    items = Project.objects.annotate(
        lead_count=Count("leads", distinct=True), booking_count=Count("bookings", distinct=True),
        doc_count=Count("documents", filter=Q(documents__is_active=True), distinct=True),
    )
    return render(request, "crm/manage/projects.html", {"items": items})


def _project_form(request, instance=None):
    form = ProjectForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        project = form.save()
        audit(request.user, "update" if instance else "create", project, f"Saved project {project.name}")
        if instance:
            messages.success(request, f"Project {project.name} saved.")
            return redirect("projects")
        messages.success(request, f"Project {project.name} created. Now upload its brochure and price list below "
                                  "so sales can share them.")
        return redirect(reverse("project_edit", args=[project.pk]) + "#documents")
    return render(request, "crm/manage/project_form.html", {
        "form": form, "project": instance, "geo": geo_data(),
        "documents": instance.documents.select_related("uploaded_by") if instance else [],
        "doc_form": ProjectDocumentForm() if instance else None,
    })


@role_required(ADMIN)
def resolve_maps_link(request):
    try:
        coords = geo.resolve_maps_link(request.GET.get("url", "")[:2000])
    except geo.LinkUnreachable:
        return JsonResponse({"ok": False, "error": "Couldn't open this link from the server. Search the place name instead."})
    if not coords:
        return JsonResponse({"ok": False, "error": "No location found in this link. In Google Maps open the exact place, "
                                                  "tap Share → Copy link and paste it again, or search the place name."})
    return JsonResponse({"ok": True, "lat": float(coords[0]), "lng": float(coords[1])})


@role_required(ADMIN)
@post_only
def project_doc_add(request, pk):
    project = get_object_or_404(Project, pk=pk)
    form = ProjectDocumentForm(request.POST, request.FILES)
    if form.is_valid():
        doc = form.save(commit=False)
        doc.project, doc.uploaded_by = project, request.user
        same_kind = project.documents.filter(kind=doc.kind)
        with transaction.atomic():
            doc.version = (same_kind.aggregate(v=Max("version"))["v"] or 0) + 1
            if form.cleaned_data["replaces"]:
                same_kind.filter(is_active=True).update(is_active=False)
            doc.save()
        audit(request.user, "create", doc, f"Added {doc.get_kind_display()} '{doc.title}' v{doc.version} to {project.name}")
        messages.success(request, f"{doc.title} (v{doc.version}) added. Sales staff can now share it.")
    else:
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return redirect(reverse("project_edit", args=[pk]) + "#documents")


@role_required(ADMIN)
@post_only
def project_doc_toggle(request, pk):
    doc = get_object_or_404(ProjectDocument.objects.select_related("project"), pk=pk)
    doc.is_active = not doc.is_active
    doc.save(update_fields=["is_active"])
    state = "restored" if doc.is_active else "withdrawn"
    audit(request.user, "update", doc, f"{state.capitalize()} '{doc.title}' v{doc.version} of {doc.project.name}")
    messages.success(request, f"{doc.title} v{doc.version} {state}.")
    return redirect(reverse("project_edit", args=[doc.project_id]) + "#documents")


@role_required(ADMIN)
def project_create(request):
    return _project_form(request)


@role_required(ADMIN)
def project_edit(request, pk):
    return _project_form(request, get_object_or_404(Project, pk=pk))


@role_required(ADMIN)
def audit_log(request):
    logs = AuditLog.objects.select_related("user")
    action = request.GET.get("action", "")
    if action:
        logs = logs.filter(action=action)
    actions = AuditLog.objects.values_list("action", flat=True).distinct().order_by("action")
    return render(request, "crm/manage/audit.html", {
        "page": Paginator(logs, 50).get_page(request.GET.get("page")), "actions": actions, "action": action,
    })
