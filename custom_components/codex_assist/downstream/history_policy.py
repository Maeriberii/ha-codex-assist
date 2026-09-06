"""Bounds for already-translated Responses replay items."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

MAX_HISTORY_ITEMS = 24
MAX_HISTORY_BYTES = 128 * 1024
RECENT_IMAGE_USER_TURNS = 2


def serialized_bytes(items: Sequence[dict[str, Any]]) -> int:
    """Return compact UTF-8 JSON size used by the replay budget."""
    return len(json.dumps(items, ensure_ascii=False, separators=(",", ":")).encode())


def retain_complete_turns(
    items: list[dict[str, Any]],
    *,
    max_items: int = MAX_HISTORY_ITEMS,
    max_bytes: int = MAX_HISTORY_BYTES,
) -> list[dict[str, Any]]:
    """Keep newest complete user-led groups without splitting tool chains."""
    if len(items) <= max_items and serialized_bytes(items) <= max_bytes:
        return items
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for item in items:
        if item.get("role") == "user" and current:
            groups.append(current)
            current = []
        current.append(item)
    if current:
        groups.append(current)

    selected: list[list[dict[str, Any]]] = []
    selected_items = 0
    selected_bytes = 2
    for group in reversed(groups):
        group_bytes = serialized_bytes(group) - 2
        separator_bytes = 1 if selected_items else 0
        if not selected and len(group) > max_items:
            raise ValueError(
                f"Current Codex turn contains {len(group)} items; maximum is {max_items}"
            )
        if selected and (
            selected_items + len(group) > max_items
            or selected_bytes + separator_bytes + group_bytes > max_bytes
        ):
            break
        selected.append(group)
        selected_items += len(group)
        selected_bytes += separator_bytes + group_bytes
    return [item for group in reversed(selected) for item in group]


def recent_user_content_indexes(contents: Sequence[Any]) -> set[int]:
    """Return only the user turns whose image attachments may be replayed."""
    user_indexes = [
        index for index, content in enumerate(contents) if getattr(content, "role", None) == "user"
    ]
    return set(user_indexes[-RECENT_IMAGE_USER_TURNS:])
