import io
from datetime import timedelta
from urllib.parse import urlencode
from uuid import UUID

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import models
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.urls import reverse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.text import slugify

from apps.dashboard.controllers.leader_dashboard_controller import LeaderDashboardController
from apps.scouting.forms import PatrolMemberFormSet, PatrolOnboardingStepAForm
from apps.scouting.models import (
    MatchCelebrationEvent,
    Patrol,
    PatrolInterest,
    PatrolMember,
    PatrolYouTubeSubmission,
    PointLog,
    SteloCertification,
    Submission,
)
from apps.scouting.services.poentaro_engine import PoentaroEngine
from apps.scouting.services.certification import check_and_issue_certification, verify_certification_token
from fastapi_app.services.telegram_manager import TelegramManager


User = get_user_model()


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def landing_page(request: HttpRequest) -> HttpResponse:
    return render(request, "ligilo/landing_page.html")


def _build_simple_pdf(lines: list[str]) -> bytes:
    encoded_lines = [line.encode("latin-1", errors="replace").decode("latin-1") for line in lines]

    content_ops = [
        "BT",
        "/F1 13 Tf",
        "48 790 Td",
        "18 TL",
    ]
    for index, line in enumerate(encoded_lines):
        content_ops.append(f"({_pdf_escape(line)}) Tj")
        if index < len(encoded_lines) - 1:
            content_ops.append("T*")
    content_ops.append("ET")

    stream_content = "\n".join(content_ops).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream_content)).encode("ascii") + b" >>\nstream\n"
        + stream_content
        + b"\nendstream",
    ]

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{index} 0 obj\n".encode("ascii"))
        out.write(obj)
        out.write(b"\nendobj\n")

    xref_pos = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.write(f"{offset:010d} 00000 n \n".encode("ascii"))

    out.write(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF"
        ).encode("ascii")
    )

    return out.getvalue()


@login_required
def leader_dashboard(request: HttpRequest) -> HttpResponse:
    controller = LeaderDashboardController(user=request.user)
    return render(request, "ligilo/leader_dashboard.html", controller.get_context())


@login_required
def leader_onboarding(request: HttpRequest) -> HttpResponse:
    patrol_rows = (
        Patrol.objects.select_related("event")
        .order_by("-updated_at", "name")[:8]
    )

    onboarding_rows = []
    for patrol in patrol_rows:
        step_label = {
            0: "Paso A",
            1: "Paso B",
            2: "Paso C",
        }.get(patrol.onboarding_step, "Operativa")

        step_a_url = ""
        if patrol.invitation_token:
            step_a_url = request.build_absolute_uri(
                reverse("dashboard:patrol-onboarding-step-a", args=[patrol.invitation_token])
            )

        onboarding_rows.append(
            {
                "name": patrol.name,
                "event_name": patrol.event.name,
                "delegation": patrol.delegation_name,
                "token": str(patrol.invitation_token) if patrol.invitation_token else "",
                "step": step_label,
                "step_a_url": step_a_url,
            }
        )

    context = {
        "leader_display_name": request.user.get_full_name() or request.user.get_username(),
        "leader_email": request.user.email,
        "onboarding_rows": onboarding_rows,
    }
    return render(request, "ligilo/leader_onboarding.html", context)


@login_required
def admin_operations_dashboard(request: HttpRequest) -> HttpResponse:
    if not (request.user.is_staff or request.user.is_superuser):
        return HttpResponseForbidden("Admin access required")

    now = timezone.now()
    last_7_days = now - timedelta(days=7)

    patrols_qs = Patrol.objects.select_related("event")
    active_patrols = patrols_qs.filter(is_active=True)

    onboarding_pending_qs = patrols_qs.filter(onboarding_step__lt=3)
    pending_youtube_qs = PatrolYouTubeSubmission.objects.select_related("patrol").filter(
        leader_approval_status=PatrolYouTubeSubmission.LeaderApprovalStatus.PENDING
    )
    open_incidents_qs = RoverIncident.objects.select_related("patrol").filter(
        status__in=[RoverIncident.Status.OPEN, RoverIncident.Status.IN_REVIEW]
    )
    recent_certs_qs = MCERCertificate.objects.select_related("patrol").order_by("-issued_at")[:8]

    kpis = {
        "users_total": User.objects.count(),
        "events_active": Event.objects.filter(is_active=True).count(),
        "patrols_total": patrols_qs.count(),
        "patrols_active": active_patrols.count(),
        "onboarding_pending": onboarding_pending_qs.count(),
        "youtube_pending": pending_youtube_qs.count(),
        "incidents_open": open_incidents_qs.count(),
        "certificates_total": MCERCertificate.objects.count(),
        "certificates_week": MCERCertificate.objects.filter(issued_at__gte=last_7_days).count(),
    }

    onboarding_rows = []
    for patrol in onboarding_pending_qs.order_by("onboarding_step", "updated_at")[:8]:
        onboarding_rows.append(
            {
                "name": patrol.name,
                "delegation": patrol.delegation_name,
                "step": patrol.onboarding_step,
                "node_active": patrol.telegram_node_active,
                "updated_at": patrol.updated_at,
            }
        )

    youtube_rows = []
    for item in pending_youtube_qs.order_by("-submitted_at")[:8]:
        youtube_rows.append(
            {
                "id": item.id,
                "patrol": item.patrol.name,
                "youtube_url": item.youtube_url,
                "validation": item.validation_status,
                "audit": item.audit_status,
                "submitted_at": item.submitted_at,
            }
        )

    incident_rows = []
    for incident in open_incidents_qs.order_by("-created_at")[:8]:
        incident_rows.append(
            {
                "patrol": incident.patrol.name,
                "status": incident.status,
                "priority": incident.priority,
                "created_at": incident.created_at,
                "description": incident.description,
            }
        )

    cert_rows = []
    for cert in recent_certs_qs:
        cert_rows.append(
            {
                "patrol": cert.patrol.name,
                "level": cert.mcer_level,
                "points": cert.points_at_issue,
                "code": cert.certification_code,
                "issued_at": cert.issued_at,
                "preview": cert.is_preview_mode(),
            }
        )

    context = {
        "kpis": kpis,
        "onboarding_rows": onboarding_rows,
        "youtube_rows": youtube_rows,
        "incident_rows": incident_rows,
        "cert_rows": cert_rows,
        "admin_name": request.user.get_full_name() or request.user.get_username(),
        "generated_at": now,
    }
    return render(request, "ligilo/admin_dashboard.html", context)


def _parse_uuid_or_404(raw: str) -> UUID:
    try:
        return UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise Http404("token invalido") from exc


def _get_patrol_from_token(token: str) -> Patrol:
    parsed = _parse_uuid_or_404(token)
    patrol = (
        Patrol.objects.select_related("event")
        .filter(models.Q(invitation_token=parsed) | models.Q(telegram_node_token=parsed))
        .first()
    )
    if patrol is None:
        raise Http404("patrol not found for token")
    return patrol


def patrol_onboarding_step_a(request: HttpRequest, token: str) -> HttpResponse:
    patrol = _get_patrol_from_token(token)
    initial_interests = list(patrol.interests.values_list("tag", flat=True))

    if request.method == "POST":
        form = PatrolOnboardingStepAForm(request.POST, instance=patrol)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.onboarding_step = max(updated.onboarding_step, 1)
            updated.save()

            PatrolInterest.objects.filter(patrol=updated).delete()
            for tag in form.cleaned_data.get("interests") or []:
                PatrolInterest.objects.create(patrol=updated, tag=tag)

            return HttpResponseRedirect(reverse("dashboard:patrol-onboarding-step-b", args=[token]))
    else:
        form = PatrolOnboardingStepAForm(
            instance=patrol,
            initial={"event": patrol.event_id, "interests": initial_interests},
        )

    return render(
        request,
        "ligilo/patrol_onboarding_step_a.html",
        {
            "form": form,
            "patrol": patrol,
            "token": token,
        },
    )


def patrol_onboarding_step_b(request: HttpRequest, token: str) -> HttpResponse:
    patrol = _get_patrol_from_token(token)

    if request.method == "POST":
        formset = PatrolMemberFormSet(request.POST)
        if formset.is_valid():
            PatrolMember.objects.filter(patrol=patrol).delete()
            created = 0
            for form in formset:
                data = form.cleaned_data
                if not data:
                    continue
                if not any(data.get(k) for k in ["full_name", "alias", "gender", "birth_date", "initial_level"]):
                    continue
                member = PatrolMember(
                    patrol=patrol,
                    full_name=data["full_name"],
                    alias=data.get("alias") or "",
                    gender=data["gender"],
                    birth_date=data["birth_date"],
                    initial_level=data["initial_level"],
                )
                member.full_clean()
                member.save()
                created += 1

            patrol.member_count = created
            patrol.onboarding_step = max(patrol.onboarding_step, 2)
            patrol.save(update_fields=["member_count", "onboarding_step", "updated_at"])

            return HttpResponseRedirect(reverse("dashboard:patrol-onboarding-step-c", args=[token]))
    else:
        initial_rows = []
        for member in patrol.members.all()[:5]:
            initial_rows.append(
                {
                    "full_name": member.full_name,
                    "alias": member.alias,
                    "gender": member.gender,
                    "birth_date": member.birth_date,
                    "initial_level": member.initial_level,
                }
            )
        while len(initial_rows) < 5:
            initial_rows.append({})
        formset = PatrolMemberFormSet(initial=initial_rows)

    return render(
        request,
        "ligilo/patrol_onboarding_step_b.html",
        {
            "formset": formset,
            "patrol": patrol,
            "token": token,
        },
    )


def patrol_onboarding_step_c(request: HttpRequest, token: str) -> HttpResponse:
    patrol = _get_patrol_from_token(token)

    manager = TelegramManager()
    if not patrol.telegram_node_link:
        patrol.telegram_node_link = manager.build_unique_patrol_link(patrol)
        patrol.save(update_fields=["telegram_node_link", "updated_at"])

    joined_count = patrol.members.exclude(joined_node_at__isnull=True).count()
    member_target = patrol.members.count()

    if request.method == "POST" and request.POST.get("action") == "activate":
        all_joined = member_target >= 2 and joined_count == member_target
        if all_joined:
            patrol.telegram_node_active = True
            patrol.onboarding_step = max(patrol.onboarding_step, 3)
            patrol.onboarding_completed_at = timezone.now()
            patrol.save(
                update_fields=[
                    "telegram_node_active",
                    "onboarding_step",
                    "onboarding_completed_at",
                    "updated_at",
                ]
            )
            return HttpResponseRedirect(reverse("dashboard:patrol-operations", args=[token]))

    return render(
        request,
        "ligilo/patrol_onboarding_step_c.html",
        {
            "patrol": patrol,
            "token": token,
            "joined_count": joined_count,
            "member_target": member_target,
            "all_joined": member_target >= 2 and joined_count == member_target,
        },
    )


def _infer_ai_recommendation(mcer_level: str, text_points: int, audio_points: int) -> str:
    if mcer_level == "A1":
        return "Ustedes ya dominan frases base. Sumen vocabulario de campismo: tendumado, fajro, kompaso."
    if mcer_level == "A2":
        if audio_points < text_points:
            return "Jaguaroj, usen mas audio colaborativo para subir fluidez y desbloquear B1."
        return "Excelente progreso A2. Agreguen verbos en pasado para narrar experiencias de campamento."
    if mcer_level == "B1":
        return "Muy buen nivel B1. Para ir a B2, argumenten causas y consecuencias con ejemplos reales."
    return "Nivel avanzado. Mantengan liderazgo internacional y proyecto de impacto para cerrar B2."


def patrol_operations_dashboard(request: HttpRequest, token: str) -> HttpResponse:
    patrol = _get_patrol_from_token(token)
    engine = PoentaroEngine()
    snapshot = engine.compute(patrol)

    linguo_points = (
        PointLog.objects.filter(
            patrol=patrol,
            event_type__in=[PointLog.EventType.TEXT_VALIDATED, PointLog.EventType.AUDIO_VALIDATED],
        ).aggregate(total=models.Sum("points")).get("total")
        or 0
    )
    agado_points = (
        PointLog.objects.filter(patrol=patrol, event_type=PointLog.EventType.YOUTUBE_MISSION)
        .aggregate(total=models.Sum("points"))
        .get("total")
        or 0
    )
    amikeco_points = (
        MatchCelebrationEvent.objects.filter(patrol=patrol, first_interaction_at__isnull=False).count() * 40
    )

    recent_submission = (
        PatrolYouTubeSubmission.objects.filter(patrol=patrol).order_by("-submitted_at").first()
    )
    if recent_submission:
        findings = recent_submission.audit_findings or {}
        ai_feedback = findings.get(
            "esperanto_feedback",
            "Bravo. Mantengan claridad en la pronunciación y coordinación entre patrullas.",
        )
        validation_note = (
            f"Tu video recibió estado {recent_submission.validation_status}, auditoría {recent_submission.audit_status} "
            f"y sello del líder {recent_submission.leader_approval_status}."
        )
    else:
        ai_feedback = "Aún sin auditoría reciente. Envíen una misión YouTube para recibir feedback 360."
        validation_note = "No hay videos validados todavía."

    validated_360_count = PatrolYouTubeSubmission.objects.filter(
        patrol=patrol,
        validation_status=PatrolYouTubeSubmission.ValidationStatus.VALID,
        audit_status=PatrolYouTubeSubmission.AuditStatus.PASSED,
        leader_approval_status=PatrolYouTubeSubmission.LeaderApprovalStatus.APPROVED,
    ).count()

    b1_ready = snapshot.effective_score >= 3500 and validated_360_count >= 4
    b2_ready = snapshot.effective_score >= 6000 and patrol.leadership_project_validated

    if snapshot.effective_score >= 6001:
        energy_pct = 100
    else:
        energy_pct = max(1, min(99, int((snapshot.effective_score * 100) / 6001)))

    context = {
        "patrol": patrol,
        "token": token,
        "node_link": patrol.telegram_node_link,
        "rules": [
            "Interacción diaria: mínimo 3 mensajes por patrulla.",
            "Honor Scout: la validación de pares es sagrada.",
            "Feedback 360: validación técnica, pares, líder y auditoría IA.",
        ],
        "mcer_level": snapshot.mcer_level,
        "energy_pct": energy_pct,
        "linguo_points": linguo_points,
        "amikeco_points": amikeco_points,
        "agado_points": agado_points,
        "ai_recommendation": _infer_ai_recommendation(snapshot.mcer_level, linguo_points, agado_points),
        "latest_feedback": ai_feedback,
        "validation_note": validation_note,
        "validated_360_count": validated_360_count,
        "b1_ready": b1_ready,
        "b2_ready": b2_ready,
        "b1_missing_points": max(0, 3500 - snapshot.effective_score),
        "b1_missing_videos": max(0, 4 - validated_360_count),
        "b2_missing_points": max(0, 6000 - snapshot.effective_score),
    }
    return render(request, "ligilo/patrol_operations_dashboard.html", context)


@login_required
def download_patrol_certificate(request: HttpRequest) -> HttpResponse:
    patrol_id = request.GET.get("patrol_id")
    if not patrol_id:
        raise Http404("patrol_id is required")

    patrol = get_object_or_404(Patrol.objects.select_related("event"), pk=patrol_id)
    submissions = Submission.objects.filter(patrol=patrol).select_related("mission")
    reviewed_count = submissions.filter(status=Submission.Status.REVIEWED).count()
    total_count = submissions.count()
    latest_submission = submissions.order_by("-submitted_at").first()
    mission_name = latest_submission.mission.title if latest_submission else "Sin mision enviada"

    verification_code = (
        f"LGL-{patrol.event_id:03d}-{patrol.id:03d}-{timezone.localdate().strftime('%Y%m%d')}"
    )

    lines = [
        "LIGILO - CERTIFICADO DE PATRULLA",
        "",
        f"Patrulla: {patrol.name}",
        f"Delegacion: {patrol.delegation_name}",
        f"Evento: {patrol.event.name}",
        f"Idioma oficial: {patrol.official_language_name}",
        f"Scouts: {patrol.member_count}",
        f"Submissions revisadas: {reviewed_count}/{total_count}",
        f"Ultima mision: {mission_name}",
        f"Codigo de verificacion: {verification_code}",
        f"Emitido: {timezone.localdate().strftime('%d/%m/%Y')}",
    ]

    response = HttpResponse(_build_simple_pdf(lines), content_type="application/pdf")
    filename = slugify(f"certificado-{patrol.name}") or f"patrulla-{patrol.id}"
    response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
    return response


@login_required
def share_patrol_certificate(request: HttpRequest) -> HttpResponse:
    patrol_id = request.GET.get("patrol_id")
    if not patrol_id:
        raise Http404("patrol_id is required")

    patrol = get_object_or_404(Patrol.objects.select_related("event"), pk=patrol_id)
    submissions = Submission.objects.filter(patrol=patrol)
    reviewed_count = submissions.filter(status=Submission.Status.REVIEWED).count()
    total_count = submissions.count()

    subject = f"Certificado Ligilo - {patrol.name}"
    body = (
        f"Hola delegacion {patrol.delegation_name},\n\n"
        f"La patrulla {patrol.name} quedo certificada en {patrol.event.name}.\n"
        f"Submissions revisadas: {reviewed_count}/{total_count}.\n"
        f"Scouts activos: {patrol.member_count}.\n\n"
        "Puedes descargar el certificado actualizado desde el dashboard Ligilo."
    )
    query = urlencode({"subject": subject, "body": body})
    target_email = patrol.leader_email or ""
    return HttpResponseRedirect(f"mailto:{target_email}?{query}")


@login_required
def share_patrol_certificate_telegram(request: HttpRequest) -> HttpResponse:
    patrol_id = request.GET.get("patrol_id")
    if not patrol_id:
        raise Http404("patrol_id is required")

    patrol = get_object_or_404(Patrol.objects.select_related("event"), pk=patrol_id)
    submissions = Submission.objects.filter(patrol=patrol)
    reviewed_count = submissions.filter(status=Submission.Status.REVIEWED).count()
    total_count = submissions.count()

    certificate_path = reverse("dashboard:download-certificate")
    certificate_url = request.build_absolute_uri(f"{certificate_path}?patrol_id={patrol.id}")
    share_text = (
        f"Certificado Ligilo: {patrol.name} ({patrol.delegation_name}) en {patrol.event.name}. "
        f"Submissions revisadas: {reviewed_count}/{total_count}."
    )
    query = urlencode({"url": certificate_url, "text": share_text})
    return HttpResponseRedirect(f"https://t.me/share/url?{query}")


def stelo_achievement_profile(request: HttpRequest, patrol_id: int) -> HttpResponse:
    """
    Public achievement profile page — no login required.
    Linked from QR code; verifies the JWT token if present.
    Scouts show this on their phone screen at the SEL stand to receive their patch.
    """
    patrol = get_object_or_404(
        Patrol.objects.select_related("event"), pk=patrol_id, is_active=True
    )
    token = request.GET.get("token", "")
    token_result: dict = {}
    if token:
        token_result = verify_certification_token(token)

    cert: SteloCertification | None = SteloCertification.objects.filter(
        patrol=patrol, revoked=False
    ).first()

    from datetime import timedelta
    recent_logs = PointLog.objects.filter(
        patrol=patrol,
        created_at__gte=timezone.now() - timedelta(days=30),
    ).order_by("-created_at")[:10]

    tier_colors = {
        SteloCertification.Tier.BRONZE: "#b45309",
        SteloCertification.Tier.SILVER: "#64748b",
        SteloCertification.Tier.GOLD: "#b45309",
    }
    tier_labels = {
        SteloCertification.Tier.BRONZE: "🥉 Bronce",
        SteloCertification.Tier.SILVER: "🥈 Plata",
        SteloCertification.Tier.GOLD: "🥇 Oro",
    }

    context = {
        "patrol": patrol,
        "cert": cert,
        "tier_label": tier_labels.get(cert.tier, cert.tier) if cert else None,
        "tier_color": tier_colors.get(cert.tier, "#1e40af") if cert else "#1e40af",
        "token_valid": token_result.get("valid"),
        "token_reason": token_result.get("reason"),
        "recent_logs": recent_logs,
        "next_threshold": _next_threshold(patrol.sel_points),
        "progress_pct": _progress_pct(patrol.sel_points),
    }
    return render(request, "ligilo/stelo_achievement_profile.html", context)


@login_required
def stelo_issue_qr(request: HttpRequest) -> HttpResponse:
    """
    Leader-authenticated endpoint: issue or renew the Stelo QR for the current patrol.
    Returns JSON so it can be called from the Telegram bot or admin dashboard.
    """
    import json as _json
    patrol_id = request.GET.get("patrol_id")
    if not patrol_id:
        raise Http404("patrol_id is required")

    patrol = get_object_or_404(Patrol.objects.select_related("event"), pk=patrol_id)
    result = check_and_issue_certification(patrol)
    return HttpResponse(
        _json.dumps(result, ensure_ascii=False),
        content_type="application/json; charset=utf-8",
    )


@login_required
def youtube_submission_review(request: HttpRequest, submission_id: int) -> HttpResponse:
    submission = get_object_or_404(
        PatrolYouTubeSubmission.objects.select_related("patrol__event"),
        pk=submission_id,
    )

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip().lower()
        notes = (request.POST.get("notes") or "").strip()

        if action == "approve":
            submission.leader_approval_status = PatrolYouTubeSubmission.LeaderApprovalStatus.APPROVED
            submission.leader_approved_at = timezone.now()
            submission.final_approved_at = timezone.now()
            submission.leader_approval_notes = notes
            submission.approved_for_wall_of_fame = bool(
                submission.patrol.sel_points >= SteloCertification.THRESHOLD_GOLD
            )
            submission.save(
                update_fields=[
                    "leader_approval_status",
                    "leader_approved_at",
                    "final_approved_at",
                    "leader_approval_notes",
                    "approved_for_wall_of_fame",
                ]
            )

            already_awarded = PointLog.objects.filter(
                patrol=submission.patrol,
                event_type=PointLog.EventType.YOUTUBE_MISSION,
                external_ref=submission.video_id,
            ).exists()
            if not already_awarded:
                PointLog.objects.create(
                    patrol=submission.patrol,
                    event_type=PointLog.EventType.YOUTUBE_MISSION,
                    points=500,
                    external_ref=submission.video_id,
                    metadata={
                        "source": "leader_final_approval",
                        "submission_id": submission.id,
                        "notes": notes,
                    },
                )
                Patrol.objects.filter(pk=submission.patrol_id).update(sel_points=models.F("sel_points") + 500)

            return HttpResponseRedirect(reverse("dashboard:youtube-review", args=[submission.id]))

        if action == "reject":
            submission.leader_approval_status = PatrolYouTubeSubmission.LeaderApprovalStatus.REJECTED
            submission.leader_approval_notes = notes
            submission.final_approved_at = None
            submission.save(
                update_fields=[
                    "leader_approval_status",
                    "leader_approval_notes",
                    "final_approved_at",
                ]
            )
            return HttpResponseRedirect(reverse("dashboard:youtube-review", args=[submission.id]))

    return render(
        request,
        "ligilo/youtube_submission_review.html",
        {
            "submission": submission,
            "patrol": submission.patrol,
            "audit_findings": submission.audit_findings or {},
            "validation_errors": submission.validation_errors or [],
            "audit_errors": submission.audit_errors or [],
            "is_pending": (
                submission.leader_approval_status
                == PatrolYouTubeSubmission.LeaderApprovalStatus.PENDING
            ),
        },
    )


def _next_threshold(points: int) -> int:
    for t in (
        SteloCertification.THRESHOLD_BRONZE,
        SteloCertification.THRESHOLD_SILVER,
        SteloCertification.THRESHOLD_GOLD,
    ):
        if points < t:
            return t
    return SteloCertification.THRESHOLD_GOLD


def _progress_pct(points: int) -> int:
    threshold = _next_threshold(points)
    # Find the previous tier threshold
    tiers = [0, SteloCertification.THRESHOLD_BRONZE, SteloCertification.THRESHOLD_SILVER, SteloCertification.THRESHOLD_GOLD]
    prev = 0
    for t in tiers:
        if t < threshold:
            prev = t
    span = threshold - prev
    earned = points - prev
    if span <= 0:
        return 100
    return min(100, max(0, int(earned * 100 / span)))