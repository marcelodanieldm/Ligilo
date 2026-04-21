from __future__ import annotations

import json
import os
from pathlib import Path
from urllib import error, request


API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
DEFAULT_MODEL = "gemini-1.5-flash"

_PROMPT_FILE = Path(__file__).resolve().parents[2] / "prompts" / "gemini_training_tutor_system_prompt.txt"


def _load_system_prompt() -> str:
    if _PROMPT_FILE.exists():
        return _PROMPT_FILE.read_text(encoding="utf-8")
    return (
        "Actua como la patrulla virtual Stelo, da la bienvenida y propone 3 retos basicos "
        "de Esperanto mientras llega un match real."
    )


def _call_gemini(*, api_key: str, model: str, user_text: str, timeout_seconds: int) -> str:
    payload = {
        "system_instruction": {"parts": [{"text": _load_system_prompt()}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {"temperature": 0.35, "maxOutputTokens": 350},
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
        raise RuntimeError(f"Gemini HTTP {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc

    parsed = json.loads(raw)
    candidates = parsed.get("candidates") or []
    if not candidates:
        raise RuntimeError("No candidates from Gemini tutor")

    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    if not parts or "text" not in parts[0]:
        raise RuntimeError("No text part from Gemini tutor")

    return parts[0]["text"].strip()


def generate_training_tutor_reply(
    scout_text: str,
    *,
    model: str = DEFAULT_MODEL,
    timeout_seconds: int = 45,
) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return (
            "Soy Stelo, tu patrulla virtual de entrenamiento. Mientras llega tu match internacional, "
            "vamos con 3 retos: 1) Preséntate en Esperanto. 2) Escribe una ubicacion segura. "
            "3) Responde con un saludo a otra patrulla: Saluton, amikoj!"
        )

    tutor_prompt = (
        "Mensaje del scout:\n"
        f"{scout_text}\n\n"
        "Responde como Stelo con guia breve y, si corresponde, propone 3 retos basicos de Esperanto."
    )
    try:
        return _call_gemini(
            api_key=api_key,
            model=model,
            user_text=tutor_prompt,
            timeout_seconds=timeout_seconds,
        )
    except RuntimeError:
        return (
            "Soy Stelo. Seguimos entrenando: 1) Escribe 'Ni pretas lerni'. "
            "2) Da una instruccion corta de patrulla en Esperanto. "
            "3) Cierra con 'Saluton, amikoj!'."
        )
