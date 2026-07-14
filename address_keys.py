from __future__ import annotations

import re


ROAD_ADDRESS_PATTERN = re.compile(r"([0-9가-힣]+(?:대로|로|길))\s*(\d+(?:-\d+)?)")
LOT_ADDRESS_PATTERN = re.compile(r"([0-9가-힣]+(?:동|리))\s*(\d+(?:-\d+)?)")


def compact_address(value: str | None) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", str(value or "").lower())


def match_key(parts: tuple[str, ...]) -> str:
    normalized = [re.sub(r"[^0-9a-z가-힣-]", "", part.lower()).replace("-", "_") for part in parts if part]
    return "".join(normalized)


def address_key(value: str | None, fallback_pattern: str | None = None) -> str:
    """Return a building-level road or lot key, never an administrative-area-only key."""
    text = re.sub(r"\s+", " ", str(value or "")).strip().replace("울산광역시", "울산").replace(".", "")

    for pattern in (ROAD_ADDRESS_PATTERN, LOT_ADDRESS_PATTERN):
        match = pattern.search(text)
        if match:
            return match_key(match.groups())

    if fallback_pattern:
        match = re.search(fallback_pattern, text)
        if match and any(re.search(r"\d", part or "") for part in match.groups()):
            return match_key(match.groups())
    return ""
