import os
import uuid
from datetime import timedelta
import json

import django
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.utils import timezone


if not os.getenv("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django.setup()

from apps.scouting.models import (  # noqa: E402
    AuditLog,
    MatchCelebrationEvent,
    MCERCertificate,
    Patrol,
    PatrolMatch,
    PatrolYouTubeSubmission,
    Payment,
    PointLog,
    RoverIncident,
    SteloCertification,
)
from apps.scouting.services.certification import check_and_issue_certification  # noqa: E402
from apps.scouting.services.poentaro_engine import PoentaroEngine  # noqa: E402


User = get_user_model()


def _serialize_patrol(patrol: Patrol | None) -> dict | None:
    if patrol is None:
        return None
    return {
        "id": patrol.id,
        "name": patrol.name,
        "delegation_name": patrol.delegation_name,
        "event_id": patrol.event_id,
        "telegram_chat_id": patrol.telegram_chat_id,
        "training_points": patrol.training_points,
        "sel_points": patrol.sel_points,
        "is_rover_moderator": patrol.is_rover_moderator,
        "mcer_notified_a1": patrol.mcer_notified_a1,
        "mcer_notified_a2": patrol.mcer_notified_a2,
        "mcer_notified_b1": patrol.mcer_notified_b1,
    }


POINT_RULES = {
    PointLog.EventType.TEXT_VALIDATED: 10,
    PointLog.EventType.AUDIO_VALIDATED: 50,
    PointLog.EventType.YOUTUBE_MISSION: 500,
}

# Stelo-Meter tier thresholds
TIER_THRESHOLDS = {
    "bronze": 500,
    "silver": 1000,
    "gold": 2000,
}


def _get_tier_progress_info(sel_points: int) -> dict:
    """
    Calculate current tier, progress percentage, and 50% milestone info.
    Returns: {
        current_tier: str,
        current_threshold: int,
        next_threshold: int,
        progress_pct: int,
        crossed_50_percent: bool,
        previous_progress_pct: int (before this point award)
    }
    """
    thresholds = [500, 1000, 2000]
    
    # Determine current tier bracket
    current_threshold = 0
    next_threshold = 500
    
    for threshold in thresholds:
        if sel_points >= threshold:
            current_threshold = threshold
            # Find next threshold
            next_idx = thresholds.index(threshold) + 1
            next_threshold = thresholds[next_idx] if next_idx < len(thresholds) else threshold
        else:
            next_threshold = threshold
            break
    
    # Calculate progress percentage in current bracket
    bracket_start = current_threshold
    bracket_end = next_threshold
    bracket_size = bracket_end - bracket_start
    
    points_in_bracket = sel_points - bracket_start
    progress_pct = min(100, max(0, (points_in_bracket * 100) // bracket_size))
    
    # Determine tier name
    tier_map = {500: "bronze", 1000: "silver", 2000: "gold"}
    current_tier = tier_map.get(current_threshold, "none")
    
    return {
        "current_tier": current_tier,
        "current_threshold": current_threshold,
        "next_threshold": next_threshold,
        "progress_pct": progress_pct,
        "bracket_size": bracket_size,
    }


def _check_50_percent_milestone(previous_points: int, new_points: int) -> dict:
    """
    Check if 50% milestone was crossed between previous and new points.
    Returns: {
        crossed_50_percent: bool,
        milestone_tier: str | None,
        milestone_target_points: int | None,
    }
    """
    prev_info = _get_tier_progress_info(previous_points)
    new_info = _get_tier_progress_info(new_points)
    
    prev_pct = prev_info["progress_pct"]
    new_pct = new_info["progress_pct"]
    
    # Check if we crossed 50% (going from <= 50% to >= 50%)
    crossed = prev_pct < 50 and new_pct >= 50
    
    if crossed and new_info["current_tier"] != "none":
        return {
            "crossed_50_percent": True,
            "milestone_tier": new_info["current_tier"],
            "milestone_target_points": new_info["next_threshold"],
            "current_points": new_points,
        }
    
    return {"crossed_50_percent": False}


@sync_to_async
def get_patrol_by_chat_id(chat_id: int) -> dict | None:
    patrol = Patrol.objects.select_related("event").filter(telegram_chat_id=chat_id).first()
    return _serialize_patrol(patrol)


@sync_to_async
def bind_chat_to_patrol_token(chat_id: int, token: str) -> dict:
    raw_token = token.strip()
    if not raw_token:
        return {"status": "invalid_token"}

    try:
        parsed_token = uuid.UUID(raw_token)
    except ValueError:
        return {"status": "invalid_token"}

    # La transakcio certigas konsekvencan ligon inter token kaj chat_id.
    with transaction.atomic():
        patrol = (
            Patrol.objects.select_for_update()
            .select_related("event")
            .filter(invitation_token=parsed_token)
            .first()
        )
        if patrol is None:
            return {"status": "invalid_token"}

        if patrol.telegram_chat_id and patrol.telegram_chat_id != chat_id:
            return {"status": "token_already_used"}

        existing_by_chat = Patrol.objects.select_for_update().filter(telegram_chat_id=chat_id).exclude(pk=patrol.pk)
        if existing_by_chat.exists():
            return {"status": "chat_already_bound"}

        patrol.telegram_chat_id = chat_id
        # Unufoja tokeno: post sukcesa ligado ni nuligas la inviton.
        patrol.invitation_token = None
        patrol.save(update_fields=["telegram_chat_id", "invitation_token", "updated_at"])

    return {
        "status": "bound",
        "patrol": _serialize_patrol(patrol),
    }


@sync_to_async
def get_registration_status(chat_id: int) -> dict:
    patrol = Patrol.objects.select_related("event").filter(telegram_chat_id=chat_id).first()
    if patrol is None:
        return {
            "bound": False,
            "registration_complete": False,
            "has_sister_patrol": False,
            "is_training": True,
            "match_id": None,
            "patrol": None,
            "sister_patrol": None,
        }

    match = (
        PatrolMatch.objects.select_related("patrol_a", "patrol_b")
        .filter(
            Q(patrol_a_id=patrol.id) | Q(patrol_b_id=patrol.id),
            status__in=[PatrolMatch.Status.PROPOSED, PatrolMatch.Status.ACTIVE],
        )
        .order_by("-matched_at")
        .first()
    )

    sister_patrol = None
    is_training = True
    match_id = None
    if match is not None:
        match_id = match.id
        is_training = bool(match.is_training)
        sibling = match.patrol_b if match.patrol_a_id == patrol.id else match.patrol_a
        if not is_training:
            sister_patrol = {
                "id": sibling.id,
                "name": sibling.name,
                "delegation_name": sibling.delegation_name,
                "status": match.status,
            }

    return {
        "bound": True,
        "registration_complete": sister_patrol is not None,
        "has_sister_patrol": sister_patrol is not None,
        "is_training": is_training,
        "match_id": match_id,
        "patrol": _serialize_patrol(patrol),
        "sister_patrol": sister_patrol,
    }


def create_audit_log_entry(
    *,
    user_identifier: str,
    input_text: str,
    ai_response: dict,
    flagged_status: bool,
) -> None:
    user_obj = None
    normalized_id = user_identifier.strip()
    if normalized_id.isdigit():
        user_obj = User.objects.filter(pk=int(normalized_id)).first()

    AuditLog.objects.create(
        user=user_obj,
        user_identifier=normalized_id,
        input_text=input_text,
        ai_response=ai_response,
        flagged_status=flagged_status,
    )


def _serialize_match_card_payload(patrol: Patrol, sister: Patrol, patrol_match: PatrolMatch) -> dict:
    return {
        "chat_id": patrol.telegram_chat_id,
        "match_id": patrol_match.id,
        "patrol": {
            "id": patrol.id,
            "name": patrol.name,
            "delegation_name": patrol.delegation_name,
            "country_code": patrol.country_code,
        },
        "sister_patrol": {
            "id": sister.id,
            "name": sister.name,
            "delegation_name": sister.delegation_name,
            "country_code": sister.country_code,
        },
        "suggested_phrase": "Saluton, amikoj!",
    }


@sync_to_async
def prepare_match_celebration_payloads(chat_id: int) -> list[dict]:
    patrol = Patrol.objects.select_related("event").filter(telegram_chat_id=chat_id).first()
    if patrol is None:
        return []

    patrol_match = (
        PatrolMatch.objects.select_related("patrol_a", "patrol_b")
        .filter(
            Q(patrol_a_id=patrol.id) | Q(patrol_b_id=patrol.id),
            status__in=[PatrolMatch.Status.PROPOSED, PatrolMatch.Status.ACTIVE],
            is_training=False,
        )
        .order_by("-matched_at")
        .first()
    )
    if patrol_match is None:
        return []

    patrol_a = patrol_match.patrol_a
    patrol_b = patrol_match.patrol_b
    recipients: list[dict] = []

    with transaction.atomic():
        for own, sister in ((patrol_a, patrol_b), (patrol_b, patrol_a)):
            if not own.telegram_chat_id:
                continue

            event_obj, created = MatchCelebrationEvent.objects.get_or_create(
                patrol_match=patrol_match,
                patrol=own,
                defaults={
                    "event_name": "match_celebrated",
                    "telegram_chat_id": own.telegram_chat_id,
                },
            )

            if event_obj.telegram_chat_id != own.telegram_chat_id:
                event_obj.telegram_chat_id = own.telegram_chat_id
                event_obj.save(update_fields=["telegram_chat_id"])

            if created:
                recipients.append(_serialize_match_card_payload(own, sister, patrol_match))

    return recipients


@sync_to_async
def capture_match_celebration_interaction(chat_id: int) -> None:
    patrol = Patrol.objects.filter(telegram_chat_id=chat_id).first()
    if patrol is None:
        return

    event = (
        MatchCelebrationEvent.objects.select_related("patrol_match")
        .filter(patrol=patrol, first_interaction_at__isnull=True)
        .order_by("-sent_at")
        .first()
    )
    if event is None:
        return

    now = timezone.now()
    elapsed = now - event.sent_at
    seconds = max(0, int(elapsed / timedelta(seconds=1)))
    event.first_interaction_at = now
    event.first_interaction_seconds = seconds
    event.save(update_fields=["first_interaction_at", "first_interaction_seconds"])


@sync_to_async
def add_training_points(chat_id: int, points: int = 1) -> int:
    patrol = Patrol.objects.filter(telegram_chat_id=chat_id).first()
    if patrol is None:
        return 0

    safe_points = max(0, points)
    if safe_points == 0:
        return patrol.training_points

    Patrol.objects.filter(pk=patrol.pk).update(training_points=F("training_points") + safe_points)
    patrol.refresh_from_db(fields=["training_points"])
    return patrol.training_points


@sync_to_async
def award_points_by_chat(
    chat_id: int,
    *,
    event_type: str,
    external_ref: str = "",
    metadata: dict | None = None,
) -> dict:
    patrol = Patrol.objects.filter(telegram_chat_id=chat_id).first()
    if patrol is None:
        return {"awarded": False, "reason": "patrol_not_found", "sel_points": 0}

    points = POINT_RULES.get(event_type)
    if points is None:
        return {"awarded": False, "reason": "unknown_event", "sel_points": patrol.sel_points}

    normalized_ref = external_ref.strip()
    if normalized_ref:
        already_exists = PointLog.objects.filter(
            patrol=patrol,
            event_type=event_type,
            external_ref=normalized_ref,
        ).exists()
        if already_exists:
            return {
                "awarded": False,
                "reason": "already_awarded",
                "sel_points": patrol.sel_points,
            }

    # Capture points before award for milestone detection
    previous_points = patrol.sel_points

    with transaction.atomic():
        PointLog.objects.create(
            patrol=patrol,
            event_type=event_type,
            points=points,
            external_ref=normalized_ref,
            metadata=metadata or {},
        )
        Patrol.objects.filter(pk=patrol.pk).update(sel_points=F("sel_points") + points)

    patrol.refresh_from_db(fields=["sel_points"])
    result = {"awarded": True, "reason": "ok", "points": points, "sel_points": patrol.sel_points}

    # Check for 50% milestone (monetization trigger)
    milestone_info = _check_50_percent_milestone(previous_points, patrol.sel_points)
    if milestone_info.get("crossed_50_percent"):
        result["milestone_50_percent"] = milestone_info

    # Check for consistency bonus: 3 audio submissions in the last 24 hours
    if event_type == PointLog.EventType.AUDIO_VALIDATED:
        window_start = timezone.now() - timedelta(hours=24)
        recent_audio_count = PointLog.objects.filter(
            patrol=patrol,
            event_type=PointLog.EventType.AUDIO_VALIDATED,
            created_at__gte=window_start,
        ).count()

        if recent_audio_count == 3:
            bonus_points = POINT_RULES[PointLog.EventType.AUDIO_VALIDATED] * 2  # 2x bonus = 100 pts
            already_bonus = PointLog.objects.filter(
                patrol=patrol,
                event_type=PointLog.EventType.CONSISTENCY_BONUS,
                created_at__gte=window_start,
            ).exists()
            if not already_bonus:
                with transaction.atomic():
                    PointLog.objects.create(
                        patrol=patrol,
                        event_type=PointLog.EventType.CONSISTENCY_BONUS,
                        points=bonus_points,
                        multiplier="2.00",
                        metadata={"trigger": "3_audios_in_24h", "window_start": window_start.isoformat()},
                    )
                    Patrol.objects.filter(pk=patrol.pk).update(sel_points=F("sel_points") + bonus_points)
                patrol.refresh_from_db(fields=["sel_points"])
                result["consistency_bonus"] = {"awarded": True, "bonus_points": bonus_points}
                result["sel_points"] = patrol.sel_points

    # Compute composite progression score (PoentaroEngine) and trigger milestone flags.
    engine = PoentaroEngine()
    snapshot = engine.compute(patrol)
    result["poentaro"] = {
        "base_points": snapshot.base_points,
        "daily_telegram_points": snapshot.daily_telegram_points,
        "peer_validation_points": snapshot.peer_validation_points,
        "leader_multiplier": snapshot.leader_multiplier,
        "effective_score": snapshot.effective_score,
        "mcer_level": snapshot.mcer_level,
    }

    reached_levels: list[str] = []
    update_map: dict[str, object] = {}
    now = timezone.now()

    if snapshot.effective_score >= engine.THRESHOLD_A1 and not patrol.mcer_notified_a1:
        reached_levels.append("A1")
        update_map["mcer_notified_a1"] = True

    if snapshot.effective_score >= engine.THRESHOLD_A2 and not patrol.mcer_notified_a2:
        reached_levels.append("A2")
        update_map["mcer_notified_a2"] = True

    if snapshot.effective_score >= engine.THRESHOLD_B1 and not patrol.mcer_notified_b1:
        reached_levels.append("B1")
        update_map["mcer_notified_b1"] = True
        update_map["sel_patch_prep_notified_at"] = now

    if update_map:
        Patrol.objects.filter(pk=patrol.pk).update(**update_map)

    if reached_levels:
        result["mcer_milestones"] = reached_levels
        if "B1" in reached_levels:
            result["notify_sel_patch_preparation"] = True

    return result


@sync_to_async
def build_certification_qr_payload(patrol_id: int) -> dict:
    """
    Check milestone eligibility and issue/renew a Stelo certification.
    Returns a unified dict compatible with the existing gamification router.
    Thresholds: Bronze 500 / Silver 1000 / Gold 2000 pts.
    """
    patrol = Patrol.objects.select_related("event").filter(pk=patrol_id).first()
    if patrol is None:
        return {"eligible": False, "reason": "patrol_not_found"}

    result = check_and_issue_certification(patrol)
    if not result.get("eligible"):
        return result

    # Build quickchart fallback QR URL at size=400 with ecLevel=H (matches service)
    return {
        "eligible": True,
        "tier": result.get("tier"),
        "certification_code": result.get("certification_code"),
        "payload": {
            "patrol_id": patrol.id,
            "patrol_name": patrol.name,
            "delegation_name": patrol.delegation_name,
            "event": patrol.event.name,
            "points": result.get("current_points"),
            "tier": result.get("tier"),
            "cert": result.get("certification_code"),
            "issued_at": result.get("issued_at"),
            "expires_at": result.get("expires_at"),
        },
        "qr_url": result.get("qr_fallback_url"),
        "qr_png_b64": result.get("qr_png_b64"),
        "profile_url": result.get("profile_url"),
        "renewed": result.get("renewed", False),
    }


@sync_to_async
def create_payment(
    patrol_id: int,
    product_type: str,
    amount_cents: int,
    payment_method: str,
    metadata: dict | None = None,
) -> dict:
    """Create a new payment record for a patrol."""
    try:
        patrol = Patrol.objects.get(pk=patrol_id)
    except Patrol.DoesNotExist:
        return {"success": False, "error": "Patrol not found"}

    payment = Payment.objects.create(
        patrol=patrol,
        product_type=product_type,
        amount_cents=amount_cents,
        payment_method=payment_method,
        metadata=metadata or {},
        status=Payment.Status.PENDING,
    )

    return {
        "success": True,
        "payment_id": payment.id,
        "status": payment.status,
        "amount": amount_cents / 100,
    }


@sync_to_async
def create_or_update_youtube_submission_by_chat(
    chat_id: int,
    *,
    youtube_url: str,
    validation_result: dict,
    audit_result: dict,
) -> dict:
    patrol = Patrol.objects.filter(telegram_chat_id=chat_id).first()
    if patrol is None:
        return {"ok": False, "reason": "patrol_not_found"}

    video_id = str(validation_result.get("video_id") or "").strip()
    if not video_id:
        return {"ok": False, "reason": "invalid_video_id"}

    embed_url = str(validation_result.get("embed_url") or f"https://www.youtube.com/embed/{video_id}")
    is_valid_metadata = bool(validation_result.get("valid"))
    is_audit_pass = bool(audit_result.get("audit_valid"))

    validation_status = (
        PatrolYouTubeSubmission.ValidationStatus.VALID
        if is_valid_metadata
        else PatrolYouTubeSubmission.ValidationStatus.INVALID
    )
    audit_status = (
        PatrolYouTubeSubmission.AuditStatus.PASSED
        if is_audit_pass
        else PatrolYouTubeSubmission.AuditStatus.FAILED
    )

    with transaction.atomic():
        submission, _created = PatrolYouTubeSubmission.objects.update_or_create(
            patrol=patrol,
            defaults={
                "youtube_url": youtube_url,
                "video_id": video_id,
                "embed_url": embed_url,
                "validation_status": validation_status,
                "validation_errors": list(validation_result.get("errors") or []),
                "validation_warnings": list(validation_result.get("warnings") or []),
                "metadata": dict(validation_result.get("metadata") or {}),
                "audit_status": audit_status,
                "audit_errors": list(audit_result.get("errors") or []),
                "audit_findings": dict(audit_result.get("findings") or {}),
                "validated_at": timezone.now() if is_valid_metadata else None,
                "audited_at": timezone.now(),
                "leader_approval_status": PatrolYouTubeSubmission.LeaderApprovalStatus.PENDING,
                "leader_approval_notes": "",
                "leader_approved_at": None,
                "final_approved_at": None,
                "approved_for_wall_of_fame": False,
                "leader_notification_sent_at": timezone.now() if (is_valid_metadata and is_audit_pass) else None,
            },
        )

    public_base = os.getenv("DJANGO_PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    review_url = f"{public_base}/scouts/youtube/review/{submission.id}/"

    return {
        "ok": True,
        "submission_id": submission.id,
        "video_id": submission.video_id,
        "embed_url": submission.embed_url,
        "leader_approval_required": is_valid_metadata and is_audit_pass,
        "leader_review_url": review_url,
        "leader_email": patrol.leader_email,
        "validation_status": submission.validation_status,
        "audit_status": submission.audit_status,
    }


@sync_to_async
def create_rover_incident_by_chat(chat_id: int, *, description: str) -> dict:
    patrol = Patrol.objects.filter(telegram_chat_id=chat_id).first()
    if patrol is None:
        return {"ok": False, "reason": "patrol_not_found"}
    if not patrol.is_rover_moderator:
        return {"ok": False, "reason": "rover_only"}

    summary = description.strip()
    if not summary:
        return {"ok": False, "reason": "empty_description"}

    incident = RoverIncident.objects.create(
        patrol=patrol,
        reported_by_chat_id=chat_id,
        description=summary,
        priority="high",
        status=RoverIncident.Status.OPEN,
    )
    return {
        "ok": True,
        "incident_id": incident.id,
        "status": incident.status,
        "priority": incident.priority,
        "created_at": incident.created_at.isoformat(),
    }


@sync_to_async
def get_payment_by_stripe_id(stripe_payment_intent_id: str) -> dict | None:
    """Retrieve payment by Stripe payment intent ID."""
    payment = Payment.objects.filter(
        stripe_payment_intent_id=stripe_payment_intent_id
    ).first()
    
    if payment is None:
        return None
    
    return {
        "id": payment.id,
        "patrol_id": payment.patrol_id,
        "status": payment.status,
        "amount_cents": payment.amount_cents,
    }


@sync_to_async
def update_payment_status(
    payment_intent_id: str | None = None,
    paypal_transaction_id: str | None = None,
    status: str | None = None,
    completed_at: str | None = None,
    error_message: str = "",
    metadata: dict | None = None,
) -> dict:
    """Update payment status based on webhook data from Stripe or PayPal."""
    payment = None
    
    if payment_intent_id:
        payment = Payment.objects.filter(
            stripe_payment_intent_id=payment_intent_id
        ).first()
    elif paypal_transaction_id:
        payment = Payment.objects.filter(
            paypal_transaction_id=paypal_transaction_id
        ).first()
    
    if payment is None:
        return {"success": False, "error": "Payment not found"}
    
    # Update payment fields
    if status:
        payment.status = status
    if completed_at:
        payment.completed_at = completed_at
    if error_message:
        payment.error_message = error_message
    if metadata:
        # Merge metadata
        payment.metadata = {**payment.metadata, **metadata}
    
    payment.save()
    
    return {
        "success": True,
        "payment_id": payment.id,
        "status": payment.status,
    }


@sync_to_async
def get_patrol_payments(patrol_id: int) -> list[dict]:
    """Get all payments for a patrol."""
    payments = Payment.objects.filter(patrol_id=patrol_id).order_by("-created_at")
    
    return [
        {
            "id": p.id,
            "product_type": p.product_type,
            "amount_cents": p.amount_cents,
            "status": p.status,
            "payment_method": p.payment_method,
            "created_at": p.created_at.isoformat(),
        }
        for p in payments
    ]


@sync_to_async
def build_weekly_report_for_patrol(chat_id: int) -> dict:
    """
    Build the weekly learning report payload for a patrol leader.
    Covers the last 7 days of activity:
      - text messages validated
      - audios validated
      - YouTube missions completed
      - consistency bonuses earned
      - SEL points earned this week
      - estimated new Esperanto words practiced (1 text=1 word, 1 audio=3 words)
    """
    patrol = Patrol.objects.filter(telegram_chat_id=chat_id).first()
    if patrol is None:
        return {"success": False, "error": "patrol_not_found"}

    week_start = timezone.now() - timedelta(days=7)
    logs = PointLog.objects.filter(patrol=patrol, created_at__gte=week_start)

    texts = logs.filter(event_type=PointLog.EventType.TEXT_VALIDATED).count()
    audios = logs.filter(event_type=PointLog.EventType.AUDIO_VALIDATED).count()
    youtube = logs.filter(event_type=PointLog.EventType.YOUTUBE_MISSION).count()
    bonuses = logs.filter(event_type=PointLog.EventType.CONSISTENCY_BONUS).count()
    weekly_points = logs.aggregate(total=Sum("points")).get("total") or 0

    # Estimated word practice: each validated text ~ 1 word, each audio ~ 3 words
    estimated_words = (texts * 1) + (audios * 3) + (youtube * 5)

    return {
        "success": True,
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


def build_global_ranking(event_id: int | None = None, limit: int = 20) -> list[dict]:
    """
    Build the global ranking of patrols ordered by sel_points descending.
    Optionally scoped to a single event.
    Returns a list of dicts ready for admin display.
    """
    qs = Patrol.objects.select_related("event").filter(is_active=True)
    if event_id:
        qs = qs.filter(event_id=event_id)

    qs = qs.order_by("-sel_points")[:limit]

    ranking = []
    for rank, patrol in enumerate(qs, start=1):
        recent_window = timezone.now() - timedelta(days=7)
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
            }
        )
    return ranking


@sync_to_async
def get_or_create_mcer_certificate(chat_id: int) -> dict:
    """
    Get or create MCER certificate (Atestilo) for patrol by chat_id.
    
    Returns:
        {
            "ok": bool,
            "certificate_id": int,
            "patrol_name": str,
            "sister_patrol_name": str,
            "delegation_name": str,
            "mcer_level": str,
            "points": int,
            "certification_code": str,
            "qr_png_b64": str,
            "match_start_date": str,
            "leader_name": str,
            "leader_email": str,
            "with_watermark": bool,  # True if < 80% of B1 (2,401 pts)
            "progress_to_b1_pct": int,  # Percentage to B1 threshold
            "points_to_b1": int,  # Points remaining to reach B1
        }
    """
    from apps.scouting.models import MCERCertificate  # Import here to avoid circular
    
    patrol = Patrol.objects.select_related("event").filter(telegram_chat_id=chat_id).first()
    if patrol is None:
        return {"ok": False, "reason": "patrol_not_found"}
    
    # Get sister patrol from patrol match
    patrol_match = (
        PatrolMatch.objects.filter(
            Q(patrol_a=patrol) | Q(patrol_b=patrol),
            status=PatrolMatch.Status.ACTIVE,
        )
        .select_related("patrol_a", "patrol_b")
        .first()
    )
    
    sister_patrol = None
    match_start_date = None
    if patrol_match:
        sister_patrol = patrol_match.patrol_b if patrol_match.patrol_a_id == patrol.id else patrol_match.patrol_a
        match_start_date = patrol_match.matched_at.date()
    
    # Calculate progress with PoentaroEngine
    engine = PoentaroEngine()
    snapshot = engine.compute(patrol)
    
    effective_points = snapshot.effective_score
    mcer_level = snapshot.mcer_level
    
    # Calculate B1 progress (B1 starts at 3,001 pts)
    B1_THRESHOLD = 3001
    B1_80_PCT = 2401  # 80% of B1
    
    if effective_points >= B1_THRESHOLD:
        progress_to_b1_pct = 100
        points_to_b1 = 0
    else:
        progress_to_b1_pct = min(100, int((effective_points / B1_THRESHOLD) * 100))
        points_to_b1 = max(0, B1_THRESHOLD - effective_points)
    
    with_watermark = effective_points < B1_80_PCT
    
    # Get or create certificate
    cert = MCERCertificate.objects.filter(patrol=patrol).order_by("-issued_at").first()
    
    if cert is None or cert.points_at_issue < effective_points:
        # Generate QR code
        import qrcode
        import base64
        import io
        
        cert_code = f"MCER-{patrol.id}-{uuid.uuid4().hex[:8].upper()}"
        wall_of_fame_url = f"{os.getenv('DJANGO_PUBLIC_BASE_URL', 'http://localhost:8000')}/scouts/wall-of-fame/"
        
        qr = qrcode.QRCode(version=1, box_size=10, border=2)
        qr.add_data(wall_of_fame_url)
        qr.make(fit=True)
        
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format="PNG")
        qr_png_b64 = base64.b64encode(qr_buffer.getvalue()).decode("utf-8")
        
        cert = MCERCertificate.objects.create(
            patrol=patrol,
            sister_patrol=sister_patrol,
            mcer_level=mcer_level,
            points_at_issue=effective_points,
            certification_code=cert_code,
            qr_png_b64=qr_png_b64,
            match_start_date=match_start_date,
        )
    else:
        # Update preview tracking
        cert.preview_requested_count += 1
        cert.last_preview_requested_at = timezone.now()
        cert.save(update_fields=["preview_requested_count", "last_preview_requested_at"])
    
    return {
        "ok": True,
        "certificate_id": cert.id,
        "patrol_name": patrol.name,
        "sister_patrol_name": sister_patrol.name if sister_patrol else "Sin patrulla hermana",
        "delegation_name": patrol.delegation_name,
        "mcer_level": mcer_level,
        "points": effective_points,
        "certification_code": cert.certification_code,
        "qr_png_b64": cert.qr_png_b64,
        "match_start_date": match_start_date.strftime("%d/%m/%Y") if match_start_date else "Sin fecha",
        "leader_name": patrol.leader_name or "Scout Leader",
        "leader_email": patrol.leader_email or "",
        "with_watermark": with_watermark,
        "progress_to_b1_pct": progress_to_b1_pct,
        "points_to_b1": points_to_b1,
    }


@sync_to_async
def notify_leader_certificate_preview(chat_id: int) -> dict:
    """
    Send email notification to leader when patrol requests /atestilo.
    
    Returns:
        {"notified": bool, "leader_email": str}
    """
    from apps.scouting.models import MCERCertificate
    
    patrol = Patrol.objects.filter(telegram_chat_id=chat_id).first()
    if patrol is None or not patrol.leader_email:
        return {"notified": False, "leader_email": ""}
    
    cert = MCERCertificate.objects.filter(patrol=patrol).order_by("-issued_at").first()
    if cert is None:
        return {"notified": False, "leader_email": patrol.leader_email}
    
    # Check if we already notified recently (within 24 hours)
    if cert.leader_notified_at:
        time_since_last = timezone.now() - cert.leader_notified_at
        if time_since_last < timedelta(hours=24):
            return {"notified": False, "leader_email": patrol.leader_email, "reason": "recently_notified"}
    
    # Update notification timestamp
    cert.leader_notified_at = timezone.now()
    cert.save(update_fields=["leader_notified_at"])
    
    return {
        "notified": True,
        "leader_email": patrol.leader_email,
        "patrol_name": patrol.name,
        "points": cert.points_at_issue,
        "mcer_level": cert.mcer_level,
    }
