import json

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.urls import path, reverse
from django.utils import timezone

from apps.scouting.models import Event, Mission, Patrol, PatrolMatch, Submission


def _parse_submission_payload(payload: str) -> dict | None:
    try:
        parsed = json.loads(payload)
        return parsed if isinstance(parsed, dict) else None
    except (TypeError, json.JSONDecodeError):
        return None


def _is_ai_flagged_submission(submission: Submission) -> bool:
    parsed = _parse_submission_payload(submission.payload)
    if parsed is None:
        return False

    direct_flag = parsed.get("flagged")
    if isinstance(direct_flag, bool):
        return direct_flag

    validator_result = parsed.get("validation")
    if isinstance(validator_result, dict):
        nested_flag = validator_result.get("flagged")
        if isinstance(nested_flag, bool):
            return nested_flag

    return False


def _build_security_alert_rows(limit: int = 25) -> list[dict]:
    rows: list[dict] = []
    submissions = Submission.objects.select_related("mission__event", "patrol").order_by("-submitted_at")

    for submission in submissions:
        if not _is_ai_flagged_submission(submission):
            continue

        parsed = _parse_submission_payload(submission.payload) or {}
        reason = parsed.get("reason") or parsed.get("encouragement_message") or "Sin detalle de IA"
        rows.append(
            {
                "id": submission.id,
                "event_name": submission.mission.event.name,
                "mission_title": submission.mission.title,
                "patrol_name": submission.patrol.name,
                "submitted_by": submission.submitted_by,
                "submitted_at": timezone.localtime(submission.submitted_at).strftime("%d/%m/%Y %H:%M"),
                "reason": str(reason)[:120],
                "change_url": reverse("admin:scouting_submission_change", args=[submission.id]),
            }
        )

        if len(rows) >= limit:
            break

    return rows


def _build_traffic_chart_payload() -> dict:
    labels: list[str] = []
    registered_series: list[int] = []
    matched_series: list[int] = []

    events = Event.objects.order_by("starts_at", "name")
    for event in events:
        labels.append(event.name)
        registered_count = Patrol.objects.filter(event=event).count()

        matched_ids: set[int] = set()
        for patrol_a_id, patrol_b_id in PatrolMatch.objects.filter(event=event).values_list(
            "patrol_a_id", "patrol_b_id"
        ):
            matched_ids.add(patrol_a_id)
            matched_ids.add(patrol_b_id)

        registered_series.append(registered_count)
        matched_series.append(len(matched_ids))

    if not labels:
        labels = ["Global"]
        registered_series = [0]
        matched_series = [0]

    return {
        "labels": labels,
        "registered": registered_series,
        "matched": matched_series,
    }


def admin_traffic_chart_data(_request: HttpRequest) -> JsonResponse:
    return JsonResponse(_build_traffic_chart_payload())


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


def _patch_admin_index() -> None:
    if getattr(admin.site, "_ligilo_dashboard_patched", False):
        return

    original_each_context = admin.site.each_context
    original_get_urls = admin.site.get_urls

    def ligilo_each_context(request: HttpRequest) -> dict:
        context = original_each_context(request)
        alerts = _build_security_alert_rows(limit=25)
        context.update(
            {
                "scouting_traffic_chart_url": reverse("admin:scouting_traffic_data"),
                "scouting_security_alerts": alerts,
                "scouting_security_alert_total": len(alerts),
            }
        )
        return context

    def ligilo_get_urls():
        extra_urls = [
            path(
                "analytics/traffic-chart-data/",
                admin.site.admin_view(admin_traffic_chart_data),
                name="scouting_traffic_data",
            )
        ]
        return extra_urls + original_get_urls()

    admin.site.each_context = ligilo_each_context
    admin.site.get_urls = ligilo_get_urls
    admin.site.index_template = "admin/index.html"
    admin.site._ligilo_dashboard_patched = True


_patch_admin_index()


admin.site.site_header = "SEL Ligilo Admin"
admin.site.site_title = "SEL Ligilo"
admin.site.index_title = "Gestion de delegaciones y matches"
