"""Compact, deterministic JSON serialization at integration boundaries."""

from __future__ import annotations

import json
from typing import Any


def dumps_text(value: Any, *, sort_keys: bool = False) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=sort_keys)


def dumps_bytes(value: Any, *, sort_keys: bool = False) -> bytes:
    return dumps_text(value, sort_keys=sort_keys).encode()


def loads(value: str | bytes | bytearray) -> Any:
    return json.loads(value)


def serialized_size(value: Any, *, sort_keys: bool = False) -> int:
    return len(dumps_bytes(value, sort_keys=sort_keys))
