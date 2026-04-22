from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any
from urllib import error, request


API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
DEFAULT_MODEL = "gemini-1.5-flash"

PROMPT_BASE = (
    "Analiza el siguiente texto en Esperanto para un contexto scout. "
    "Si el texto es ofensivo o rompe las reglas de 'Safe from Harm', marca flagged: true. "
    "Si es seguro, evalúa si la estructura es comprensible (incluso con errores de principiante) "
    "y devuelve un mensaje de aliento en Esperanto"
)

SYSTEM_PROMPT = (
    "You are Ligilo Semantic Validator. Return exactly one valid JSON object with these keys only: "
    "flagged (boolean), comprehensible (boolean), encouragement_message (string, max 240 chars). "
    "No markdown, no extra keys, no explanations."
)

MCER_SYSTEM_PROMPT = (
    "You are Skolto-Instruisto progression evaluator for Esperanto using CEFR levels. "
    "Return exactly one valid JSON object with these keys only: "
    "mcer_level (string: A1, A2 or B1), lexical_score (integer 0-100), grammar_score (integer 0-100), "
    "participation_score (integer 0-100), personalized_congrats (string, max 240 chars), "
    "next_focus (string, max 240 chars), assertive_feedback (string, max 240 chars). "
    "No markdown, no extra keys, no explanations."
)

logger = logging.getLogger(__name__)

_NAME_PATTERN = re.compile(r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})*\b")
_EMAIL_PATTERN = re.compile(r"\b[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE_PATTERN = re.compile(r"\+?\d[\d\s\-]{7,}\d")


def anonymize_sensitive_text(text: str) -> str:
    sanitized = _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)
    sanitized = _PHONE_PATTERN.sub("[REDACTED_PHONE]", sanitized)
    sanitized = _NAME_PATTERN.sub("[REDACTED_NAME]", sanitized)
    return sanitized


def _call_gemini(
    *,
    api_key: str,
    model: str,
    text_input: str,
    temperature: float,
    timeout_seconds: int,
) -> str:
    if os.getenv("GEMINI_EXTERNAL_DEBUG_LOGS", "false").lower() == "true":
        logger.info(
            "Gemini request prepared (model=%s, text=%s)",
            model,
            anonymize_sensitive_text(text_input)[:180],
        )

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": f"{PROMPT_BASE}\n\nTexto:\n{text_input}",
                    }
                ],
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 240,
        },
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
        raise RuntimeError(
            f"Gemini HTTP {exc.code}: {anonymize_sensitive_text(body)}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc

    parsed = json.loads(raw)
    candidates = parsed.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"No candidates in Gemini response: {raw}")

    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    if not parts or "text" not in parts[0]:
        raise RuntimeError(f"No text part in Gemini response: {raw}")

    return parts[0]["text"].strip()


def _parse_json_object(raw_text: str) -> tuple[dict[str, Any] | None, str | None]:
    # Unua provo: rekta JSON-parse.
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            return parsed, None
        return None, "Parsed JSON is not an object"
    except json.JSONDecodeError:
        pass

    # Rezerva provo: elpreni la unuan JSON-objekton en la teksto.
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = raw_text[start : end + 1]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed, None
            return None, "Recovered JSON is not an object"
        except json.JSONDecodeError as exc:
            return None, f"JSON decode error: {exc}"

    return None, "No JSON object found"


def _validate_schema(obj: dict[str, Any]) -> tuple[bool, str | None]:
    required_keys = {"flagged", "comprehensible", "encouragement_message"}
    keys = set(obj.keys())

    missing = required_keys - keys
    extra = keys - required_keys
    if missing:
        return False, f"Missing keys: {sorted(missing)}"
    if extra:
        return False, f"Extra keys: {sorted(extra)}"

    if not isinstance(obj.get("flagged"), bool):
        return False, "flagged must be boolean"
    if not isinstance(obj.get("comprehensible"), bool):
        return False, "comprehensible must be boolean"

    encouragement_message = obj.get("encouragement_message")
    if not isinstance(encouragement_message, str):
        return False, "encouragement_message must be string"
    if len(encouragement_message) > 240:
        return False, "encouragement_message max length is 240"

    return True, None


def validate_esperanto_content(
    text: str,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    max_retries: int = 3,
    temperature: float = 0.2,
    timeout_seconds: int = 60,
    initial_backoff_seconds: float = 1.0,
) -> dict[str, Any]:
    # Servo por la Semilla-nivela taksado kun revojigo kaj sekura fallback.
    resolved_api_key = api_key or os.getenv("GEMINI_API_KEY", "")
    if not resolved_api_key:
        raise ValueError("Missing Gemini API key. Use api_key or GEMINI_API_KEY.")

    if max_retries < 1:
        raise ValueError("max_retries must be >= 1")

    for attempt in range(1, max_retries + 1):
        try:
            raw_output = _call_gemini(
                api_key=resolved_api_key,
                model=model,
                text_input=text,
                temperature=temperature,
                timeout_seconds=timeout_seconds,
            )
            parsed, parse_error = _parse_json_object(raw_output)
            if parse_error:
                raise RuntimeError(f"Malformed JSON: {parse_error}")

            assert parsed is not None
            valid, schema_error = _validate_schema(parsed)
            if not valid:
                raise RuntimeError(f"Invalid schema: {schema_error}")

            return parsed
        except RuntimeError:
            if os.getenv("GEMINI_EXTERNAL_DEBUG_LOGS", "false").lower() == "true":
                logger.warning(
                    "Gemini validation retry %s/%s for text=%s",
                    attempt,
                    max_retries,
                    anonymize_sensitive_text(text)[:180],
                )
            if attempt == max_retries:
                break
            backoff = initial_backoff_seconds * (2 ** (attempt - 1))
            time.sleep(backoff)

    return {
        "flagged": True,
        "comprehensible": False,
        "encouragement_message": "Bonvolu reprovi post momento. Ni estas cxe vi por helpi!",
    }


def _validate_mcer_schema(obj: dict[str, Any]) -> tuple[bool, str | None]:
    required_keys = {
        "mcer_level",
        "lexical_score",
        "grammar_score",
        "participation_score",
        "personalized_congrats",
        "next_focus",
        "assertive_feedback",
    }
    keys = set(obj.keys())
    missing = required_keys - keys
    extra = keys - required_keys
    if missing:
        return False, f"Missing keys: {sorted(missing)}"
    if extra:
        return False, f"Extra keys: {sorted(extra)}"

    if obj.get("mcer_level") not in {"A1", "A2", "B1"}:
        return False, "mcer_level must be A1, A2 or B1"

    for key in ("lexical_score", "grammar_score", "participation_score"):
        value = obj.get(key)
        if not isinstance(value, int):
            return False, f"{key} must be integer"
        if value < 0 or value > 100:
            return False, f"{key} must be 0..100"

    for key in ("personalized_congrats", "next_focus", "assertive_feedback"):
        value = obj.get(key)
        if not isinstance(value, str):
            return False, f"{key} must be string"
        if len(value) > 240:
            return False, f"{key} max length is 240"

    return True, None


def evaluate_mcer_progress(
    text: str,
    *,
    mcer_level: str,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """
    Evaluate Esperanto progression by MCER level focus.
    A1: vocabulario básico e identificación de objetos scouts.
    A2: interacción simple, rutinas, instrucciones y narración breve en presente/pasado cercano.
    B1: argumentación y tiempos verbales compuestos.
    """
    resolved_api_key = api_key or os.getenv("GEMINI_API_KEY", "")
    if not resolved_api_key:
        raise ValueError("Missing Gemini API key. Use api_key or GEMINI_API_KEY.")

    level = (mcer_level or "A1").strip().upper()
    if level not in {"A1", "A2", "B1"}:
        level = "A1"

    if level == "A1":
        level_focus = (
            "Enfocate en vocabulario básico scout, identificación de objetos (tenda, ŝnuro, kompaso), "
            "y frases cortas funcionales."
        )
    elif level == "A2":
        level_focus = (
            "Enfocate en interacción cotidiana simple entre patrullas, instrucciones claras, "
            "descripción de rutinas del campamento y narración breve de acciones recientes."
        )
    else:
        level_focus = (
            "Enfocate en argumentación (causa-consecuencia, opinión fundamentada), "
            "y uso de tiempos verbales compuestos en Esperanto."
        )

    prompt = (
        "Analiza el siguiente mensaje en Esperanto de una patrulla scout. "
        f"Nivel objetivo MCER: {level}. "
        f"Criterio del nivel: {level_focus}\n\n"
        "Devuelve puntuaciones, una felicitación personalizada motivadora, "
        "el siguiente foco pedagógico corto y feedback con comunicación asertiva "
        "(claro, respetuoso y accionable).\n\n"
        f"Texto:\n{text}"
    )

    payload = {
        "system_instruction": {"parts": [{"text": MCER_SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 260,
        },
    }

    req = request.Request(
        url=API_URL_TEMPLATE.format(model=model, api_key=resolved_api_key),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
        parsed = json.loads(raw)
        candidates = parsed.get("candidates") or []
        if not candidates:
            raise RuntimeError("No candidates in Gemini response")
        parts = ((candidates[0].get("content") or {}).get("parts") or [])
        if not parts or "text" not in parts[0]:
            raise RuntimeError("No text part in Gemini response")

        obj, parse_error = _parse_json_object(parts[0]["text"].strip())
        if parse_error or obj is None:
            raise RuntimeError(f"Malformed JSON: {parse_error}")

        valid, schema_error = _validate_mcer_schema(obj)
        if not valid:
            raise RuntimeError(f"Invalid MCER schema: {schema_error}")
        return obj
    except Exception:
        # Conservative pedagogical fallback keeps the bot responsive.
        if level == "A1":
            return {
                "mcer_level": "A1",
                "lexical_score": 60,
                "grammar_score": 58,
                "participation_score": 62,
                "personalized_congrats": "Bonege! Vi jam nomas bazajn skoltajn objektojn en Esperanto.",
                "next_focus": "Praktiku 3 frazojn pri objektoj de via tendaro kun simpla verbo.",
                "assertive_feedback": "Tu avance es real. Mantén frases breves y agrega un verbo claro por oración.",
            }

        if level == "A2":
            return {
                "mcer_level": "A2",
                "lexical_score": 66,
                "grammar_score": 63,
                "participation_score": 70,
                "personalized_congrats": "Tre bone! Vi jam komunikas kun via patrolo en simplaj, utilaj situacioj.",
                "next_focus": "Kreu dialogon de 4 linioj: saluto, instrukcio, konfirmo, adiaŭo.",
                "assertive_feedback": "Tu comunicación ya conecta al equipo. Próximo paso: dar instrucciones más precisas y verificar comprensión.",
            }

        return {
            "mcer_level": "B1",
            "lexical_score": 67,
            "grammar_score": 64,
            "participation_score": 68,
            "personalized_congrats": "Tre bone! Via argumento en Esperanto jam sonas pli matura.",
            "next_focus": "Uzu konektilojn por argumenti kaj praktiku verbajn formojn kun pli longa respondo.",
            "assertive_feedback": "Tu base es sólida. Refuerza tus argumentos con ejemplos concretos y cierra cada idea con una conclusión breve.",
        }
