from django.db import transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from .models import Activity, Assignment, AuditLog, Lead, Notification, Profile, normalize_phone


def audit(user, action, obj, summary):
    AuditLog.objects.create(
        user=user if user and user.is_authenticated else None,
        action=action,
        object_type=obj.__class__.__name__,
        object_id=str(getattr(obj, "pk", "") or ""),
        summary=summary[:300],
    )


def notify(user, text, url=""):
    if user:
        Notification.objects.create(user=user, text=text[:200], url=url)


def lead_url(lead):
    return reverse("lead_detail", args=[lead.pk])


def log_activity(lead, kind, user, note="", outcome=""):
    activity = Activity.objects.create(lead=lead, kind=kind, outcome=outcome, note=note, created_by=user)
    if kind in Activity.RESPONSE_KINDS:
        changed = []
        if not lead.first_response_at:
            lead.first_response_at = activity.created_at
            changed.append("first_response_at")
        if lead.stage == Lead.NEW:
            set_stage(lead, Lead.CONTACTED, user, auto=True)
        if changed:
            lead.save(update_fields=changed + ["updated_at"])
    return activity


def set_stage(lead, stage, user, lost_reason="", lost_note="", auto=False):
    if stage not in dict(Lead.STAGES):
        raise ValueError("Unknown stage")
    if stage == Lead.LOST and not lost_reason:
        raise ValueError("A lost reason is required.")
    old = lead.stage
    if old == stage:
        return
    lead.stage = stage
    lead.stage_changed_at = timezone.now()
    lead.max_stage_rank = max(lead.max_stage_rank, Lead.STAGE_RANK[stage])
    if stage == Lead.LOST:
        lead.lost_reason, lead.lost_note = lost_reason, lost_note
        lead.next_followup = None
        lead.temperature = Lead.COLD
    elif stage == Lead.BOOKED:
        lead.next_followup = None
        lead.temperature = Lead.HOT
    else:
        lead.lost_reason, lead.lost_note = "", ""
    lead.save()
    labels = dict(Lead.STAGES)
    note = f"Stage changed: {labels[old]} → {labels[stage]}"
    if stage == Lead.LOST:
        note += f" ({dict(Lead.LOST_REASONS)[lost_reason]}{': ' + lost_note if lost_note else ''})"
    Activity.objects.create(lead=lead, kind="system", note=note + (" (automatic)" if auto else ""), created_by=user)
    if not auto:
        audit(user, "stage_change", lead, f"{lead.name}: {labels[old]} → {labels[stage]}")


def pick_executive(project=None):
    """Round-robin: the available executive who received a lead longest ago (project specialists first)."""
    profiles = Profile.objects.filter(
        role=Profile.EXECUTIVE, accepts_leads=True, user__is_active=True
    ).select_related("user")
    if project:
        specialists = profiles.filter(projects=project)
        if specialists.exists():
            profiles = specialists
    profile = profiles.order_by(F("last_assigned_at").asc(nulls_first=True), "id").first()
    return profile.user if profile else None


def assign(lead, to_user, by_user=None, reason=""):
    previous = lead.owner
    if previous == to_user:
        return
    lead.owner = to_user
    lead.save(update_fields=["owner", "updated_at"])
    Assignment.objects.create(lead=lead, from_user=previous, to_user=to_user, by_user=by_user, reason=reason)
    Profile.objects.filter(user=to_user).update(last_assigned_at=timezone.now())
    who = by_user.get_full_name() if by_user else "Auto-assignment"
    Activity.objects.create(
        lead=lead, kind="system", created_by=by_user,
        note=f"Assigned to {to_user.get_full_name() or to_user.username} by {who}" + (f" - {reason}" if reason else ""),
    )
    notify(to_user, f"New lead assigned: {lead.name} ({lead.get_source_display()})", lead_url(lead))
    if by_user:
        audit(by_user, "reassign", lead, f"{lead.name}: {previous or 'unassigned'} → {to_user}")


def auto_assign(lead, by_user=None):
    executive = pick_executive(lead.project)
    if executive:
        assign(lead, executive, by_user=None, reason="Round-robin")
    return executive


@transaction.atomic
def capture_lead(data, user=None, channel=""):
    """Create a lead or, if the phone already exists, record a re-enquiry. Returns (lead, created)."""
    phone = normalize_phone(data["phone"])
    existing = Lead.objects.select_for_update().filter(phone=phone).first()
    if existing:
        existing.enquiry_count += 1
        existing.last_enquiry_at = timezone.now()
        note = f"Enquired again via {dict(Lead.SOURCES).get(data.get('source'), channel or 'unknown')}"
        if data.get("project") and data["project"] != existing.project:
            note += f" (asked about {data['project']})"
        if existing.stage == Lead.LOST:
            existing.stage = Lead.NEW
            existing.temperature = Lead.WARM
            existing.lost_reason = existing.lost_note = ""
            note += " - lead reopened"
        existing.save()
        Activity.objects.create(lead=existing, kind="system", note=note, created_by=user)
        notify(existing.owner, f"{existing.name} enquired again ({existing.enquiry_count}x)", lead_url(existing))
        return existing, False

    owner = data.pop("owner", None)
    lead = Lead(**{**data, "phone": phone}, created_by=user)
    lead.full_clean()
    lead.save()
    Activity.objects.create(
        lead=lead, kind="system", created_by=user,
        note=f"Lead created via {channel or lead.get_source_display()}",
    )
    if owner:
        assign(lead, owner, by_user=user, reason="Assigned at creation")
    else:
        auto_assign(lead)
    if user:
        audit(user, "create", lead, f"Lead {lead.name} ({lead.phone}) created")
    return lead, True


def transfer_leads(from_user, to_user, by_user, only_open=True):
    """Move a departing executive's leads to one person, or round-robin when to_user is None."""
    leads = Lead.objects.filter(owner=from_user)
    if only_open:
        leads = leads.filter(stage__in=Lead.OPEN_STAGES)
    count = 0
    for lead in leads:
        target = to_user or auto_pick_excluding(lead, from_user)
        if target:
            assign(lead, target, by_user=by_user, reason=f"Transferred from {from_user.get_full_name()}")
            count += 1
    audit(by_user, "transfer", from_user, f"{count} leads transferred from {from_user.get_full_name()}")
    return count


def auto_pick_excluding(lead, excluded):
    Profile.objects.filter(user=excluded).update(accepts_leads=False)
    return pick_executive(lead.project)
