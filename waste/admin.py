from django.contrib import admin
from .models import Collection, Complaint, Profile, Accomplishment, ActionPlan


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ("id", "barangay", "waste_type", "status", "scheduled_date", "weight_kg", "collector", "date_collected")
    list_filter = ("barangay", "waste_type")
    search_fields = ("collector",)


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ("id", "barangay", "resident_name", "status", "date_filed")
    list_filter = ("barangay", "status")
    search_fields = ("resident_name", "issue")


@admin.register(Accomplishment)
class AccomplishmentAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "barangay", "date_accomplished", "logged_by", "due_date", "submission_date")
    list_filter = ("barangay",)
    search_fields = ("title", "description")


@admin.register(ActionPlan)
class ActionPlanAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "barangay", "status", "target_date", "responsible_person", "submission_date")
    list_filter = ("barangay", "status")
    search_fields = ("title", "description", "responsible_person")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "barangay")
    list_filter = ("role", "barangay")