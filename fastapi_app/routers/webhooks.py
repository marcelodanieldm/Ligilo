from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from fastapi_app.database import get_db
from fastapi_app.services.media_pipeline import build_media_metadata
from fastapi_app.services.safe_from_harm import find_prohibited_terms
from fastapi_app.services.telegram_bot import process_telegram_update

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class TelegramWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str = "telegram"
    provider_media_id: str | None = None
    media_kind: str = Field(pattern="^(audio|video)$")
    storage_bucket: str
    storage_path: str
    mime_type: str | None = None
    duration_seconds: float | None = None
    size_bytes: int | None = None
    width: int | None = None
    height: int | None = None
    transcript_text: str = ""
    language_code: str | None = None
    captured_at: str | None = None


@router.post("/telegram")
async def telegram_webhook(update_payload: dict) -> dict[str, str]:
    try:
        await process_telegram_update(update_payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return {"status": "ok", "detail": "Telegram update processed"}


@router.post("/media")
def media_webhook(payload: TelegramWebhookPayload, db: Session = Depends(get_db)) -> dict[str, str | bool]:
    prohibited_terms = find_prohibited_terms(payload.transcript_text)
    if prohibited_terms:
        db.execute(
            text(
                """
                insert into public.ligilo_safe_from_harm
                    (source, matched_terms, input_excerpt, blocked)
                values
                    (:source, :matched_terms, :input_excerpt, true)
                """
            ),
            {
                "source": payload.provider,
                "matched_terms": prohibited_terms,
                "input_excerpt": "[REDACTED_BY_SAFE_FROM_HARM]",
            },
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "blocked": True,
                "reason": "safe_from_harm",
                "matched_terms": prohibited_terms,
            },
        )

    metadata = build_media_metadata(payload.model_dump())
    db.execute(
        text(
            """
            insert into public.ligilo_media_metadata
                (
                    provider,
                    provider_media_id,
                    media_kind,
                    storage_bucket,
                    storage_path,
                    content_hash,
                    mime_type,
                    duration_seconds,
                    size_bytes,
                    width,
                    height,
                    transcript_excerpt,
                    language_code,
                    captured_at
                )
            values
                (
                    :provider,
                    :provider_media_id,
                    :media_kind,
                    :storage_bucket,
                    :storage_path,
                    :content_hash,
                    :mime_type,
                    :duration_seconds,
                    :size_bytes,
                    :width,
                    :height,
                    :transcript_excerpt,
                    :language_code,
                    :captured_at
                )
            on conflict (content_hash) do update
            set
                transcript_excerpt = excluded.transcript_excerpt,
                language_code = excluded.language_code,
                captured_at = excluded.captured_at
            """
        ),
        metadata,
    )

    db.execute(
        text(
            """
            insert into public.ligilo_ingestion_events
                (source, event_type, event_ts, payload)
            values
                (:source, :event_type, :event_ts, cast(:payload as jsonb))
            """
        ),
        {
            "source": payload.provider,
            "event_type": "media_metadata_ingested",
            "event_ts": datetime.now(tz=timezone.utc),
            "payload": payload.model_dump_json(),
        },
    )
    db.commit()

    return {
        "status": "ok",
        "stored": True,
        "blocked": False,
        "detail": "Media metadata guardada en Supabase",
    }
