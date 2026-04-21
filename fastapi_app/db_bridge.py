import os
import uuid

import django
from asgiref.sync import sync_to_async
from django.db import transaction
from django.db.models import Q


if not os.getenv("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django.setup()

from apps.scouting.models import Patrol, PatrolMatch  # noqa: E402


def _serialize_patrol(patrol: Patrol | None) -> dict | None:
    if patrol is None:
        return None
    return {
        "id": patrol.id,
        "name": patrol.name,
        "delegation_name": patrol.delegation_name,
        "event_id": patrol.event_id,
        "telegram_chat_id": patrol.telegram_chat_id,
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
    if match is not None:
        sibling = match.patrol_b if match.patrol_a_id == patrol.id else match.patrol_a
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
        "patrol": _serialize_patrol(patrol),
        "sister_patrol": sister_patrol,
    }
