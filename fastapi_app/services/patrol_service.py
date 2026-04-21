from fastapi_app.db_bridge import bind_chat_to_patrol_token, get_patrol_by_chat_id


async def find_patrol_by_chat_id(chat_id: int) -> dict | None:
    return await get_patrol_by_chat_id(chat_id)


async def bind_chat_with_invitation_token(chat_id: int, token: str) -> dict:
    return await bind_chat_to_patrol_token(chat_id, token)
