# eventapp/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import School, RegisterCounter, Application, Programme, Banner


# ---------- School ----------
@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


# ---------- RegisterCounter ----------
@admin.register(RegisterCounter)
class RegisterCounterAdmin(admin.ModelAdmin):
    list_display = ("prefix", "current")
    search_fields = ("prefix",)
    list_editable = ("current",)


# ---------- Programme ----------
@admin.register(Programme)
class ProgrammeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "team_min",
        "team_max",
        "expiry_date",
        "is_active",
        "order",
        "card_image",
    )
    list_filter = ("category", "is_active")
    search_fields = ("name", "description")
    ordering = ("order", "id")
    list_editable = ("is_active", "order")
    readonly_fields = ("card_image",)

    fieldsets = (
        ("Basic info", {
            "fields": ("category", "name", "description"),
        }),
        ("Display", {
            "fields": ("image", "card_image", "order", "is_active"),
        }),
        ("Application rules", {
            "fields": ("team_min", "team_max", "expiry_date"),
            "description": "Applicants range used by the Apply modal (min..max).",
        }),
    )

    @admin.display(description="Image", ordering="image")
    def card_image(self, obj):
        if getattr(obj, "image", None):
            return format_html(
                '<img src="{}" style="height:48px;border-radius:6px;" />',
                obj.image.url,
            )
        return "—"


# ---------- Application ----------
@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "register_no",
        "program_name",
        "school",
        "name",
        "mobile",
        "team_size",
        "is_winner",
        "winner_rank",
        "submitted_at",
    )
    list_filter = (
        "program_name",
        "team_size",
        "is_winner",
        "winner_rank",
        "submitted_at",
    )
    search_fields = (
        "register_no",
        "name",
        "mobile",
        "program_name",
        "school__name",
    )
    readonly_fields = ("register_no", "submitted_at", "members")
    ordering = ("-submitted_at",)

    fieldsets = (
        ("Registration", {
            "fields": ("register_no", "submitted_at"),
        }),
        ("Programme", {
            "fields": ("program_name", "team_size", "school"),
        }),
        ("Primary member (mirrored)", {
            "fields": ("name", "mobile"),
        }),
        ("All members (JSON)", {
            "fields": ("members",),
        }),
        ("Winner", {
            "fields": ("is_winner", "winner_rank", "winner_note"),
        }),
    )

    # Quick actions for winners
    @admin.action(description="Mark selected as winners")
    def make_winner(self, request, queryset):
        queryset.update(is_winner=True)

    @admin.action(description="Clear winner status")
    def clear_winner(self, request, queryset):
        queryset.update(is_winner=False, winner_rank=None)

    actions = ["make_winner", "clear_winner"]


# ---------- Banner ----------
@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ("title", "order", "is_active", "height_px", "preview")
    list_editable = ("order", "is_active", "height_px")
    list_filter = ("is_active",)
    search_fields = ("title",)
    ordering = ("order", "id")
    readonly_fields = ("preview",)

    fields = (
        "title", "subtitle", "image", "preview",
        "link_url", "height_px", "order", "is_active",
    )

    @admin.display(description="Preview", ordering="image")
    def preview(self, obj):
        if getattr(obj, "image", None):
            return format_html(
                '<img src="{}" style="height:60px;border-radius:6px;" />',
                obj.image.url,
            )
        return "—"
