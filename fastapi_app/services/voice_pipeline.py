from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, parse, request


_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _base_output_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "outputs"


def extract_youtube_video_id(raw_url: str) -> str | None:
    try:
        parsed = parse.urlparse(raw_url.strip())
    except ValueError:
        return None

    host = parsed.netloc.lower()
    path = parsed.path.strip("/")

    if host in {"youtu.be", "www.youtu.be"}:
        candidate = path.split("/")[0] if path else ""
        return candidate if _YOUTUBE_ID_RE.match(candidate) else None

    if "youtube.com" in host:
        if path == "watch":
            query = parse.parse_qs(parsed.query)
            candidate = (query.get("v") or [""])[0]
            return candidate if _YOUTUBE_ID_RE.match(candidate) else None
        if path.startswith("shorts/") or path.startswith("embed/"):
            candidate = path.split("/")[1] if len(path.split("/")) > 1 else ""
            return candidate if _YOUTUBE_ID_RE.match(candidate) else None

    return None


async def download_and_convert_voice(
    *,
    telegram_file,
    chat_id: int,
    target_ext: str = "wav",
) -> dict[str, str]:
    now_token = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    media_root = _base_output_dir() / "media" / "voice"
    raw_dir = media_root / "raw"
    converted_dir = media_root / "converted"
    raw_dir.mkdir(parents=True, exist_ok=True)
    converted_dir.mkdir(parents=True, exist_ok=True)

    raw_path = raw_dir / f"chat_{chat_id}_{now_token}.ogg"
    converted_path = converted_dir / f"chat_{chat_id}_{now_token}.{target_ext}"

    await telegram_file.download_to_drive(custom_path=str(raw_path))
    await _convert_with_ffmpeg(raw_path=raw_path, converted_path=converted_path)

    return {
        "raw_path": str(raw_path),
        "converted_path": str(converted_path),
    }


async def _convert_with_ffmpeg(*, raw_path: Path, converted_path: Path) -> None:
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        str(raw_path),
        str(converted_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(
            "ffmpeg conversion failed: " + stderr.decode("utf-8", errors="replace")[-300:]
        )


def send_for_transcription(job: dict) -> dict:
    webhook_url = os.getenv("TRANSCRIPTION_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return _enqueue_transcription_job(job)

    req = request.Request(
        url=webhook_url,
        data=json.dumps(job).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except (error.URLError, error.HTTPError) as exc:
        return {
            "status": "deferred",
            "reason": str(exc),
            "job": _enqueue_transcription_job(job),
        }

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = {"raw_response": body}

    result = {"status": "sent", "response": parsed}
    transcript = parsed.get("transcript_text") if isinstance(parsed, dict) else None
    if isinstance(transcript, str):
        result["transcript_text"] = transcript
    return result


def _enqueue_transcription_job(job: dict) -> dict:
    queue_dir = _base_output_dir() / "transcription_jobs"
    queue_dir.mkdir(parents=True, exist_ok=True)
    job_id = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    job_path = queue_dir / f"job_{job_id}.json"
    job_path.write_text(json.dumps(job, ensure_ascii=True, indent=2), encoding="utf-8")
    return {
        "status": "queued",
        "job_path": str(job_path),
        "job_id": job_id,
    }
