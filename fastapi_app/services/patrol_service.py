from fastapi_app.db_bridge import (
    add_training_points,
    award_points_by_chat,
    bind_chat_to_patrol_token,
    build_certification_qr_payload,
    capture_match_celebration_interaction,
    create_or_update_youtube_submission_by_chat,
    create_rover_incident_by_chat,
    get_or_create_mcer_certificate,
    get_patrol_by_chat_id,
    get_registration_status,
    notify_leader_certificate_preview,
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


async def award_patrol_points(
    chat_id: int,
    *,
    event_type: str,
    external_ref: str = "",
    metadata: dict | None = None,
) -> dict:
    return await award_points_by_chat(
        chat_id,
        event_type=event_type,
        external_ref=external_ref,
        metadata=metadata,
    )


async def get_certification_qr_payload(patrol_id: int) -> dict:
    return await build_certification_qr_payload(patrol_id)


async def create_youtube_submission_by_chat(
    chat_id: int,
    *,
    youtube_url: str,
    validation_result: dict,
    audit_result: dict,
) -> dict:
    return await create_or_update_youtube_submission_by_chat(
        chat_id,
        youtube_url=youtube_url,
        validation_result=validation_result,
        audit_result=audit_result,
    )


async def create_rover_incident(chat_id: int, *, description: str) -> dict:
    return await create_rover_incident_by_chat(chat_id, description=description)


async def get_mcer_certificate(chat_id: int) -> dict:
    """Get or create MCER certificate (Atestilo) for patrol."""
    return await get_or_create_mcer_certificate(chat_id)


async def notify_leader_about_certificate(chat_id: int) -> dict:
    """Notify leader when patrol requests certificate preview."""
    return await notify_leader_certificate_preview(chat_id)
