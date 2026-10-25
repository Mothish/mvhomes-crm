from datetime import datetime, timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..access import ADMIN, SALES_ROLES, can_view_lead, role_required, visible_leads
from ..forms import BookingForm, SiteVisitForm, VisitResultForm
from ..models import Booking, Lead, Notification, Project, SiteVisit
from ..services import audit, log_activity, notify, set_stage
from .leads import get_visible_lead


@role_required(*SALES_ROLES)
def my_day(request):
    now = timezone.now()
    today = timezone.localdate()
    mine = Lead.objects.filter(owner=request.user, stage__in=Lead.OPEN_STAGES).select_related("project")
    overdue = list(mine.filter(next_followup__lt=now).order_by("next_followup"))
    due_today = list(mine.filter(next_followup__gte=now, next_followup__date=today).order_by("next_followup"))
    untouched = list(mine.filter(first_response_at__isnull=True).order_by("created_at"))
    visits = SiteVisit.objects.filter(
        executive=request.user, status=SiteVisit.SCHEDULED, scheduled_at__date__lte=today + timedelta(days=1)
    ).select_related("lead", "project").order_by("scheduled_at")
    hot = mine.filter(temperature=Lead.HOT).exclude(pk__in=[lead.pk for lead in overdue + due_today])[:8]
    return render(
        request,
        "crm/my_day.html",
        {"overdue": overdue, "due_today": due_today, "untouched": untouched, "visits": visits, "hot": hot,
         "now": now, "today": today},
    )


@role_required(*SALES_ROLES)
def visit_schedule(request, pk):
    lead = get_visible_lead(request, pk)
    if not lead.is_open:
        messages.error(request, "Site visits can only be scheduled for open leads.")
        return redirect("lead_detail", pk=pk)
    form = SiteVisitForm(
        request.POST or None, user=request.user,
        initial={"project": lead.project_id, "executive": lead.owner_id or request.user.pk},
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            visit = form.save(commit=False)
            visit.lead, visit.created_by = lead, request.user
            visit.save()
            if Lead.STAGE_RANK[lead.stage] < Lead.STAGE_RANK[Lead.SV_SCHEDULED]:
                set_stage(lead, Lead.SV_SCHEDULED, request.user)
            lead.next_followup = visit.scheduled_at - timedelta(hours=3)
            lead.save(update_fields=["next_followup", "updated_at"])
            when = timezone.localtime(visit.scheduled_at)
            log_activity(lead, "note", request.user, note=f"Site visit scheduled: {visit.project} on {when:%a %d %b, %I:%M %p}")
            if visit.executive and visit.executive != request.user:
                notify(visit.executive, f"Site visit with {lead.name} on {when:%d %b %I:%M %p}", f"/leads/{lead.pk}/")
        messages.success(request, "Site visit scheduled. Send the confirmation on WhatsApp from the lead page.")
        return redirect("lead_detail", pk=pk)
    return render(request, "crm/visits/form.html", {"form": form, "lead": lead})


@role_required(*SALES_ROLES)
def visit_update(request, pk):
    visit = get_object_or_404(SiteVisit.objects.select_related("lead", "project"), pk=pk)
    if not can_view_lead(request.user, visit.lead) and visit.executive != request.user:
        raise PermissionDenied
    form = VisitResultForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        lead = visit.lead
        with transaction.atomic():
            visit.status = form.cleaned_data["status"]
            visit.feedback = form.cleaned_data["feedback"]
            visit.completed_at = timezone.now()
            visit.save()
            log_activity(lead, "site_visit", request.user,
                         note=f"Site visit {visit.get_status_display().lower()} at {visit.project}. {visit.feedback}".strip())
            if visit.status == SiteVisit.DONE and lead.is_open and Lead.STAGE_RANK[lead.stage] < Lead.STAGE_RANK[Lead.SV_DONE]:
                set_stage(lead, Lead.SV_DONE, request.user)
            elif visit.status != SiteVisit.DONE and lead.stage == Lead.SV_SCHEDULED:
                set_stage(lead, Lead.INTERESTED, request.user)
        messages.success(request, f"Site visit marked {visit.get_status_display().lower()}.")
        return redirect("lead_detail", pk=lead.pk)
    return render(request, "crm/visits/update.html", {"form": form, "visit": visit})


@role_required(*SALES_ROLES)
def visit_calendar(request):
    today = timezone.localdate()
    try:
        start = datetime.strptime(request.GET.get("week", ""), "%Y-%m-%d").date()
    except ValueError:
        start = today
    start -= timedelta(days=start.weekday())
    end = start + timedelta(days=6)
    visits = SiteVisit.objects.filter(
        lead__in=visible_leads(request.user), scheduled_at__date__range=(start, end)
    ).select_related("lead", "project", "executive").order_by("scheduled_at")
    days = [{"date": start + timedelta(days=i), "visits": []} for i in range(7)]
    for v in visits:
        days[(timezone.localtime(v.scheduled_at).date() - start).days]["visits"].append(v)
    return render(
        request,
        "crm/visits/calendar.html",
        {"days": days, "start": start, "end": end, "today": today, "total": len(visits),
         "prev": start - timedelta(days=7), "next": start + timedelta(days=7)},
    )


@role_required(*SALES_ROLES)
def booking_create(request, pk):
    lead = get_visible_lead(request, pk)
    if lead.stage == Lead.BOOKED:
        messages.info(request, "This lead is already booked.")
        return redirect("lead_detail", pk=pk)
    if lead.stage == Lead.LOST:
        messages.error(request, "Reopen the lead before booking.")
        return redirect("lead_detail", pk=pk)
    form = BookingForm(request.POST or None, initial={"project": lead.project_id, "booking_date": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            booking = form.save(commit=False)
            booking.lead = lead
            booking.executive = lead.owner or request.user
            booking.save()
            set_stage(lead, Lead.BOOKED, request.user)
            log_activity(lead, "note", request.user,
                         note=f"Booked unit {booking.unit_no} at {booking.project} for ₹{booking.deal_value:,.0f}")
            audit(request.user, "booking", booking, f"{lead.name} booked {booking.project} {booking.unit_no}")
        messages.success(request, f"Congratulations! {lead.name} has booked {booking.project} - {booking.unit_no}.")
        return redirect("lead_detail", pk=pk)
    return render(request, "crm/bookings/form.html", {"form": form, "lead": lead})


@role_required(*SALES_ROLES)
def booking_list(request):
    bookings = Booking.objects.filter(lead__in=visible_leads(request.user)).select_related(
        "lead", "project", "executive"
    )
    project = request.GET.get("project", "")
    if project:
        bookings = bookings.filter(project_id=project)
    totals = bookings.aggregate(value=Sum("deal_value"), amount=Sum("booking_amount"))
    return render(
        request,
        "crm/bookings/list.html",
        {"page": Paginator(bookings, 25).get_page(request.GET.get("page")), "totals": totals,
         "projects": Project.objects.all(), "project": project},
    )


@role_required(ADMIN)
@require_POST
def booking_cancel(request, pk):
    booking = get_object_or_404(Booking.objects.select_related("lead"), pk=pk)
    lead = booking.lead
    with transaction.atomic():
        audit(request.user, "booking_cancel", booking, f"Cancelled booking {booking.unit_no} for {lead.name}")
        booking.delete()
        lead.stage = Lead.NEGOTIATION
        lead.save(update_fields=["stage", "updated_at"])
        log_activity(lead, "system", request.user, note="Booking cancelled - lead moved back to Negotiation")
    messages.success(request, "Booking cancelled.")
    return redirect("lead_detail", pk=lead.pk)


@role_required(*SALES_ROLES)
def notifications(request):
    items = Notification.objects.filter(user=request.user)[:100]
    return render(request, "crm/notifications.html", {"items": items})


@role_required(*SALES_ROLES)
def notification_open(request, pk):
    note = get_object_or_404(Notification, pk=pk, user=request.user)
    note.is_read = True
    note.save(update_fields=["is_read"])
    return redirect(note.url if note.url.startswith("/") and not note.url.startswith("//") else "notifications")


@role_required(*SALES_ROLES)
@require_POST
def notifications_read_all(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect("notifications")
