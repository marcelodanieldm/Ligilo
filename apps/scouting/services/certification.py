"""
Stelo-Meter Certification Service
==================================
Handles:
  - Milestone threshold checks (Bronze 500 / Silver 1000 / Gold 2000)
  - JWT-signed achievement URL generation
  - QR code PNG generation (error-correction H = scans at ~30% damage / dim screens)
  - Issuance and renewal of SteloCertification records
"""
from __future__ import annotations

import base64
import io
import os
import uuid
from datetime import timedelta

import jwt
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.scouting.models import Patrol, SteloCertification

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_SECRET = os.getenv("DJANGO_SECRET_KEY", "django-insecure-ligilo-prototype-key")
_ALGORITHM = "HS256"
_CERT_TTL_DAYS = 365  # QR valid for one year
# Public base URL for the achievement profile — override via env in production
_BASE_URL = os.getenv("LIGILO_PUBLIC_BASE_URL", "https://ligilo.sel.org")


def _make_certification_code(patrol: Patrol) -> str:
    short_uid = uuid.uuid4().hex[:8].upper()
    return f"SEL-{patrol.event_id:03d}-{patrol.id:04d}-{short_uid}"


def _sign_jwt(payload: dict, expires_at) -> str:
    claims = {
        **payload,
        "iat": int(timezone.now().timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(claims, _SECRET, algorithm=_ALGORITHM)


def _generate_qr_png_b64(url: str) -> str:
    """
    Render QR as a base64 PNG.
    Error correction H (≈30%) ensures readability on dim/partial screens.
    Size: 400×400 px with quiet-zone border = max scannability at badge distance.
    """
    try:
        import qrcode
        from qrcode.constants import ERROR_CORRECT_H

        qr = qrcode.QRCode(
            version=None,  # auto-size
            error_correction=ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except ImportError:
        # qrcode not installed — return empty (QR URL still works via quickchart fallback)
        return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_and_issue_certification(patrol: Patrol) -> dict:
    """
    Check if patrol has reached a certification milestone and (re)issue if so.

    Returns:
        {
            "eligible": bool,
            "tier": "bronze"|"silver"|"gold"|None,
            "required_points": int,          # only when not eligible
            "current_points": int,
            "certification_code": str,
            "profile_url": str,              # signed JWT URL
            "qr_png_b64": str,               # base64 PNG (empty if qrcode not installed)
            "qr_fallback_url": str,          # quickchart.io fallback URL
            "renewed": bool,                 # True if tier was upgraded
            "issued_at": str,
            "expires_at": str,
        }
    """
    points = patrol.sel_points
    tier = SteloCertification.tier_for_points(points)

    if tier is None:
        next_threshold = SteloCertification.THRESHOLD_BRONZE
        return {
            "eligible": False,
            "tier": None,
            "current_points": points,
            "required_points": next_threshold,
            "reason": "insufficient_points",
        }

    # Check if an existing cert covers the same or higher tier
    existing: SteloCertification | None = SteloCertification.objects.filter(
        patrol=patrol, revoked=False
    ).first()

    tier_rank = {
        SteloCertification.Tier.BRONZE: 1,
        SteloCertification.Tier.SILVER: 2,
        SteloCertification.Tier.GOLD: 3,
    }
    if existing and tier_rank.get(existing.tier, 0) >= tier_rank[tier]:
        # Already certified at this tier or higher — return existing cert
        return _cert_to_dict(existing, renewed=False)

    # Issue (or upgrade) the certificate
    return _issue_certification(patrol, tier, points, existing)


@transaction.atomic
def _issue_certification(
    patrol: Patrol,
    tier: str,
    points: int,
    existing: SteloCertification | None,
) -> dict:
    if existing:
        existing.revoked = True
        existing.save(update_fields=["revoked"])

    cert_code = _make_certification_code(patrol)
    issued_at = timezone.now()
    expires_at = issued_at + timedelta(days=_CERT_TTL_DAYS)

    # Build the public profile URL that the QR points to
    profile_path = f"/scouts/achievement/{patrol.id}/"
    profile_url_base = f"{_BASE_URL}{profile_path}"

    jwt_payload = {
        "sub": str(patrol.id),
        "patrol_name": patrol.name,
        "delegation": patrol.delegation_name,
        "event_id": patrol.event_id,
        "event_name": patrol.event.name,
        "tier": tier,
        "points": points,
        "cert": cert_code,
        "profile_url": profile_url_base,
    }
    token = _sign_jwt(jwt_payload, expires_at)

    # The URL embedded in QR carries the JWT as a query param so scanners
    # land on the verified public profile page
    signed_url = f"{profile_url_base}?token={token}"

    qr_b64 = _generate_qr_png_b64(signed_url)

    cert = SteloCertification.objects.create(
        patrol=patrol,
        tier=tier,
        points_at_issue=points,
        certification_code=cert_code,
        jwt_token=token,
        qr_png_b64=qr_b64,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    return _cert_to_dict(cert, renewed=existing is not None)


def _cert_to_dict(cert: SteloCertification, *, renewed: bool) -> dict:
    profile_path = f"/scouts/achievement/{cert.patrol_id}/"
    profile_url_base = f"{_BASE_URL}{profile_path}"
    signed_url = f"{profile_url_base}?token={cert.jwt_token}"

    # Fallback QR URL via quickchart.io (no server-side rendering needed)
    import urllib.parse
    qr_fallback_url = (
        f"https://quickchart.io/qr"
        f"?text={urllib.parse.quote(signed_url, safe='')}"
        f"&size=400&ecLevel=H&margin=4"
    )

    return {
        "eligible": True,
        "tier": cert.tier,
        "current_points": cert.points_at_issue,
        "certification_code": cert.certification_code,
        "profile_url": signed_url,
        "qr_png_b64": cert.qr_png_b64,
        "qr_fallback_url": qr_fallback_url,
        "renewed": renewed,
        "issued_at": cert.issued_at.isoformat(),
        "expires_at": cert.expires_at.isoformat(),
    }


def verify_certification_token(token: str) -> dict:
    """
    Verify a JWT from a QR scan.
    Returns decoded payload or an error dict.
    Used by the public achievement profile view.
    """
    try:
        payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
        # Extra check: cert code must still exist and not be revoked
        cert_code = payload.get("cert")
        cert = SteloCertification.objects.filter(
            certification_code=cert_code, revoked=False
        ).select_related("patrol__event").first()
        if cert is None:
            return {"valid": False, "reason": "revoked_or_not_found"}
        return {"valid": True, "payload": payload, "cert_id": cert.id}
    except jwt.ExpiredSignatureError:
        return {"valid": False, "reason": "expired"}
    except jwt.InvalidTokenError:
        return {"valid": False, "reason": "invalid_token"}
