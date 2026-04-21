from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path


def _base_output_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "outputs"


def store_success_audio_sample(source_path: Path, *, patrol_id: int | None) -> dict[str, str]:
    storage_mode = os.getenv("MEDIA_STORAGE_MODE", "local").strip().lower()
    if storage_mode == "s3":
        try:
            import boto3  # type: ignore
        except ImportError:
            storage_mode = "local"
        else:
            bucket = os.getenv("MEDIA_S3_BUCKET", "")
            if bucket:
                key = _build_success_key(source_path.name, patrol_id=patrol_id)
                boto3.client("s3").upload_file(str(source_path), bucket, key)
                return {
                    "storage_bucket": bucket,
                    "storage_path": key,
                    "storage_mode": "s3",
                }
            storage_mode = "local"

    success_dir = _base_output_dir() / "success_samples"
    success_dir.mkdir(parents=True, exist_ok=True)
    target_path = success_dir / _build_success_filename(source_path.name, patrol_id=patrol_id)
    shutil.copy2(source_path, target_path)
    return {
        "storage_bucket": "local-success-samples",
        "storage_path": str(target_path),
        "storage_mode": storage_mode,
    }


def _build_success_key(file_name: str, *, patrol_id: int | None) -> str:
    today = datetime.utcnow().strftime("%Y/%m/%d")
    patrol_part = f"patrol_{patrol_id}" if patrol_id else "patrol_unknown"
    return f"success_samples/{today}/{patrol_part}_{file_name}"


def _build_success_filename(file_name: str, *, patrol_id: int | None) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    patrol_part = f"patrol_{patrol_id}" if patrol_id else "patrol_unknown"
    return f"{timestamp}_{patrol_part}_{file_name}"
