from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..access import ADMIN, role_required
from ..forms import ProjectForm, TeamForm, TransferForm, UserForm
from ..models import AuditLog, Lead, Project, Team
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
@require_POST
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
        lead_count=Count("leads", distinct=True), booking_count=Count("bookings", distinct=True)
    )
    return render(request, "crm/manage/projects.html", {"items": items})


def _project_form(request, instance=None):
    form = ProjectForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        project = form.save()
        audit(request.user, "update" if instance else "create", project, f"Saved project {project.name}")
        messages.success(request, f"Project {project.name} saved.")
        return redirect("projects")
    return render(request, "crm/manage/project_form.html", {"form": form, "project": instance})


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
