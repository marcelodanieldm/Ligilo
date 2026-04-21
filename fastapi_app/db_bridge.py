import os
import uuid
from datetime import timedelta
import json
from urllib.parse import quote

import django
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.db.models import Q
from django.db.models import Sum
from django.utils import timezone


if not os.getenv("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django.setup()

from apps.scouting.models import AuditLog, MatchCelebrationEvent, Patrol, PatrolMatch, Payment, PointLog  # noqa: E402


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
    }


POINT_RULES = {
    PointLog.EventType.TEXT_VALIDATED: 10,
    PointLog.EventType.AUDIO_VALIDATED: 50,
    PointLog.EventType.YOUTUBE_MISSION: 500,
}


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
    return {"awarded": True, "reason": "ok", "points": points, "sel_points": patrol.sel_points}


@sync_to_async
def build_certification_qr_payload(patrol_id: int) -> dict:
    patrol = Patrol.objects.select_related("event").filter(pk=patrol_id).first()
    if patrol is None:
        return {"eligible": False, "reason": "patrol_not_found"}

    total_logs = (
        PointLog.objects.filter(patrol=patrol).aggregate(total=Sum("points")).get("total") or 0
    )
    effective_points = max(patrol.sel_points, int(total_logs))
    if effective_points < 1000:
        return {
            "eligible": False,
            "reason": "insufficient_points",
            "current_points": effective_points,
            "required_points": 1000,
        }

    issued_at = timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    certification_code = f"SEL-{patrol.event_id:03d}-{patrol.id:04d}-{timezone.now().strftime('%Y%m%d')}"
    payload = {
        "certification_code": certification_code,
        "patrol_id": patrol.id,
        "patrol_name": patrol.name,
        "delegation_name": patrol.delegation_name,
        "event": patrol.event.name,
        "points": effective_points,
        "issued_at": issued_at,
    }
    qr_data = quote(json.dumps(payload, ensure_ascii=False), safe="")
    qr_url = f"https://quickchart.io/qr?size=300&text={qr_data}"
    return {
        "eligible": True,
        "payload": payload,
        "qr_url": qr_url,
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
