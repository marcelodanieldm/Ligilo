import hashlib
import os
from datetime import datetime, timezone


def _to_iso_timestamp(raw_value: str | None) -> datetime:
    if not raw_value:
        return datetime.now(tz=timezone.utc)

    value = raw_value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_media_metadata(payload: dict) -> dict:
    transcript_excerpt_limit = int(os.getenv("MEDIA_TRANSCRIPT_EXCERPT_LIMIT", "280"))

    provider = payload.get("provider", "telegram")
    provider_media_id = payload.get("provider_media_id")
    storage_bucket = payload["storage_bucket"]
    storage_path = payload["storage_path"]
    media_kind = payload["media_kind"]

    hash_base = "|".join(
        [
            str(provider),
            str(provider_media_id or ""),
            str(storage_bucket),
            str(storage_path),
            str(payload.get("size_bytes") or ""),
            str(payload.get("duration_seconds") or ""),
        ]
    )
    content_hash = hashlib.sha256(hash_base.encode("utf-8")).hexdigest()

    transcript_excerpt = (payload.get("transcript_text") or "")[:transcript_excerpt_limit]

    # Ni konservas nur metadatumojn por eviti stokadan saturigon.
    return {
        "provider": provider,
        "provider_media_id": provider_media_id,
        "media_kind": media_kind,
        "storage_bucket": storage_bucket,
        "storage_path": storage_path,
        "content_hash": content_hash,
        "mime_type": payload.get("mime_type"),
        "duration_seconds": payload.get("duration_seconds"),
        "size_bytes": payload.get("size_bytes"),
        "width": payload.get("width"),
        "height": payload.get("height"),
        "transcript_excerpt": transcript_excerpt,
        "language_code": payload.get("language_code"),
        "captured_at": _to_iso_timestamp(payload.get("captured_at")),
    }
