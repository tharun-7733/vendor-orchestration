from typing import Any


def normalize_kyc(raw: dict[str, Any]) -> dict[str, Any]:
    verified = raw.get("identity_match") is True
    return {
        "vendor": "kyc",
        "outcome": "clear" if verified else "failed",
        "matched": not verified,
        "confidence": raw.get("score"),
        "payload": raw,
        "error": None,
    }


def normalize_sanctions(raw: dict[str, Any]) -> dict[str, Any]:
    hits = raw.get("hits") or []
    return {
        "vendor": "sanctions",
        "outcome": "review" if hits else "clear",
        "matched": bool(hits),
        "confidence": max((hit.get("score", 0) for hit in hits), default=1.0),
        "payload": raw,
        "error": None,
    }
