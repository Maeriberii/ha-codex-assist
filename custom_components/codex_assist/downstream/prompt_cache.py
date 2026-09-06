"""Opaque Responses prompt-cache partitions."""

from __future__ import annotations

import hashlib


def prompt_cache_key(entry_id: str, stable_scope: object) -> str | None:
    """Return a deterministic opaque key only for a stable conversation/task scope."""
    if not isinstance(stable_scope, str) or not stable_scope:
        return None
    return hashlib.sha256(f"{entry_id}\0{stable_scope}".encode()).hexdigest()
