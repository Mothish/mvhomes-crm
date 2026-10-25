from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect, render
from django.utils import timezone

from ..access import EXECUTIVE, LEADER, MGMT, SALES_ROLES, get_role, role_required, visible_leads, visible_users
from ..models import Activity, AdSpend, Booking, Lead, Project, SiteVisit, Target, month_start

PERIODS = [("month", "This month"), ("last_month", "Last month"), ("30", "Last 30 days"), ("90", "Last 90 days")]
FUNNEL = [("Leads", 0), ("Contacted", 1), ("Interested", 2), ("Site visit done", 4), ("Negotiation", 5), ("Booked", 6)]


def period_range(key, today):
    if key == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if key in ("30", "90"):
        return today - timedelta(days=int(key) - 1), today
    return today.replace(day=1), today


def parse_range(request, today):
    try:
        start = datetime.strptime(request.GET.get("from", ""), "%Y-%m-%d").date()
        end = datetime.strptime(request.GET.get("to", ""), "%Y-%m-%d").date()
        if start > end:
            start, end = end, start
    except ValueError:
        start, end = period_range(request.GET.get("period", "month"), today)
    return start, end


def change_pct(current, previous):
    if not previous:
        return None
    return round((float(current) - float(previous)) * 100 / float(previous))


def funnel(leads):
    agg = leads.aggregate(**{f"s{rank}": Count("id", filter=Q(max_stage_rank__gte=rank)) for _, rank in FUNNEL})
    top = agg["s0"] or 0
    steps = []
    for label, rank in FUNNEL:
        n = agg[f"s{rank}"] or 0
        steps.append({"label": label, "count": n, "pct": round(n * 100 / top) if top else 0})
    return steps


def avg_response(leads):
    pairs = leads.filter(first_response_at__isnull=False).values_list("created_at", "first_response_at")
    mins = [max(0, (b - a).total_seconds() / 60) for a, b in pairs]
    return round(sum(mins) / len(mins)) if mins else None


def user_row(user, scope, start, end, month):
    owned = scope.filter(owner=user)
    new = owned.filter(created_at__date__range=(start, end))
    visits = SiteVisit.objects.filter(executive=user, status=SiteVisit.DONE, completed_at__date__range=(start, end)).count()
    bookings = Booking.objects.filter(executive=user, booking_date__range=(start, end))
    b = bookings.aggregate(n=Count("id"), v=Sum("deal_value"))
    target = Target.objects.filter(user=user, month=month).first()
    month_visits = SiteVisit.objects.filter(executive=user, status=SiteVisit.DONE, completed_at__date__gte=month).count()
    month_bookings = Booking.objects.filter(executive=user, booking_date__gte=month).count()
    activities = Activity.objects.filter(created_by=user, created_at__date__range=(start, end))
    return {
        "user": user,
        "open": owned.filter(stage__in=Lead.OPEN_STAGES).count(),
        "overdue": owned.filter(stage__in=Lead.OPEN_STAGES, next_followup__lt=timezone.now()).count(),
        "new": new.count(),
        "calls": activities.filter(kind="call").count(),
        "whatsapp": activities.filter(kind="whatsapp").count(),
        "visits": visits,
        "bookings": b["n"] or 0,
        "value": b["v"] or 0,
        "conversion": round((b["n"] or 0) * 100 / new.count()) if new.count() else 0,
        "response": avg_response(new),
        "target": target,
        "month_visits": month_visits,
        "month_bookings": month_bookings,
    }


def daily_trend(scope, start, end):
    days = (end - start).days + 1
    labels = [(start + timedelta(days=i)) for i in range(days)]
    leads = dict(
        scope.filter(created_at__date__range=(start, end)).values_list("created_at__date").annotate(c=Count("id")).order_by()
    )
    bookings = dict(
        Booking.objects.filter(lead__in=scope, booking_date__range=(start, end))
        .values_list("booking_date").annotate(c=Count("id")).order_by()
    )
    return {
        "labels": [d.strftime("%d %b") for d in labels],
        "leads": [leads.get(d, 0) for d in labels],
        "bookings": [bookings.get(d, 0) for d in labels],
    }


@role_required(*SALES_ROLES)
def home(request):
    if get_role(request.user) == EXECUTIVE:
        return exec_dashboard(request)
    today = timezone.localdate()
    period = request.GET.get("period", "month")
    start, end = period_range(period, today)
    length = (end - start).days + 1
    prev_start, prev_end = start - timedelta(days=length), start - timedelta(days=1)
    if period in ("month", "last_month"):
        prev_start = month_start(start - timedelta(days=1))
        prev_end = min(prev_start + timedelta(days=length - 1), start - timedelta(days=1))

    scope = visible_leads(request.user)
    leads_p = scope.filter(created_at__date__range=(start, end))
    leads_prev = scope.filter(created_at__date__range=(prev_start, prev_end)).count()
    bookings = Booking.objects.filter(lead__in=scope, booking_date__range=(start, end))
    b = bookings.aggregate(n=Count("id"), v=Sum("deal_value"))
    b_prev = Booking.objects.filter(lead__in=scope, booking_date__range=(prev_start, prev_end)).count()
    visits = SiteVisit.objects.filter(lead__in=scope, status=SiteVisit.DONE, completed_at__date__range=(start, end)).count()
    now = timezone.now()
    open_leads = scope.filter(stage__in=Lead.OPEN_STAGES)

    by_source = list(leads_p.values("source").annotate(c=Count("id")).order_by("-c"))
    src_labels = dict(Lead.SOURCES)
    by_project = list(
        leads_p.values("project__name").annotate(c=Count("id"), booked=Count("id", filter=Q(stage=Lead.BOOKED)))
        .order_by("-c")
    )
    month = month_start(today)
    team = [
        user_row(u, scope, start, end, month)
        for u in visible_users(request.user).filter(profile__role__in=(EXECUTIVE, LEADER))
    ]
    team.sort(key=lambda r: (-r["value"], -r["bookings"], -r["visits"]))
    return render(
        request,
        "crm/dashboard.html",
        {
            "period": period, "periods": PERIODS, "start": start, "end": end,
            "kpi": {
                "leads": leads_p.count(), "leads_pct": change_pct(leads_p.count(), leads_prev),
                "visits": visits, "bookings": b["n"] or 0, "bookings_pct": change_pct(b["n"] or 0, b_prev),
                "value": b["v"] or 0, "response": avg_response(leads_p),
                "conversion": round((b["n"] or 0) * 100 / leads_p.count()) if leads_p.count() else 0,
            },
            "alerts": {
                "waiting": open_leads.filter(first_response_at__isnull=True, created_at__lt=now - timedelta(hours=2)).count(),
                "overdue": open_leads.filter(next_followup__lt=now).count(),
                "unassigned": open_leads.filter(owner__isnull=True).count(),
                "hot": open_leads.filter(temperature=Lead.HOT).count(),
                "web_today": scope.filter(source="website", created_at__date=today).count(),
            },
            "funnel": funnel(leads_p),
            "team": team,
            "charts": {
                "source": {"labels": [src_labels[r["source"]] for r in by_source], "values": [r["c"] for r in by_source]},
                "project": {"labels": [r["project__name"] or "Not decided" for r in by_project],
                            "leads": [r["c"] for r in by_project], "booked": [r["booked"] for r in by_project]},
                "trend": daily_trend(scope, start, end),
            },
        },
    )


def exec_dashboard(request):
    user = request.user
    today = timezone.localdate()
    now = timezone.now()
    month = month_start(today)
    mine = Lead.objects.filter(owner=user)
    open_mine = mine.filter(stage__in=Lead.OPEN_STAGES)
    row = user_row(user, mine, month, today, month)
    agenda = list(open_mine.filter(next_followup__date__lte=today).select_related("project").order_by("next_followup")[:10])
    visits = SiteVisit.objects.filter(executive=user, status=SiteVisit.SCHEDULED, scheduled_at__gte=now - timedelta(hours=6)) \
        .select_related("lead", "project").order_by("scheduled_at")[:6]
    rank_rows = sorted(
        ({"user": u, "n": Booking.objects.filter(executive=u, booking_date__gte=month).count()}
         for u in get_user_model().objects.filter(is_active=True, profile__role=EXECUTIVE)),
        key=lambda r: -r["n"],
    )
    my_rank = next((i + 1 for i, r in enumerate(rank_rows) if r["user"].pk == user.pk), None)
    return render(
        request,
        "crm/dashboard_exec.html",
        {
            "today": today, "now": now, "row": row, "agenda": agenda, "visits": visits,
            "untouched": open_mine.filter(first_response_at__isnull=True).count(),
            "due_today": open_mine.filter(next_followup__date=today).count(),
            "hot": open_mine.filter(temperature=Lead.HOT).select_related("project")[:6],
            "funnel": funnel(mine.filter(created_at__date__gte=today - timedelta(days=89))),
            "my_rank": my_rank, "team_size": len(rank_rows),
        },
    )


# ---------------------------------------------------------------- reports


@role_required(*MGMT, LEADER)
def reports(request):
    today = timezone.localdate()
    tab = request.GET.get("tab", "sources")
    start, end = parse_range(request, today)
    scope = visible_leads(request.user)
    project = request.GET.get("project", "")
    if project:
        scope = scope.filter(project_id=project)
    cohort = scope.filter(created_at__date__range=(start, end))
    ctx = {"tab": tab, "start": start, "end": end, "projects": Project.objects.all(), "project": project,
           "periods": PERIODS}

    if tab == "team":
        rows = [user_row(u, scope, start, end, month_start(today))
                for u in visible_users(request.user).filter(profile__role__in=(EXECUTIVE, LEADER))]
        rows.sort(key=lambda r: (-r["bookings"], -r["visits"]))
        ctx["rows"] = rows
        ctx["chart"] = {"labels": [r["user"].get_full_name() for r in rows], "visits": [r["visits"] for r in rows],
                        "bookings": [r["bookings"] for r in rows], "calls": [r["calls"] for r in rows]}
    elif tab == "lost":
        lost = scope.filter(stage=Lead.LOST, stage_changed_at__date__range=(start, end))
        reasons = dict(Lead.LOST_REASONS)
        by_reason = list(lost.values("lost_reason").annotate(c=Count("id")).order_by("-c"))
        total = sum(r["c"] for r in by_reason)
        ctx["rows"] = [{"label": reasons.get(r["lost_reason"], "Unknown"), "count": r["c"],
                        "pct": round(r["c"] * 100 / total) if total else 0} for r in by_reason]
        ctx["total"] = total
        ctx["by_stage"] = [
            {"label": label, "count": lost.filter(max_stage_rank=rank).count()}
            for label, rank in [("Never contacted", 0), ("After first contact", 1), ("While interested", 2),
                                ("After visit scheduled", 3), ("After site visit", 4), ("In negotiation", 5)]
        ]
        ctx["recent"] = lost.select_related("owner", "project").order_by("-stage_changed_at")[:15]
        ctx["chart"] = {"labels": [r["label"] for r in ctx["rows"]], "values": [r["count"] for r in ctx["rows"]]}
    else:
        months = []
        m = month_start(start)
        while m <= end:
            months.append(m)
            m = month_start(m + timedelta(days=32))
        spend = dict(AdSpend.objects.filter(month__in=months).values_list("source").annotate(t=Sum("amount")).order_by())
        rows = []
        for key, label in Lead.SOURCES:
            src = cohort.filter(source=key)
            n = src.count()
            booked = src.filter(stage=Lead.BOOKED)
            nb = booked.count()
            value = Booking.objects.filter(lead__in=booked).aggregate(v=Sum("deal_value"))["v"] or 0
            s = spend.get(key, Decimal("0"))
            rows.append({
                "key": key, "label": label, "leads": n,
                "contacted": src.filter(max_stage_rank__gte=1).count(),
                "visits": src.filter(max_stage_rank__gte=4).count(),
                "bookings": nb, "value": value, "spend": s,
                "conversion": round(nb * 100 / n, 1) if n else 0,
                "cpl": s / n if n and s else None, "cpb": s / nb if nb and s else None,
                "roi": round(float(value) / float(s), 1) if s and value else None,
            })
        rows.sort(key=lambda r: (-r["bookings"], -r["leads"]))
        ctx["rows"] = rows
        ctx["totals"] = {k: sum(r[k] for r in rows) for k in ("leads", "visits", "bookings", "value", "spend")}
        t = ctx["totals"]
        ctx["totals"]["cpl"] = t["spend"] / t["leads"] if t["leads"] and t["spend"] else None
        ctx["totals"]["cpb"] = t["spend"] / t["bookings"] if t["bookings"] and t["spend"] else None
        active = [r for r in rows if r["leads"]]
        ctx["best"] = min((r for r in active if r["cpb"]), key=lambda r: r["cpb"], default=None)
        ctx["worst"] = max((r for r in active if r["spend"] and not r["bookings"]), key=lambda r: r["spend"], default=None)
        ctx["chart"] = {"labels": [r["label"] for r in active], "leads": [r["leads"] for r in active],
                        "visits": [r["visits"] for r in active], "bookings": [r["bookings"] for r in active]}
    return render(request, "crm/reports.html", ctx)


@role_required(*MGMT)
def ad_spend(request):
    today = timezone.localdate()
    try:
        month = datetime.strptime(request.GET.get("month", "") + "-01", "%Y-%m-%d").date()
    except ValueError:
        month = month_start(today)
    if request.method == "POST":
        saved = 0
        for key, _ in Lead.SOURCES:
            raw = request.POST.get(f"amount_{key}", "").replace(",", "").strip()
            if raw == "":
                AdSpend.objects.filter(month=month, source=key).delete()
                continue
            try:
                amount = Decimal(raw)
                if amount < 0:
                    raise ValueError
            except Exception:
                messages.error(request, f"Invalid amount for {dict(Lead.SOURCES)[key]}.")
                return redirect(f"{request.path}?month={month:%Y-%m}")
            AdSpend.objects.update_or_create(month=month, source=key, defaults={"amount": amount})
            saved += 1
        messages.success(request, f"Ad spend saved for {month:%B %Y}.")
        return redirect(f"{request.path}?month={month:%Y-%m}")
    spend = dict(AdSpend.objects.filter(month=month).values_list("source", "amount"))
    end = (month_start(month + timedelta(days=32)) - timedelta(days=1))
    leads = dict(Lead.objects.filter(created_at__date__range=(month, end)).values_list("source").annotate(c=Count("id")).order_by())
    rows = [{"key": k, "label": v, "amount": spend.get(k), "leads": leads.get(k, 0),
             "cpl": spend[k] / leads[k] if spend.get(k) and leads.get(k) else None} for k, v in Lead.SOURCES]
    return render(request, "crm/ad_spend.html", {"rows": rows, "month": month,
                                                 "total": sum(spend.values(), Decimal("0"))})


@role_required(*MGMT, LEADER)
def targets(request):
    today = timezone.localdate()
    try:
        month = datetime.strptime(request.GET.get("month", "") + "-01", "%Y-%m-%d").date()
    except ValueError:
        month = month_start(today)
    users = visible_users(request.user).filter(profile__role__in=(EXECUTIVE, LEADER))
    can_edit = get_role(request.user) in MGMT
    if request.method == "POST" and can_edit:
        for u in users:
            try:
                sv = int(request.POST.get(f"sv_{u.pk}") or 0)
                bk = int(request.POST.get(f"bk_{u.pk}") or 0)
            except ValueError:
                messages.error(request, "Targets must be whole numbers.")
                return redirect(f"{request.path}?month={month:%Y-%m}")
            Target.objects.update_or_create(user=u, month=month, defaults={"site_visits": max(sv, 0), "bookings": max(bk, 0)})
        messages.success(request, f"Targets saved for {month:%B %Y}.")
        return redirect(f"{request.path}?month={month:%Y-%m}")
    end = month_start(month + timedelta(days=32)) - timedelta(days=1)
    rows = []
    for u in users:
        t = Target.objects.filter(user=u, month=month).first()
        rows.append({
            "user": u, "target": t,
            "visits": SiteVisit.objects.filter(executive=u, status=SiteVisit.DONE, completed_at__date__range=(month, end)).count(),
            "bookings": Booking.objects.filter(executive=u, booking_date__range=(month, end)).count(),
        })
    return render(request, "crm/targets.html", {"rows": rows, "month": month, "can_edit": can_edit,
                                                "prev": month_start(month - timedelta(days=1)),
                                                "next": month_start(month + timedelta(days=32))})
