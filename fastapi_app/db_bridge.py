import os

import django
from asgiref.sync import sync_to_async
from django.db import transaction


if not os.getenv("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django.setup()

from apps.scouting.models import Patrol  # noqa: E402


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
    normalized_token = token.strip().upper()
    if not normalized_token:
        return {"status": "invalid_token"}

    # La transakcio certigas konsekvencan ligon inter token kaj chat_id.
    with transaction.atomic():
        patrol = (
            Patrol.objects.select_for_update()
            .select_related("event")
            .filter(invitation_token=normalized_token)
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
        patrol.save(update_fields=["telegram_chat_id", "updated_at"])

    return {
        "status": "bound",
        "patrol": _serialize_patrol(patrol),
    }
