import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from crm.models import (
    Activity, AdSpend, Assignment, AuditLog, Booking, Lead, Notification, Profile, Project, SiteVisit, Target, Team,
    month_start,
)

PASSWORD = "Demo@1234"
STAFF = [
    # username, first, last, role, team, response-minutes, closing skill
    ("karthik", "Karthik", "Raman", Profile.ADMIN, None, None, None),
    ("meera", "Meera", "Krishnan", Profile.MANAGER, None, None, None),
    ("arun", "Arun", "Prakash", Profile.LEADER, "Team Velachery", None, None),
    ("sneha", "Sneha", "Iyer", Profile.LEADER, "Team OMR", None, None),
    ("divya", "Divya", "Subramanian", Profile.EXECUTIVE, "Team Velachery", 12, 1.45),
    ("rahul", "Rahul", "Menon", Profile.EXECUTIVE, "Team Velachery", 25, 1.1),
    ("priya", "Priya", "Natarajan", Profile.EXECUTIVE, "Team Velachery", 50, 0.9),
    ("vignesh", "Vignesh", "Kumar", Profile.EXECUTIVE, "Team Velachery", 95, 0.7),
    ("sanjay", "Sanjay", "Reddy", Profile.EXECUTIVE, "Team OMR", 15, 1.3),
    ("kavitha", "Kavitha", "Rajan", Profile.EXECUTIVE, "Team OMR", 30, 1.0),
    ("manoj", "Manoj", "Pillai", Profile.EXECUTIVE, "Team OMR", 170, 0.6),
    ("lakshmi", "Lakshmi", "Venkat", Profile.EXECUTIVE, "Team OMR", 60, 0.9),
]
PROJECTS = [
    # name, location, types, from, to, team, weight, property types
    ("MV Lakeview Residences", "Velachery, Chennai", "2 & 3 BHK", 75, 140, "Team Velachery", 30, ["2bhk", "3bhk"]),
    ("MV Metro Heights", "Porur, Chennai", "2 & 3 BHK", 65, 120, "Team Velachery", 25, ["2bhk", "3bhk"]),
    ("MV Greens", "Siruseri, OMR", "2 & 3 BHK", 55, 95, "Team OMR", 35, ["2bhk", "3bhk"]),
    ("MV Royal Villas", "ECR, Chennai", "4 BHK Villas", 180, 320, "Team OMR", 10, ["villa", "4bhk"]),
]
SOURCES = {  # weight, quality
    "facebook": (25, 0.8), "google": (15, 0.9), "website": (12, 1.05), "99acres": (14, 0.95),
    "magicbricks": (10, 0.9), "walk_in": (7, 1.35), "referral": (6, 1.45), "channel_partner": (6, 1.25),
    "print": (3, 0.75), "other": (2, 0.85),
}
AD_SPEND = {"facebook": 180000, "google": 140000, "99acres": 85000, "magicbricks": 60000, "print": 55000,
            "website": 25000, "channel_partner": 40000}
STEP_P = {1: 0.88, 2: 0.56, 3: 0.52, 4: 0.8, 5: 0.56, 6: 0.42}
LOST_BY_RANK = {
    0: ["not_reachable", "not_reachable", "not_interested"],
    1: ["not_interested", "not_reachable", "budget"],
    2: ["budget", "location", "not_interested", "bought_elsewhere"],
    3: ["location", "budget", "bought_elsewhere"],
    4: ["budget", "bought_elsewhere", "loan_rejected", "location"],
    5: ["bought_elsewhere", "budget", "loan_rejected", "other"],
}
FIRST = ["Ramesh", "Suresh", "Anitha", "Deepak", "Lavanya", "Gopal", "Harini", "Ashok", "Bhavani", "Chandru",
         "Dinesh", "Geetha", "Hari", "Indira", "Jagan", "Kamala", "Mohan", "Nirmala", "Prakash", "Radha",
         "Saravanan", "Shalini", "Senthil", "Tamil", "Uma", "Venkatesh", "Yamuna", "Arvind", "Bala", "Charu",
         "Ganesh", "Janani", "Karthick", "Madhu", "Naveen", "Pooja", "Raghav", "Sowmya", "Thilak", "Vidya",
         "Abdul", "Fathima", "Joseph", "Mary", "Rohit", "Neha", "Amit", "Sunita", "Rajesh", "Anjali"]
LAST = ["Kumar", "Srinivasan", "Raman", "Iyer", "Pillai", "Reddy", "Nair", "Chandran", "Murugan", "Balaji",
        "Sundaram", "Ganesan", "Rao", "Sharma", "Krishnan", "Mohan", "Rahman", "Thomas", "Gupta", "Joseph"]
AREAS = ["Velachery", "Adyar", "Tambaram", "Porur", "Anna Nagar", "T. Nagar", "Sholinganallur", "Guindy",
         "Medavakkam", "Pallikaranai", "Perungudi", "Mylapore", "Chromepet", "Bangalore", "Dubai (NRI)"]
NOTES = {
    "call": ["Discussed floor plans and pricing", "Asked about loan options", "Wants east-facing unit",
             "Comparing with another builder", "Will discuss with family this weekend", "Asked for best price",
             "Interested in higher floor", "Needs possession within 12 months"],
    "whatsapp": ["Shared brochure and price sheet", "Sent location pin", "Shared payment plan", "Sent offer details"],
}


class Command(BaseCommand):
    help = "Load a realistic 6-month demo dataset for the configured company."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            for model in (Notification, AuditLog, Booking, SiteVisit, Activity, Assignment, Lead, Target, AdSpend):
                model.objects.all().delete()
            Project.objects.all().delete()
        self.rng = rng = random.Random(42)
        self.now = now = timezone.now()
        self.used_phones = set(Lead.objects.values_list("phone", flat=True))

        users, profiles = self._users()
        projects = self._projects()
        team_execs = {
            team: [u for u, p in profiles.items() if p.team and p.team.name == team and p.role == Profile.EXECUTIVE]
            for team in ("Team Velachery", "Team OMR")
        }
        for name, *_rest, team, _w, _types in PROJECTS:
            for u in team_execs[team]:
                profiles[u].projects.add(projects[name])

        if Lead.objects.exists():
            self.stdout.write(self.style.WARNING("Leads already exist. Use --reset to reload."))
            return

        execs = [u for u, p in profiles.items() if p.role == Profile.EXECUTIVE]
        speed = {u: next(s[5] for s in STAFF if s[0] == u.username) for u in execs}
        skill = {u: next(s[6] for s in STAFF if s[0] == u.username) for u in execs}
        source_keys, source_w = list(SOURCES), [SOURCES[s][0] for s in SOURCES]
        proj_names, proj_w = [p[0] for p in PROJECTS], [p[6] for p in PROJECTS]

        count = 0
        for _ in range(820):
            days_ago = int(180 * rng.random() ** 1.12)
            created = now - timedelta(days=days_ago, hours=rng.randint(0, 12), minutes=rng.randint(0, 59))
            if days_ago == 0:
                created = now - timedelta(minutes=rng.randint(20, 600))
            source = rng.choices(source_keys, weights=source_w)[0]
            pname = rng.choices(proj_names, weights=proj_w)[0] if rng.random() < 0.88 else None
            project = projects.get(pname)
            team = next(p[5] for p in PROJECTS if p[0] == pname) if pname else rng.choice(list(team_execs))
            owner = rng.choice(team_execs[team])
            self._make_lead(created, source, project, pname, owner, speed[owner], skill[owner], users)
            count += 1

        self._untouched(execs, projects, users)
        self._ad_spend_targets(execs)
        self._extras(users, execs)
        self.stdout.write(self.style.SUCCESS(
            f"Loaded {len(users)} users, {len(projects)} projects, {Lead.objects.count()} leads, "
            f"{Activity.objects.count()} activities, {SiteVisit.objects.count()} site visits, "
            f"{Booking.objects.count()} bookings."
        ))

    # ------------------------------------------------------------------ helpers

    def _users(self):
        User = get_user_model()
        teams = {}
        users, profiles = {}, {}
        for username, first, last, role, team, *_ in STAFF:
            user, _ = User.objects.get_or_create(username=username)
            user.first_name, user.last_name, user.email = first, last, f"{username}@{settings.COMPANY_WEBSITE}"
            user.is_active = True
            user.is_staff = user.is_superuser = role == Profile.ADMIN
            user.set_password(PASSWORD)
            user.save()
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.role = role
            profile.phone = f"98400{self.rng.randint(10000, 99999)}"
            profile.accepts_leads = role == Profile.EXECUTIVE
            if team:
                teams.setdefault(team, Team.objects.get_or_create(name=team)[0])
                profile.team = teams[team]
            profile.save()
            users[username], profiles[user] = user, profile
        Team.objects.filter(name="Team Velachery").update(leader=users["arun"])
        Team.objects.filter(name="Team OMR").update(leader=users["sneha"])
        return users, profiles

    def _projects(self):
        out = {}
        for name, loc, types, pfrom, pto, *_ in PROJECTS:
            out[name], _ = Project.objects.update_or_create(
                name=name,
                defaults={"location": loc, "property_types": types, "price_from": pfrom, "price_to": pto,
                          "brochure_url": f"https://{settings.COMPANY_WEBSITE}/{name.split()[1].lower()}.pdf"},
            )
        return out

    def _phone(self):
        while True:
            p = f"{self.rng.choice('9876')}{self.rng.randint(100000000, 999999999)}"
            if p not in self.used_phones:
                self.used_phones.add(p)
                return p

    def _act(self, lead, kind, at, by, note="", outcome=""):
        if at <= self.now:
            Activity.objects.create(lead=lead, kind=kind, note=note, outcome=outcome, created_by=by, created_at=at)

    def _budget_for(self, pname):
        if not pname:
            return self.rng.choice([b for b, _ in Lead.BUDGETS])
        lo, hi = next((p[3], p[4]) for p in PROJECTS if p[0] == pname)
        mid = self.rng.uniform(lo, hi)
        for key, cap in (("lt50", 50), ("50_75", 75), ("75_100", 100), ("100_150", 150)):
            if mid < cap:
                return key
        return "gt150"

    def _make_lead(self, created, source, project, pname, owner, speed, skill, users):
        rng, now = self.rng, self.now
        quality = SOURCES[source][1]
        types = next(p[7] for p in PROJECTS if p[0] == pname) if pname else ["2bhk", "3bhk"]
        lead = Lead.objects.create(
            name=f"{rng.choice(FIRST)} {rng.choice(LAST)}", phone=self._phone(),
            email="" if rng.random() < 0.4 else f"user{rng.randint(1000, 99999)}@example.com",
            area=rng.choice(AREAS), budget=self._budget_for(pname), property_type=rng.choice(types),
            project=project, source=source, owner=owner, language="ta" if rng.random() < 0.3 else "en",
            created_at=created, last_enquiry_at=created, stage_changed_at=created,
            notes=rng.choice(["", "", "Looking for ready-to-move", "Investment purpose", "First home",
                              "Wants near IT corridor", "NRI - prefers video call"]),
        )
        Activity.objects.create(lead=lead, kind="system", created_at=created,
                                note=f"Lead created via {lead.get_source_display()}")
        Assignment.objects.create(lead=lead, to_user=owner, reason="Round-robin", created_at=created)
        Activity.objects.create(lead=lead, kind="system", created_at=created + timedelta(seconds=5),
                                note=f"Assigned to {owner.get_full_name()} by Auto-assignment - Round-robin")

        rank, t = 0, created
        times = {}
        for r in range(1, 7):
            p = STEP_P[r] * (quality if r >= 2 else 1) * (skill if r >= 5 else 1)
            if rng.random() > min(p, 0.95):
                break
            if r == 1:
                gap = timedelta(minutes=max(2, rng.gauss(speed, speed * 0.6)))
            else:
                gap = timedelta(days=rng.uniform(*{2: (0.5, 4), 3: (1, 6), 4: (1, 5), 5: (2, 9), 6: (3, 14)}[r]))
            if t + gap > now:
                break
            t += gap
            rank, times[r] = r, t

        stage_for_rank = {0: Lead.NEW, 1: Lead.CONTACTED, 2: Lead.INTERESTED, 3: Lead.SV_SCHEDULED,
                          4: Lead.SV_DONE, 5: Lead.NEGOTIATION, 6: Lead.BOOKED}
        visit_at = None
        if 1 in times:
            lead.first_response_at = times[1]
            self._act(lead, "call", times[1], owner, rng.choice(NOTES["call"]), "connected")
            self._act(lead, "whatsapp", times[1] + timedelta(minutes=8), owner, "WhatsApp sent: First response (EN)")
        elif (now - created).days > 2:
            for k in range(rng.randint(1, 3)):
                self._act(lead, "call", created + timedelta(hours=2 + k * 20), owner, "", rng.choice(["no_answer", "switched_off", "busy"]))
        for r in range(2, rank + 1):
            between = times[r - 1] + (times[r] - times[r - 1]) / 2
            kind = rng.choice(["call", "call", "whatsapp", "meeting"]) if r >= 5 else rng.choice(["call", "whatsapp"])
            self._act(lead, kind, between, owner, rng.choice(NOTES.get(kind, NOTES["call"])), "interested" if kind == "call" else "")
            self._act(lead, "system", times[r], owner, f"Stage changed: {dict(Lead.STAGES)[stage_for_rank[r - 1]]} → {dict(Lead.STAGES)[stage_for_rank[r]]}")

        if rank >= 3:
            visit_at = times.get(4) or max(times[3] + timedelta(days=rng.uniform(1, 5)), now + timedelta(hours=rng.randint(2, 140)))
            visit_at = timezone.make_aware(datetime.combine(timezone.localtime(visit_at).date(),
                                                            time(rng.choice([10, 11, 12, 15, 16, 17]), rng.choice([0, 30]))))
            if 4 in times:
                visit_at = min(visit_at, times[4])

        lost_reason = ""
        last = times.get(rank, created)
        stage = stage_for_rank[rank]
        if rank < 6 and (now - last).days > rng.randint(18, 45):
            stage = Lead.LOST
            lost_reason = rng.choice(LOST_BY_RANK[rank])
            lost_at = min(now, last + timedelta(days=rng.randint(5, 18)))
            self._act(lead, "system", lost_at, owner, f"Stage changed: → Lost ({dict(Lead.LOST_REASONS)[lost_reason]})")
            last = lost_at

        lead.stage, lead.max_stage_rank, lead.stage_changed_at = stage, rank, last
        lead.lost_reason = lost_reason
        lead.temperature = Lead.COLD if stage == Lead.LOST else (
            Lead.HOT if rank >= 4 or stage == Lead.BOOKED else rng.choice([Lead.WARM, Lead.WARM, Lead.COLD, Lead.HOT]))
        if stage in Lead.OPEN_STAGES:
            lead.next_followup = now + timedelta(hours=rng.uniform(-80, 110))
            if stage == Lead.SV_SCHEDULED and visit_at:
                lead.next_followup = visit_at - timedelta(hours=3)
        if rng.random() < 0.08:
            lead.enquiry_count = 2
            again = min(now, created + timedelta(days=rng.randint(3, 40)))
            lead.last_enquiry_at = again
            self._act(lead, "system", again, None, f"Enquired again via {rng.choice(['99acres', 'Facebook Ads', 'Website'])}")
        lead.save()

        if visit_at and project:
            status = SiteVisit.DONE if rank >= 4 else (SiteVisit.NO_SHOW if stage == Lead.LOST else SiteVisit.SCHEDULED)
            SiteVisit.objects.create(
                lead=lead, project=project, scheduled_at=visit_at, executive=owner, status=status,
                completed_at=visit_at + timedelta(hours=1) if status != SiteVisit.SCHEDULED else None,
                feedback=rng.choice(["Liked the clubhouse and layout", "Felt the price is high", "Wants a higher floor",
                                     "Family loved the unit", "Concerned about traffic"]) if status == SiteVisit.DONE else "",
                created_by=owner, created_at=times[3],
            )
            if status == SiteVisit.DONE:
                self._act(lead, "site_visit", visit_at + timedelta(hours=1), owner, f"Site visit done at {project}.")
        if stage == Lead.BOOKED:
            lo, hi = (float(project.price_from), float(project.price_to)) if project else (60.0, 100.0)
            value = Decimal(round(rng.uniform(lo, hi) * 2) * 50000)
            Booking.objects.create(
                lead=lead, project=project or Project.objects.first(), unit_no=f"{rng.choice('ABCD')}-{rng.randint(1, 14)}{rng.randint(1, 8):02d}",
                deal_value=value, booking_amount=(value * Decimal("0.1")).quantize(Decimal("1000")),
                booking_date=timezone.localtime(times[6]).date(), executive=owner, created_at=times[6],
            )

    def _untouched(self, execs, projects, users):
        rng = self.rng
        for i in range(7):
            owner = rng.choice(execs)
            created = self.now - timedelta(minutes=rng.randint(35, 300))
            lead = Lead.objects.create(
                name=f"{rng.choice(FIRST)} {rng.choice(LAST)}", phone=self._phone(), area=rng.choice(AREAS),
                project=rng.choice(list(projects.values())), source=rng.choice(["facebook", "website", "99acres", "google"]),
                property_type=rng.choice(["2bhk", "3bhk"]), budget=rng.choice(["50_75", "75_100"]), owner=owner,
                created_at=created, last_enquiry_at=created, stage_changed_at=created, temperature=Lead.WARM,
                next_followup=created + timedelta(minutes=30),
            )
            Activity.objects.create(lead=lead, kind="system", created_at=created, note=f"Lead created via {lead.get_source_display()}")
            Assignment.objects.create(lead=lead, to_user=owner, reason="Round-robin", created_at=created)
            Notification.objects.create(user=owner, text=f"New lead assigned: {lead.name} ({lead.get_source_display()})",
                                        url=f"/leads/{lead.pk}/", created_at=created)

    def _ad_spend_targets(self, execs):
        today = timezone.localdate()
        m = month_start(today)
        for i in range(7):
            for source, base in AD_SPEND.items():
                AdSpend.objects.update_or_create(month=m, source=source, defaults={
                    "amount": Decimal(round(base * self.rng.uniform(0.85, 1.15), -3))})
            for u in execs:
                Target.objects.update_or_create(user=u, month=m, defaults={
                    "site_visits": self.rng.choice([8, 10, 12]), "bookings": self.rng.choice([2, 2, 3])})
            m = month_start(m - timedelta(days=1))

    def _extras(self, users, execs):
        for u in execs:
            for lead in Lead.objects.filter(owner=u).order_by("-created_at")[:6]:
                Notification.objects.create(user=u, text=f"New lead assigned: {lead.name} ({lead.get_source_display()})",
                                            url=f"/leads/{lead.pk}/", created_at=lead.created_at,
                                            is_read=lead.first_response_at is not None)
        for lead in Lead.objects.filter(stage=Lead.SV_SCHEDULED, owner__in=execs)[:5]:
            Notification.objects.create(user=users["arun"], text=f"Site visit scheduled: {lead.name}", url=f"/leads/{lead.pk}/")
        AuditLog.objects.create(user=users["meera"], action="export", object_type="Lead", summary="Exported 214 leads",
                                created_at=self.now - timedelta(days=3))
        AuditLog.objects.create(user=users["karthik"], action="update", object_type="Project",
                                summary="Saved project MV Royal Villas", created_at=self.now - timedelta(days=9))
        for b in Booking.objects.select_related("lead", "executive").order_by("-created_at")[:10]:
            AuditLog.objects.create(user=b.executive, action="booking", object_type="Booking", object_id=str(b.pk),
                                    summary=f"{b.lead.name} booked {b.project} {b.unit_no}", created_at=b.created_at)
