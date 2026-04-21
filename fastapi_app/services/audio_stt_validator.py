from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from urllib import error, request


API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
DEFAULT_MODEL = "gemini-1.5-flash"
_PROMPT_FILE = Path(__file__).resolve().parents[2] / "prompts" / "gemini_audio_stt_prompt.txt"


def _load_prompt() -> str:
    if _PROMPT_FILE.exists():
        return _PROMPT_FILE.read_text(encoding="utf-8").strip()
    return (
        "Escucha este audio de un scout. Transcribe lo que dice en Esperanto y evalúa su "
        "pronunciación en una escala del 1 al 5. Si no se entiende nada, pide amablemente que lo repita"
    )


def _parse_json_object(raw_text: str) -> dict:
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = raw_text[start : end + 1]
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed

    raise RuntimeError("Gemini STT response is not valid JSON")


def transcribe_and_score_audio(
    audio_path: str,
    *,
    model: str = DEFAULT_MODEL,
    timeout_seconds: int = 75,
) -> dict:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("Missing Gemini API key. Use GEMINI_API_KEY.")

    file_path = Path(audio_path)
    if not file_path.exists():
        raise ValueError(f"Audio file not found: {audio_path}")

    encoded_audio = base64.b64encode(file_path.read_bytes()).decode("utf-8")
    prompt = _load_prompt()
    user_prompt = (
        f"{prompt}. "
        "Responde SOLO un JSON con claves exactas: "
        "transcript_text (string), pronunciation_score (integer 1-5), should_repeat (boolean), "
        "feedback_message (string corta)."
    )

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": user_prompt},
                    {"inlineData": {"mimeType": "audio/mpeg", "data": encoded_audio}},
                ],
            }
        ],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 300},
    }

    req = request.Request(
        url=API_URL_TEMPLATE.format(model=model, api_key=api_key),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini STT HTTP {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc

    parsed = json.loads(raw)
    candidates = parsed.get("candidates") or []
    if not candidates:
        raise RuntimeError("No candidates from Gemini STT")

    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    if not parts or "text" not in parts[0]:
        raise RuntimeError("No text output from Gemini STT")

    obj = _parse_json_object(parts[0]["text"].strip())

    transcript = str(obj.get("transcript_text") or "").strip()
    score = obj.get("pronunciation_score")
    should_repeat = bool(obj.get("should_repeat"))
    feedback = str(obj.get("feedback_message") or "").strip()

    if not isinstance(score, int):
        raise RuntimeError("pronunciation_score must be integer")

    if score < 1:
        score = 1
    if score > 5:
        score = 5

    return {
        "transcript_text": transcript,
        "pronunciation_score": score,
        "should_repeat": should_repeat,
        "feedback_message": feedback,
    }
