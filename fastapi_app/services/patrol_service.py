from fastapi_app.db_bridge import (
    add_training_points,
    bind_chat_to_patrol_token,
    capture_match_celebration_interaction,
    get_patrol_by_chat_id,
    get_registration_status,
    prepare_match_celebration_payloads,
)


async def find_patrol_by_chat_id(chat_id: int) -> dict | None:
    return await get_patrol_by_chat_id(chat_id)


async def bind_chat_with_invitation_token(chat_id: int, token: str) -> dict:
    return await bind_chat_to_patrol_token(chat_id, token)


async def get_scout_registration_status(chat_id: int) -> dict:
    return await get_registration_status(chat_id)


async def get_match_celebration_payloads(chat_id: int) -> list[dict]:
    return await prepare_match_celebration_payloads(chat_id)


async def mark_match_celebration_interaction(chat_id: int) -> None:
    await capture_match_celebration_interaction(chat_id)


async def increase_training_points(chat_id: int, points: int = 1) -> int:
    return await add_training_points(chat_id, points)
