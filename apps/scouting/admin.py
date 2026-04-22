import json
import csv
import uuid
import io
from datetime import timedelta

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Sum
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import path, reverse
from django.utils import timezone

import qrcode

from apps.scouting.models import (
    AuditLog,
    Event,
    MatchCelebrationEvent,
    MCERCertificate,
    Mission,
    Payment,
    Patrol,
    PatrolInterest,
    PatrolMember,
    PatrolMatch,
    PatrolYouTubeSubmission,
    PointLog,
    RoverIncident,
    SteloCertification,
    Submission,
)


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


def _build_global_ranking_payload(event_id: int | None = None, limit: int = 20) -> list[dict]:
    """Top patrols by SEL points, optionally filtered by event."""
    qs = Patrol.objects.select_related("event").filter(is_active=True)
    if event_id:
        qs = qs.filter(event_id=event_id)
    qs = qs.order_by("-sel_points")[:limit]

    recent_window = timezone.now() - timedelta(days=7)
    ranking = []
    for rank, patrol in enumerate(qs, start=1):
        weekly_pts = (
            PointLog.objects.filter(patrol=patrol, created_at__gte=recent_window)
            .aggregate(total=Sum("points"))
            .get("total") or 0
        )
        ranking.append(
            {
                "rank": rank,
                "patrol_id": patrol.id,
                "patrol_name": patrol.name,
                "delegation_name": patrol.delegation_name,
                "country_name": patrol.country_name,
                "country_code": patrol.country_code,
                "language": patrol.official_language_name,
                "event_name": patrol.event.name,
                "sel_points": patrol.sel_points,
                "weekly_points": weekly_pts,
                "change_url": reverse("admin:scouting_patrol_change", args=[patrol.id]),
            }
        )
    return ranking


def admin_global_ranking_data(request: HttpRequest) -> JsonResponse:
    try:
        event_id = int(request.GET["event_id"]) if "event_id" in request.GET else None
    except (TypeError, ValueError):
        event_id = None
    return JsonResponse({"ranking": _build_global_ranking_payload(event_id=event_id)})


def _build_weekly_report_payload(patrol_id: int) -> dict:
    """Build the weekly learning report for a patrol (admin preview endpoint)."""
    patrol = Patrol.objects.filter(id=patrol_id).first()
    if patrol is None:
        return {"error": "patrol_not_found"}

    week_start = timezone.now() - timedelta(days=7)
    logs = PointLog.objects.filter(patrol=patrol, created_at__gte=week_start)

    texts = logs.filter(event_type=PointLog.EventType.TEXT_VALIDATED).count()
    audios = logs.filter(event_type=PointLog.EventType.AUDIO_VALIDATED).count()
    youtube = logs.filter(event_type=PointLog.EventType.YOUTUBE_MISSION).count()
    bonuses = logs.filter(event_type=PointLog.EventType.CONSISTENCY_BONUS).count()
    weekly_points = logs.aggregate(total=Sum("points")).get("total") or 0
    estimated_words = (texts * 1) + (audios * 3) + (youtube * 5)

    return {
        "patrol_id": patrol.id,
        "patrol_name": patrol.name,
        "delegation_name": patrol.delegation_name,
        "leader_name": patrol.leader_name,
        "period_start": week_start.strftime("%d/%m/%Y"),
        "period_end": timezone.now().strftime("%d/%m/%Y"),
        "texts_validated": texts,
        "audios_validated": audios,
        "youtube_missions": youtube,
        "consistency_bonuses": bonuses,
        "weekly_points": weekly_points,
        "total_sel_points": patrol.sel_points,
        "estimated_words_learned": estimated_words,
        "summary_message": (
            f"Tu patrulla ha aprendido {estimated_words} palabras nuevas esta semana. "
            f"Enviaste {texts} frases, {audios} audios y completaste {youtube} misiones YouTube. "
            f"Ganaron {weekly_points} puntos SEL esta semana."
        ),
    }


def admin_weekly_report_data(_request: HttpRequest, patrol_id: int) -> JsonResponse:
    return JsonResponse(_build_weekly_report_payload(patrol_id))


def _build_funds_summary() -> dict:
    completed = Payment.objects.filter(status=Payment.Status.COMPLETED)
    total_cents = completed.aggregate(total=Sum("amount_cents")).get("total") or 0
    paid_patrols = completed.values("patrol_id").distinct().count()
    total_payments = completed.count()
    return {
        "total_cents": total_cents,
        "total_usd": total_cents / 100,
        "paid_patrols": paid_patrols,
        "total_payments": total_payments,
    }


def admin_funds_report_csv(_request: HttpRequest) -> HttpResponse:
    """
    Downloadable cierre de caja report for SEL accounting.
    """
    completed = (
        Payment.objects.filter(status=Payment.Status.COMPLETED)
        .select_related("patrol", "patrol__event")
        .order_by("-completed_at", "-created_at")
    )
    summary = _build_funds_summary()

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    timestamp = timezone.localtime().strftime("%Y%m%d_%H%M")
    response["Content-Disposition"] = f'attachment; filename="fondos_recaudados_{timestamp}.csv"'

    writer = csv.writer(response)
    writer.writerow(["Reporte", "Fondos Recaudados (SEL)"])
    writer.writerow(["Generado", timezone.localtime().strftime("%d/%m/%Y %H:%M")])
    writer.writerow(["Total USD", f"{summary['total_usd']:.2f}"])
    writer.writerow(["Pagos completados", summary["total_payments"]])
    writer.writerow(["Patrullas pagadas", summary["paid_patrols"]])
    writer.writerow([])
    writer.writerow(
        [
            "payment_id",
            "completed_at",
            "event",
            "delegacion",
            "patrulla",
            "producto",
            "metodo",
            "estado",
            "monto_usd",
            "currency",
            "stripe_id",
            "paypal_id",
        ]
    )

    for payment in completed:
        completed_at = payment.completed_at or payment.updated_at or payment.created_at
        writer.writerow(
            [
                payment.id,
                timezone.localtime(completed_at).strftime("%d/%m/%Y %H:%M"),
                payment.patrol.event.name,
                payment.patrol.delegation_name,
                payment.patrol.name,
                payment.product_type,
                payment.payment_method,
                payment.status,
                f"{payment.amount_cents / 100:.2f}",
                payment.currency,
                payment.stripe_payment_intent_id,
                payment.paypal_transaction_id,
            ]
        )

    return response


def _build_paid_patch_rows(request: HttpRequest) -> list[dict]:
    payments = (
        Payment.objects.filter(
            status=Payment.Status.COMPLETED,
            product_type=Payment.ProductType.STELO_PASS,
        )
        .select_related("patrol", "patrol__event")
        .order_by("patrol__delegation_name", "patrol__name")
    )

    rows = []
    seen_patrols: set[int] = set()
    for payment in payments:
        if payment.patrol_id in seen_patrols:
            continue
        seen_patrols.add(payment.patrol_id)

        cert = SteloCertification.objects.filter(patrol_id=payment.patrol_id, revoked=False).first()
        if cert:
            qr_url = request.build_absolute_uri(
                reverse("dashboard:stelo-achievement-profile", args=[payment.patrol_id])
            )
            if cert.jwt_token:
                qr_url = f"{qr_url}?token={cert.jwt_token}"
            cert_code = cert.certification_code
        else:
            qr_url = request.build_absolute_uri(
                reverse("dashboard:stelo-achievement-profile", args=[payment.patrol_id])
            )
            cert_code = "PENDIENTE_CERTIFICACION"

        rows.append(
            {
                "event": payment.patrol.event.name,
                "delegation": payment.patrol.delegation_name,
                "patrol": payment.patrol.name,
                "leader": payment.patrol.leader_name,
                "cert_code": cert_code,
                "qr_url": qr_url,
            }
        )
    return rows


def admin_paid_patrols_logistics_pdf(request: HttpRequest) -> HttpResponse:
    """
    PDF list for physical SEL stand logistics with paid patrols and QR per patrol.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas
    except Exception:
        return HttpResponse(
            "No se pudo generar el PDF: falta la dependencia reportlab. "
            "Instala requirements.txt en este entorno.",
            status=503,
            content_type="text/plain; charset=utf-8",
        )

    rows = _build_paid_patch_rows(request)

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 45
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, "SEL - Lista de Entrega de Parches (Patrullas Pagadas)")
    y -= 18
    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, y, f"Generado: {timezone.localtime().strftime('%d/%m/%Y %H:%M')}")
    y -= 22

    if not rows:
        pdf.setFont("Helvetica", 11)
        pdf.drawString(40, y, "No hay patrullas pagadas con Stelo Pass para listar.")
        pdf.showPage()
        pdf.save()
        buffer.seek(0)
        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="lista_entrega_parches.pdf"'
        return response

    for idx, row in enumerate(rows, start=1):
        if y < 130:
            pdf.showPage()
            y = height - 45

        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(40, y, f"{idx}. {row['delegation']} / {row['patrol']}")
        y -= 13
        pdf.setFont("Helvetica", 9)
        pdf.drawString(48, y, f"Evento: {row['event']}")
        y -= 12
        pdf.drawString(48, y, f"Lider responsable: {row['leader']}")
        y -= 12
        pdf.drawString(48, y, f"Codigo certificacion: {row['cert_code']}")

        qr_img = qrcode.make(row["qr_url"])
        qr_reader = ImageReader(qr_img)
        pdf.drawImage(qr_reader, width - 125, y - 10, width=75, height=75, mask="auto")

        y -= 20
        pdf.setFont("Helvetica-Oblique", 8)
        pdf.drawString(48, y, row["qr_url"][:110])
        y -= 30
        pdf.line(40, y, width - 40, y)
        y -= 16

    pdf.save()
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    timestamp = timezone.localtime().strftime("%Y%m%d_%H%M")
    response["Content-Disposition"] = f'attachment; filename="lista_entrega_parches_{timestamp}.pdf"'
    return response


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
        patrol.invitation_token = uuid.uuid4()
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
        "training_points",
        "sel_points",
        "stelo_meter_tier",
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

    @admin.display(description="Stelo-Meter")
    def stelo_meter_tier(self, obj: Patrol) -> str:
        try:
            cert = obj.stelo_certification
            if cert.revoked:
                return "—"
            icons = {"bronze": "🥉 Bronce", "silver": "🥈 Plata", "gold": "🥇 Oro"}
            return icons.get(cert.tier, cert.tier)
        except Patrol.stelo_certification.RelatedObjectDoesNotExist:
            from apps.scouting.models import SteloCertification
            tier = SteloCertification.tier_for_points(obj.sel_points)
            if tier is None:
                return f"— ({obj.sel_points} pts)"
            return f"⏳ pendiente {tier}"


@admin.register(PatrolMember)
class PatrolMemberAdmin(admin.ModelAdmin):
    list_display = (
        "patrol",
        "full_name",
        "alias",
        "gender",
        "birth_date",
        "initial_level",
        "joined_node_at",
    )
    list_filter = ("gender", "initial_level", "joined_node_at")
    search_fields = ("patrol__name", "patrol__delegation_name", "full_name", "alias")
    readonly_fields = ("created_at", "updated_at")


@admin.register(PatrolInterest)
class PatrolInterestAdmin(admin.ModelAdmin):
    list_display = ("patrol", "tag")
    search_fields = ("patrol__name", "patrol__delegation_name", "tag")


@admin.register(PatrolMatch)
class PatrolMatchAdmin(admin.ModelAdmin):
    list_display = ("event", "patrol_a", "patrol_b", "status", "is_training", "matched_at")
    list_filter = ("event", "status", "is_training")
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


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "user_identifier", "flagged_status")
    list_filter = ("flagged_status", "timestamp")
    search_fields = ("user_identifier", "input_text")
    readonly_fields = ("timestamp", "user", "user_identifier", "input_text", "ai_response", "flagged_status")


@admin.register(MatchCelebrationEvent)
class MatchCelebrationEventAdmin(admin.ModelAdmin):
    list_display = (
        "sent_at",
        "event_name",
        "patrol_match",
        "patrol",
        "telegram_chat_id",
        "first_interaction_at",
        "first_interaction_seconds",
    )
    list_filter = ("event_name", "sent_at", "first_interaction_at")
    search_fields = ("patrol__name", "patrol__delegation_name")
    readonly_fields = (
        "event_name",
        "patrol_match",
        "patrol",
        "telegram_chat_id",
        "sent_at",
        "first_interaction_at",
        "first_interaction_seconds",
    )


@admin.register(PointLog)
class PointLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "patrol", "event_type", "points", "external_ref")
    list_filter = ("event_type", "created_at")
    search_fields = ("patrol__name", "patrol__delegation_name", "external_ref")
    readonly_fields = ("created_at", "patrol", "event_type", "points", "external_ref", "metadata")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "patrol",
        "product_type",
        "amount_display",
        "status",
        "payment_method",
    )
    list_filter = ("status", "payment_method", "product_type", "created_at")
    search_fields = (
        "patrol__name",
        "patrol__delegation_name",
        "stripe_payment_intent_id",
        "paypal_transaction_id",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "completed_at",
        "stripe_payment_intent_id",
        "paypal_transaction_id",
    )

    fieldsets = (
        (
            "Información de Patrulla",
            {"fields": ("patrol",)},
        ),
        (
            "Detalles de Producto",
            {"fields": ("product_type", "amount_cents", "currency")},
        ),
        (
            "Estado de Pago",
            {"fields": ("status", "payment_method", "completed_at", "error_message")},
        ),
        (
            "Referencias de Proveedor",
            {"fields": ("stripe_payment_intent_id", "paypal_transaction_id")},
        ),
        (
            "Metadata",
            {"fields": ("metadata",), "classes": ("collapse",)},
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    def amount_display(self, obj: Payment) -> str:
        return f"${obj.amount_cents / 100:.2f} {obj.currency}"
    amount_display.short_description = "Monto"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False


@admin.register(SteloCertification)
class SteloCertificationAdmin(admin.ModelAdmin):
    list_display = (
        "issued_at",
        "patrol",
        "tier",
        "points_at_issue",
        "certification_code",
        "revoked",
        "expires_at",
    )
    list_filter = ("tier", "revoked", "issued_at")
    search_fields = ("patrol__name", "patrol__delegation_name", "certification_code")
    readonly_fields = (
        "issued_at",
        "patrol",
        "tier",
        "points_at_issue",
        "certification_code",
        "jwt_token",
        "qr_png_b64",
        "expires_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False


@admin.register(PatrolYouTubeSubmission)
class PatrolYouTubeSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "submitted_at",
        "patrol",
        "video_id",
        "validation_status",
        "audit_status",
        "leader_approval_status",
        "approved_for_wall_of_fame",
    )
    list_filter = (
        "validation_status",
        "audit_status",
        "leader_approval_status",
        "approved_for_wall_of_fame",
        "submitted_at",
    )
    search_fields = (
        "patrol__name",
        "patrol__delegation_name",
        "video_id",
        "youtube_url",
    )
    readonly_fields = (
        "submitted_at",
        "validated_at",
        "audited_at",
        "leader_notification_sent_at",
        "leader_approved_at",
        "final_approved_at",
    )


@admin.register(RoverIncident)
class RoverIncidentAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "patrol",
        "priority",
        "status",
        "reported_by_chat_id",
    )
    list_filter = ("status", "priority", "created_at")
    search_fields = ("patrol__name", "patrol__delegation_name", "description")
    readonly_fields = ("created_at", "reported_by_chat_id")


@admin.register(MCERCertificate)
class MCERCertificateAdmin(admin.ModelAdmin):
    list_display = (
        "issued_at",
        "patrol",
        "sister_patrol",
        "mcer_level",
        "points_at_issue",
        "certification_code",
        "preview_requested_count",
    )
    list_filter = ("mcer_level", "issued_at")
    search_fields = (
        "patrol__name",
        "patrol__delegation_name",
        "certification_code",
        "sister_patrol__name",
    )
    readonly_fields = (
        "issued_at",
        "certification_code",
        "qr_png_b64",
        "preview_requested_count",
        "last_preview_requested_at",
        "leader_notified_at",
    )
    autocomplete_fields = ["patrol", "sister_patrol"]
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("patrol", "sister_patrol")


def _patch_admin_index() -> None:
    if getattr(admin.site, "_ligilo_dashboard_patched", False):
        return

    original_each_context = admin.site.each_context
    original_get_urls = admin.site.get_urls

    def ligilo_each_context(request: HttpRequest) -> dict:
        context = original_each_context(request)
        alerts = _build_security_alert_rows(limit=25)
        ranking = _build_global_ranking_payload(limit=20)
        funds = _build_funds_summary()
        context.update(
            {
                "scouting_traffic_chart_url": reverse("admin:scouting_traffic_data"),
                "scouting_global_ranking_url": reverse("admin:scouting_global_ranking"),
                "scouting_global_ranking": ranking,
                "scouting_security_alerts": alerts,
                "scouting_security_alert_total": len(alerts),
                "scouting_funds_report_url": reverse("admin:scouting_funds_report"),
                "scouting_paid_patches_pdf_url": reverse("admin:scouting_paid_patches_pdf"),
                "scouting_funds_total_usd": f"{funds['total_usd']:.2f}",
                "scouting_funds_total_payments": funds["total_payments"],
                "scouting_funds_total_patrols": funds["paid_patrols"],
            }
        )
        return context

    def ligilo_get_urls():
        extra_urls = [
            path(
                "analytics/traffic-chart-data/",
                admin.site.admin_view(admin_traffic_chart_data),
                name="scouting_traffic_data",
            ),
            path(
                "analytics/global-ranking/",
                admin.site.admin_view(admin_global_ranking_data),
                name="scouting_global_ranking",
            ),
            path(
                "analytics/weekly-report/<int:patrol_id>/",
                admin.site.admin_view(admin_weekly_report_data),
                name="scouting_weekly_report",
            ),
            path(
                "analytics/funds-report/",
                admin.site.admin_view(admin_funds_report_csv),
                name="scouting_funds_report",
            ),
            path(
                "analytics/paid-patrols-logistics-pdf/",
                admin.site.admin_view(admin_paid_patrols_logistics_pdf),
                name="scouting_paid_patches_pdf",
            ),
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
