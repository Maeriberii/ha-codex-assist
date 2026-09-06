"""Explicit Home Assistant LLM API allowlist policy."""

from __future__ import annotations

from typing import Any


def normalize_selection(value: Any) -> list[str]:
    """Normalize legacy single values and remove duplicates."""
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(item for item in value if isinstance(item, str) and item))


def default_selection(value: Any, *, assist_api_id: str) -> list[str]:
    """Return saved explicit selection or the conservative Assist default."""
    return normalize_selection(value) or [assist_api_id]


def valid_explicit_selection(value: Any) -> bool:
    """An options form may not save an empty explicit allowlist."""
    return bool(normalize_selection(value))
