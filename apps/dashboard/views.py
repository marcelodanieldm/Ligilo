import io
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.text import slugify

from apps.dashboard.controllers.leader_dashboard_controller import LeaderDashboardController
from apps.scouting.models import Patrol, PointLog, SteloCertification, Submission
from apps.scouting.services.certification import check_and_issue_certification, verify_certification_token


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


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
    controller = LeaderDashboardController()
    return render(request, "ligilo/leader_dashboard.html", controller.get_context())


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