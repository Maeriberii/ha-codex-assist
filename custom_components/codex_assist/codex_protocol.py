"""Codex Responses provider-state conversion for Home Assistant chat logs."""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CodexNativeState:
    """In-memory Responses items owned by this integration only.

    ChatLog allows one native object per assistant message.  A Responses round
    can contain both a reasoning item and a web-search/image item, so keep
    their provider order in one tagged state object.
    """

    items: tuple[dict[str, Any], ...]


def native_state_from_response_items(
    items: Iterable[dict[str, Any]],
) -> CodexNativeState | None:
    """Accept only Responses output items that require provider-native replay."""
    accepted = tuple(
        copy.deepcopy(item)
        for item in items
        if item.get("type")
        in {"reasoning", "web_search_call", "image_generation_call"}
    )
    return CodexNativeState(accepted) if accepted else None


def responses_items_from_content(contents: Iterable[Any]) -> list[dict[str, Any]]:
    """Convert already materialized HA content to Responses continuation items.

    User attachments are prepared before this boundary. Native state is accepted
    only when it is tagged by this integration, so another agent cannot inject
    arbitrary provider payloads through ``AssistantContent.native``.
    """
    items: list[dict[str, Any]] = []
    for content in contents:
        role = getattr(content, "role", None)
        if role == "tool_result":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": getattr(content, "tool_call_id", ""),
                    "output": json.dumps(getattr(content, "tool_result", None)),
                }
            )
            continue
        if role != "assistant":
            text = getattr(content, "content", None)
            if role == "user" and isinstance(text, str) and text:
                items.append({"role": role, "content": text})
            continue
        native = getattr(content, "native", None)
        if isinstance(native, CodexNativeState):
            summaries: list[str] = []
            thinking = getattr(content, "thinking_content", None)
            if isinstance(thinking, str) and thinking:
                summaries.append(thinking)
            for native_item in native.items:
                item = copy.deepcopy(native_item)
                if item.get("type") == "reasoning" and summaries:
                    item["summary"] = [
                        {"type": "summary_text", "text": summary}
                        for summary in summaries
                    ]
                    summaries = []
                items.append(item)
        text = getattr(content, "content", None)
        if isinstance(text, str) and text:
            items.append({"role": "assistant", "content": text})
        for tool_call in getattr(content, "tool_calls", None) or []:
            items.append(
                {
                    "type": "function_call",
                    "name": tool_call.tool_name,
                    "arguments": json.dumps(tool_call.tool_args),
                    "call_id": tool_call.id,
                }
            )
    return items


def stable_prompt_cache_key(entry_id: str, conversation_id: str) -> str:
    """Return a short opaque cache key without user or prompt content."""
    import hashlib

    digest = hashlib.sha256(f"{entry_id}:{conversation_id}".encode()).hexdigest()
    return f"ha-codex-assist-{digest[:40]}"
