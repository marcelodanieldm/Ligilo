from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from apps.scouting.models import Event, Mission, Patrol, PatrolMatch, Submission


class MissionInline(admin.TabularInline):
    model = Mission
    extra = 0


class SubmissionInline(admin.TabularInline):
    model = Submission
    extra = 0


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("name", "host_city", "host_country", "starts_at", "ends_at", "is_active")
    list_filter = ("is_active", "host_country")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "host_city", "host_country")


@admin.action(description="Crear match valido entre patrullas seleccionadas")
def create_valid_match(modeladmin, request, queryset):
    patrols = list(queryset.select_related("event").order_by("event_id", "delegation_name", "name"))
    created = 0
    for index, patrol_a in enumerate(patrols):
        for patrol_b in patrols[index + 1 :]:
            if patrol_a.event_id != patrol_b.event_id:
                continue
            if patrol_a.official_language_code.lower() == patrol_b.official_language_code.lower():
                continue
            if PatrolMatch.objects.filter(
                event_id=patrol_a.event_id,
                patrol_a=patrol_a,
                patrol_b=patrol_b,
            ).exists() or PatrolMatch.objects.filter(
                event_id=patrol_a.event_id,
                patrol_a=patrol_b,
                patrol_b=patrol_a,
            ).exists():
                continue
            match = PatrolMatch(event=patrol_a.event, patrol_a=patrol_a, patrol_b=patrol_b)
            try:
                match.full_clean()
                match.save()
                created += 1
            except ValidationError:
                continue
            break
    messages.success(request, f"Se crearon {created} matches validos.")


@admin.action(description="Regenerar token de invitacion")
def regenerate_invitation_token(modeladmin, request, queryset):
    updated = 0
    for patrol in queryset:
        patrol.invitation_token = None
        patrol.save(update_fields=["invitation_token", "updated_at"])
        updated += 1
    messages.success(request, f"Se regeneraron {updated} tokens de invitacion.")


@admin.register(Patrol)
class PatrolAdmin(admin.ModelAdmin):
    list_display = (
        "delegation_name",
        "name",
        "event",
        "country_name",
        "official_language_name",
        "telegram_chat_id",
        "invitation_token",
        "leader_name",
        "is_active",
    )
    list_filter = ("event", "country_name", "official_language_name", "is_active", "telegram_chat_id")
    search_fields = (
        "delegation_name",
        "name",
        "country_name",
        "official_language_name",
        "leader_name",
        "invitation_token",
    )
    actions = (create_valid_match, regenerate_invitation_token)


@admin.register(PatrolMatch)
class PatrolMatchAdmin(admin.ModelAdmin):
    list_display = ("event", "patrol_a", "patrol_b", "status", "matched_at")
    list_filter = ("event", "status")
    search_fields = ("patrol_a__delegation_name", "patrol_b__delegation_name")
    inlines = (MissionInline,)


@admin.register(Mission)
class MissionAdmin(admin.ModelAdmin):
    list_display = ("title", "event", "patrol_match", "status", "opens_at", "due_at")
    list_filter = ("event", "status")
    search_fields = ("title", "briefing")
    inlines = (SubmissionInline,)


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("mission", "patrol", "submitted_by", "status", "submitted_at")
    list_filter = ("status", "submitted_at", "patrol__event")
    search_fields = ("mission__title", "patrol__delegation_name", "submitted_by")


admin.site.site_header = "SEL Ligilo Admin"
admin.site.site_title = "SEL Ligilo"
admin.site.index_title = "Gestion de delegaciones y matches"
