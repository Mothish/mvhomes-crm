from datetime import timedelta
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
STAFF = [  # username, first, last, role, team, first-response minutes
    ("karthik", "Karthik", "Raman", Profile.ADMIN, None, None),
    ("meera", "Meera", "Krishnan", Profile.MANAGER, None, None),
    ("arun", "Arun", "Prakash", Profile.LEADER, "Team Lusail", None),
    ("sneha", "Sneha", "Iyer", Profile.LEADER, "Team West Bay", None),
    ("divya", "Divya", "Subramanian", Profile.EXECUTIVE, "Team Lusail", 12),
    ("rahul", "Rahul", "Menon", Profile.EXECUTIVE, "Team Lusail", 35),
    ("sanjay", "Sanjay", "Reddy", Profile.EXECUTIVE, "Team West Bay", 18),
    ("kavitha", "Kavitha", "Rajan", Profile.EXECUTIVE, "Team West Bay", 55),
]
PROJECTS = [  # name, location, types, price from/to (QAR), team
    ("MV Marina Residences", "Marina District, Lusail", "1-3 BR apartments", 1_150_000, 3_200_000, "Team Lusail"),
    ("MV Pearl Towers", "Porto Arabia, The Pearl-Qatar", "1-3 BR & penthouses", 1_450_000, 5_800_000, "Team West Bay"),
    ("MV West Bay Heights", "West Bay, Doha", "Studio - 2 BR apartments", 780_000, 2_100_000, "Team West Bay"),
    ("MV Wakrah Villas", "Al Wukair, Al Wakrah", "4-5 BR villas & townhouses", 2_400_000, 4_900_000, "Team Lusail"),
]
# name, dial, number, country, city, area, source, project#, type, budget QAR, stage, temp, lang, days ago, owner, lost reason
LEADS = [
    ("Ahmed Al-Kuwari", "+974", "55123401", "QA", "Doha", "Al Sadd", "propertyfinder", 1, "2br", 1_900_000, "sv_scheduled", "hot", "ar", 6, "divya", ""),
    ("Fatima Al-Mannai", "+974", "66123402", "QA", "Lusail", "Fox Hills", "instagram", 0, "1br", 1_250_000, "contacted", "warm", "ar", 2, "rahul", ""),
    ("Rajesh Nair", "+974", "33123403", "QA", "Doha", "Bin Mahmoud", "facebook", 2, "2br", 1_400_000, "interested", "warm", "en", 9, "sanjay", ""),
    ("Sarah Thompson", "+44", "7700900404", "GB", "London", "Canary Wharf", "website", 1, "3br", 3_600_000, "negotiation", "hot", "en", 21, "kavitha", ""),
    ("Mohammed Al-Marri", "+974", "55123405", "QA", "Al Wakrah", "Barwa City", "referral", 3, "villa", 3_800_000, "booked", "hot", "ar", 40, "divya", ""),
    ("Priyanka Menon", "+91", "9840012306", "IN", "Kochi", "Kakkanad", "facebook", 2, "studio", 820_000, "new", "warm", "en", 0, "sanjay", ""),
    ("Omar Haddad", "+971", "501234507", "AE", "Dubai", "Dubai Marina", "google", 0, "2br", 2_000_000, "sv_done", "hot", "en", 14, "rahul", ""),
    ("Aisha Al-Sulaiti", "+974", "66123408", "QA", "Doha", "The Pearl-Qatar", "qatarliving", 1, "penthouse", 5_500_000, "interested", "warm", "ar", 11, "kavitha", ""),
    ("John Mathew", "+974", "33123409", "QA", "Doha", "Old Airport", "walk_in", 2, "1br", 900_000, "booked", "hot", "en", 33, "sanjay", ""),
    ("Khalid Al-Kubaisi", "+974", "55123410", "QA", "Al Rayyan", "Al Gharrafa", "broker", 3, "townhouse", 2_700_000, "lost", "cold", "ar", 45, "divya", "budget"),
    ("Maria Santos", "+974", "66123411", "QA", "Doha", "Najma", "facebook", 2, "studio", 780_000, "lost", "cold", "en", 38, "sanjay", "not_reachable"),
    ("Hassan Raza", "+92", "3001234512", "PK", "Karachi", "DHA", "propertyfinder", 0, "3br", 2_900_000, "contacted", "warm", "en", 4, "rahul", ""),
    ("Noora Al-Hajri", "+974", "55123413", "QA", "Lusail", "Marina District", "instagram", 0, "2br", 1_850_000, "sv_scheduled", "hot", "ar", 7, "rahul", ""),
    ("David Chen", "+1", "2125550114", "US", "New York", "Manhattan", "website", 1, "2br", 2_400_000, "new", "warm", "en", 1, "kavitha", ""),
    ("Ravi Shankar", "+974", "33123415", "QA", "Al Wakrah", "Al Wakrah Corniche", "referral", 3, "villa", 4_200_000, "negotiation", "hot", "en", 26, "divya", ""),
    ("Layla Mansour", "+966", "501234516", "SA", "Riyadh", "Al Olaya", "google", 1, "3br", 3_900_000, "interested", "warm", "ar", 12, "kavitha", ""),
    ("Abdullah Al-Naimi", "+974", "55123417", "QA", "Doha", "West Bay", "propertyfinder", 2, "2br", 1_950_000, "booked", "hot", "ar", 52, "kavitha", ""),
    ("Anil Kumar", "+974", "66123418", "QA", "Doha", "Fereej Bin Omran", "facebook", None, "1br", 950_000, "lost", "cold", "en", 30, "sanjay", "bought_elsewhere"),
    ("Emma Wilson", "+974", "33123419", "QA", "Doha", "Msheireb", "qatarliving", 2, "1br", 1_050_000, "contacted", "warm", "en", 3, "sanjay", ""),
    ("Yousef Al-Emadi", "+974", "55123420", "QA", "Umm Salal", "Umm Salal Mohammed", "walk_in", 3, "villa", 3_500_000, "sv_done", "hot", "ar", 16, "divya", ""),
    ("Grace Fernandes", "+974", "66123421", "QA", "Doha", "Abu Hamour", "instagram", 0, "1br", 1_200_000, "new", "warm", "en", 0, "rahul", ""),
    ("Tariq Saleh", "+965", "50123422", "KW", "Kuwait City", "Salmiya", "google", 1, "2br", 2_300_000, "lost", "cold", "ar", 41, "kavitha", "location"),
    ("Meenakshi Iyer", "+91", "9884012323", "IN", "Chennai", "Velachery", "facebook", 2, "2br", 1_500_000, "interested", "warm", "en", 8, "sanjay", ""),
    ("Faisal Al-Mohannadi", "+974", "55123424", "QA", "Lusail", "Qetaifan Island", "broker", 0, "3br", 3_100_000, "new", "hot", "ar", 0, "divya", ""),
    ("Sunita Rao", "+974", "33123425", "QA", "Al Rayyan", "Education City", "other:LinkedIn", 2, "2br", 1_600_000, "contacted", "warm", "en", 5, "rahul", ""),
]
LOST_AT_RANK = {"not_reachable": 0, "bought_elsewhere": 2, "location": 3, "budget": 4}
AD_SPEND = {"facebook": 18000, "instagram": 12000, "google": 15000, "propertyfinder": 22000, "qatarliving": 6000,
            "print": 9000, "website": 3000, "broker": 8000}
NOTES = ["Asked about payment plan and handover date", "Wants sea view, high floor", "Comparing with another developer",
         "Will decide after family visit", "Asked about residency visa eligibility", "Interested in furnished option"]


class Command(BaseCommand):
    help = "Load a small Qatar demo dataset (4 projects, 8 staff, 25 leads)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            for model in (Notification, AuditLog, Booking, SiteVisit, Activity, Assignment, Lead, Target, AdSpend):
                model.objects.all().delete()
            Project.objects.all().delete()
            get_user_model().objects.filter(profile__isnull=False).exclude(
                username__in=[s[0] for s in STAFF]).delete()
            Team.objects.exclude(name__in={s[4] for s in STAFF if s[4]}).delete()
        if Lead.objects.exists():
            self.stdout.write(self.style.WARNING("Leads already exist. Use --reset to reload."))
            return
        self.now = timezone.now()
        users = self._users()
        projects = self._projects(users)
        for i, row in enumerate(LEADS):
            self._lead(i, row, users, projects)
        self._spend_and_targets(users)
        self.stdout.write(self.style.SUCCESS(
            f"Loaded {len(users)} users, {len(projects)} projects, {Lead.objects.count()} leads, "
            f"{SiteVisit.objects.count()} site visits, {Booking.objects.count()} bookings."
        ))

    def _users(self):
        User = get_user_model()
        users, teams = {}, {}
        for username, first, last, role, team, _speed in STAFF:
            user, _ = User.objects.get_or_create(username=username)
            user.first_name, user.last_name = first, last
            user.email = f"{username}@{settings.COMPANY_WEBSITE}"
            user.is_active = True
            user.is_staff = user.is_superuser = role == Profile.ADMIN
            user.set_password(PASSWORD)
            user.save()
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.role, profile.phone = role, f"+974 5550 {len(users):04d}"
            profile.accepts_leads = role == Profile.EXECUTIVE
            profile.team = teams.setdefault(team, Team.objects.get_or_create(name=team)[0]) if team else None
            profile.save()
            users[username] = user
        Team.objects.filter(name="Team Lusail").update(leader=users["arun"])
        Team.objects.filter(name="Team West Bay").update(leader=users["sneha"])
        return users

    def _projects(self, users):
        out = []
        for name, location, types, pfrom, pto, team in PROJECTS:
            project, _ = Project.objects.update_or_create(name=name, defaults={
                "location": location, "property_types": types, "price_from": pfrom, "price_to": pto,
                "brochure_url": f"https://{settings.COMPANY_WEBSITE}/{name.split()[1].lower()}.pdf", "is_active": True,
            })
            for username, *_r, member_team, _s in STAFF:
                if member_team == team and username in users:
                    users[username].profile.projects.add(project)
            out.append(project)
        return out

    def _act(self, lead, kind, at, by, note="", outcome=""):
        if at <= self.now:
            Activity.objects.create(lead=lead, kind=kind, note=note, outcome=outcome, created_by=by, created_at=at)

    def _lead(self, i, row, users, projects):
        (name, dial, number, country, city, area, source, proj, ptype, budget, stage, temp, _lang, days, owner_name,
         lost_reason) = row
        now, owner = self.now, users[owner_name]
        project = projects[proj] if proj is not None else None
        source, _, source_other = source.partition(":")
        created = now - timedelta(days=days, hours=2 + i % 5) if days else now - timedelta(minutes=50 + i * 17)
        rank = LOST_AT_RANK[lost_reason] if stage == Lead.LOST else Lead.STAGE_RANK[stage]
        speed = next(s[5] for s in STAFF if s[0] == owner_name)
        span = max((now - created) * 0.85, timedelta(hours=1))
        step_at = {r: created + span * r / 7 for r in range(1, 7)}
        step_at[1] = created + timedelta(minutes=speed + i % 7)

        lead = Lead.objects.create(
            name=name, phone_code=dial, phone=number, country=country, city=city, area=area,
            email=f"{name.split()[0].lower()}.{i}@example.com" if i % 3 else "", budget_amount=Decimal(budget),
            property_type=ptype, project=project, source=source, source_other=source_other, owner=owner, language="en", temperature=temp,
            created_at=created, last_enquiry_at=created, stage_changed_at=created, notes=NOTES[i % len(NOTES)],
        )
        Activity.objects.create(lead=lead, kind="system", created_at=created, note=f"Lead created via {lead.get_source_display()}")
        Assignment.objects.create(lead=lead, to_user=owner, reason="Round-robin", created_at=created)
        Activity.objects.create(lead=lead, kind="system", created_at=created + timedelta(seconds=5),
                                note=f"Assigned to {owner.get_full_name()} by Auto-assignment - Round-robin")
        Notification.objects.create(user=owner, text=f"New lead assigned: {name} ({lead.get_source_display()})",
                                    url=f"/leads/{lead.pk}/", created_at=created, is_read=rank > 0)

        labels = dict(Lead.STAGES)
        order = [Lead.NEW, Lead.CONTACTED, Lead.INTERESTED, Lead.SV_SCHEDULED, Lead.SV_DONE, Lead.NEGOTIATION, Lead.BOOKED]
        if rank >= 1:
            lead.first_response_at = step_at[1]
            self._act(lead, "call", step_at[1], owner, NOTES[(i + 1) % len(NOTES)], "connected")
            self._act(lead, "whatsapp", step_at[1] + timedelta(minutes=6), owner,
                      f"WhatsApp sent: First response (EN)")
        elif stage == Lead.LOST:
            for k in range(3):
                self._act(lead, "call", created + timedelta(days=k + 1), owner, "", "no_answer")
        for r in range(1, rank + 1):
            self._act(lead, "system", step_at[r], owner, f"Stage changed: {labels[order[r - 1]]} → {labels[order[r]]}")

        last = step_at.get(rank, created)
        if rank >= 3 and project:
            done = rank >= 4
            visit_at = step_at[4] if done else (now + timedelta(days=1 + i % 3)).replace(hour=11 + i % 5, minute=0)
            status = SiteVisit.DONE if done else (SiteVisit.NO_SHOW if stage == Lead.LOST else SiteVisit.SCHEDULED)
            if status == SiteVisit.NO_SHOW:
                visit_at = step_at[3] + timedelta(days=2)
            SiteVisit.objects.create(
                lead=lead, project=project, scheduled_at=visit_at, executive=owner, status=status,
                feedback="Liked the layout and community amenities" if done else "",
                completed_at=visit_at + timedelta(hours=1) if status != SiteVisit.SCHEDULED else None,
                created_by=owner, created_at=step_at[3],
            )
            if done:
                self._act(lead, "site_visit", visit_at + timedelta(hours=1), owner, f"Site visit done at {project}.")
            elif status == SiteVisit.SCHEDULED:
                lead.next_followup = visit_at - timedelta(hours=3)

        if stage == Lead.BOOKED:
            value = Decimal(budget)
            Booking.objects.create(
                lead=lead, project=project, unit_no=f"{'ABCT'[i % 4]}-{10 + i}{i % 4 + 1:02d}", deal_value=value,
                booking_amount=(value * Decimal("0.10")).quantize(Decimal("1000")),
                booking_date=timezone.localtime(step_at[6]).date(), executive=owner, created_at=step_at[6],
            )
            AuditLog.objects.create(user=owner, action="booking", object_type="Booking", created_at=step_at[6],
                                    summary=f"{name} booked {project}")
        elif stage == Lead.LOST:
            last = min(now, last + timedelta(days=4))
            lead.lost_reason = lost_reason
            self._act(lead, "system", last, owner, f"Stage changed: → Lost ({dict(Lead.LOST_REASONS)[lost_reason]})")
        elif rank == 0:
            lead.next_followup = created + timedelta(minutes=30)
        elif not lead.next_followup:
            lead.next_followup = now + timedelta(hours=(i % 5 - 1) * 20)

        lead.stage, lead.max_stage_rank, lead.stage_changed_at = stage, rank, last
        lead.save()

    def _spend_and_targets(self, users):
        month = month_start(timezone.localdate())
        for _ in range(3):
            for source, amount in AD_SPEND.items():
                AdSpend.objects.update_or_create(month=month, source=source, defaults={"amount": Decimal(amount)})
            AdSpend.objects.update_or_create(month=month, source="other", custom_source="LinkedIn",
                                             defaults={"amount": Decimal(4000)})
            for s in STAFF:
                if s[3] == Profile.EXECUTIVE:
                    Target.objects.update_or_create(user=users[s[0]], month=month,
                                                    defaults={"site_visits": 4, "bookings": 1})
            month = month_start(month - timedelta(days=1))
