"""Home Assistant chat-log translation and replay retention for Responses."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

try:
    from homeassistant.components import conversation
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import llm
except ImportError:  # pragma: no cover - permits pure retention-policy tests
    conversation = Any
    HomeAssistant = Any
    llm = Any

from .codex_client import codex_user_content_with_images
from .codex_protocol import CodexNativeState
from .serialization import dumps_text, serialized_size

MAX_HISTORY_ITEMS = 24
MAX_HISTORY_BYTES = 128 * 1024
RECENT_IMAGE_USER_TURNS = 2
MAX_IMAGE_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_IMAGE_ATTACHMENTS = 4
MAX_TOTAL_IMAGE_ATTACHMENT_BYTES = 20 * 1024 * 1024
LOGGER = logging.getLogger(__name__)


def instructions_from_chat_log(chat_log: conversation.ChatLog, fallback_prompt: str) -> str:
    for content in chat_log.content:
        if getattr(content, "role", None) == "system" and isinstance(
            getattr(content, "content", None), str
        ):
            return content.content
    return fallback_prompt


async def codex_input_from_chat_log(
    hass: HomeAssistant, chat_log: conversation.ChatLog
) -> list[dict[str, Any]]:
    """Translate chat history while retaining complete recent user-led turns."""
    input_items: list[dict[str, Any]] = []
    image_history_indexes = recent_user_content_indexes(chat_log.content)
    for index, content in enumerate(chat_log.content):
        role = getattr(content, "role", None)
        text = getattr(content, "content", None)
        if role == "system":
            continue
        if role == "tool_result":
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": content.tool_call_id,
                    "output": dumps_text(content.tool_result),
                }
            )
            continue
        native = getattr(content, "native", None)
        if role == "assistant" and isinstance(native, CodexNativeState):
            input_items.extend(native.items)
            continue
        if role in {"user", "assistant"} and isinstance(text, str) and text.strip():
            item_content: str | list[dict[str, Any]] = text
            if role == "user" and index in image_history_indexes:
                images = await async_image_attachments_for_codex(
                    hass, getattr(content, "attachments", None)
                )
                item_content = codex_user_content_with_images(text, images)
            input_items.append({"role": role, "content": item_content})
        tool_calls = getattr(content, "tool_calls", None)
        if role == "assistant" and tool_calls:
            for tool_call in tool_calls:
                input_items.append(
                    {
                        "type": "function_call",
                        "name": tool_call.tool_name,
                        "arguments": dumps_text(tool_call.tool_args),
                        "call_id": tool_call.id,
                    }
                )
    return retain_complete_turns(input_items)


def retain_complete_turns(
    items: list[dict[str, Any]],
    *,
    max_items: int = MAX_HISTORY_ITEMS,
    max_bytes: int = MAX_HISTORY_BYTES,
) -> list[dict[str, Any]]:
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


def serialized_bytes(items: Sequence[dict[str, Any]]) -> int:
    return serialized_size(items)


def recent_user_content_indexes(contents: Sequence[Any]) -> set[int]:
    user_indexes = [
        index for index, content in enumerate(contents) if getattr(content, "role", None) == "user"
    ]
    return set(user_indexes[-RECENT_IMAGE_USER_TURNS:])


async def async_image_attachments_for_codex(
    hass: HomeAssistant, attachments: Any
) -> list[tuple[str, bytes]]:
    if not attachments:
        return []
    return await hass.async_add_executor_job(image_attachments_for_codex, attachments)


def image_attachments_for_codex(attachments: Any) -> list[tuple[str, bytes]]:
    candidates: list[tuple[str, Any, int]] = []
    for attachment in attachments:
        mime_type = getattr(attachment, "mime_type", "")
        if not isinstance(mime_type, str) or not mime_type.startswith("image/"):
            continue
        path = getattr(attachment, "path", None)
        if path is None:
            continue
        try:
            size = path.stat().st_size
        except OSError as err:
            LOGGER.warning("Skipping unreadable Codex Assist image attachment %s: %s", path, err)
            continue
        if size > MAX_IMAGE_ATTACHMENT_BYTES:
            LOGGER.warning(
                "Skipping Codex Assist image attachment over %s bytes: %s",
                MAX_IMAGE_ATTACHMENT_BYTES,
                path,
            )
            continue
        candidates.append((mime_type, path, size))
    if len(candidates) > MAX_IMAGE_ATTACHMENTS:
        raise ValueError(f"Codex Assist accepts at most {MAX_IMAGE_ATTACHMENTS} image attachments")
    if sum(size for _, _, size in candidates) > MAX_TOTAL_IMAGE_ATTACHMENT_BYTES:
        raise ValueError("Codex Assist image attachments exceed the total attachment size limit")
    images: list[tuple[str, bytes]] = []
    total_bytes = 0
    for mime_type, path, _size in candidates:
        remaining_bytes = MAX_TOTAL_IMAGE_ATTACHMENT_BYTES - total_bytes
        try:
            with path.open("rb") as attachment_file:
                data = attachment_file.read(min(MAX_IMAGE_ATTACHMENT_BYTES, remaining_bytes) + 1)
        except OSError as err:
            LOGGER.warning("Skipping unreadable Codex Assist image attachment %s: %s", path, err)
            continue
        if len(data) > MAX_IMAGE_ATTACHMENT_BYTES:
            raise ValueError("Codex Assist image attachment grew beyond the per-file size limit")
        if len(data) > remaining_bytes:
            raise ValueError(
                "Codex Assist image attachments exceed the total attachment size limit"
            )
        total_bytes += len(data)
        images.append((mime_type, data))
    return images


def codex_tools_from_chat_log(
    chat_log: conversation.ChatLog, *, enable_web_search: bool = False
) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    if chat_log.llm_api:
        tools.extend(
            codex_tool_from_ha_tool(tool, chat_log.llm_api.custom_serializer)
            for tool in chat_log.llm_api.tools
        )
    if enable_web_search:
        tools.append({"type": "web_search"})
    return tools


def codex_tool_from_ha_tool(tool: llm.Tool, custom_serializer: Any) -> dict[str, Any]:
    from .schema_compat import to_openapi

    schema = to_openapi(tool.parameters, custom_serializer=custom_serializer)
    unsupported_keys = {"oneOf", "anyOf", "allOf", "enum", "not"}
    if unsupported_keys.intersection(schema):
        schema = {key: value for key, value in schema.items() if key not in unsupported_keys}
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": schema,
        "strict": False,
    }
