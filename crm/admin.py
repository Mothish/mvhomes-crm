from django.contrib import admin

from .models import Activity, AdSpend, Assignment, AuditLog, Booking, Lead, Profile, Project, SiteVisit, Target, Team

for model in (Activity, AdSpend, Assignment, AuditLog, Booking, Profile, Project, SiteVisit, Target, Team):
    admin.site.register(model)


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "source", "stage", "owner", "created_at")
    list_filter = ("stage", "source")
    search_fields = ("name", "phone")
