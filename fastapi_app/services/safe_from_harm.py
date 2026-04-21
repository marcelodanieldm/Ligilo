import os
import re
import unicodedata


def _normalize(value: str) -> str:
    lowered = value.lower()
    normalized = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _load_blocklist() -> list[str]:
    # Listo agordebla per medio por produktaj medioj.
    raw = os.getenv(
        "SAFE_FROM_HARM_TERMS",
        "violencia,abuso,autolesion,bomba,arma,matar,odio,acoso",
    )
    terms = [term.strip() for term in raw.split(",") if term.strip()]
    return sorted({_normalize(term) for term in terms})


def find_prohibited_terms(text: str) -> list[str]:
    normalized = _normalize(text)
    found: list[str] = []

    for term in _load_blocklist():
        if not term:
            continue
        pattern = rf"\b{re.escape(term)}\b"
        if re.search(pattern, normalized):
            found.append(term)

    return found
