"""Shared Responses turn lifecycle for Home Assistant surfaces."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

import httpx
from homeassistant.components import conversation
from homeassistant.components.conversation import AssistantContentDeltaDict
from homeassistant.helpers import llm

from .codex_client import (
    CodexCitation,
    CodexCitationDelta,
    CodexClient,
    CodexResponseItemDelta,
    CodexStreamDelta,
    CodexTextDelta,
    CodexToolCallDelta,
)
from .codex_protocol import native_state_from_response_items
from .telemetry import log_payload_metrics

LOGGER = logging.getLogger(__name__)


async def run_tool_rounds(
    *,
    max_tool_rounds: int,
    run_iteration: Callable[[int, bool], Awaitable[bool]],
) -> None:
    """Run bounded tool rounds, then exactly one tools-disabled final turn."""
    for round_number in range(1, max_tool_rounds + 1):
        if not await run_iteration(round_number, True):
            return
    LOGGER.info(
        "Codex Assist exhausted %d tool-capable rounds; forcing final synthesis",
        max_tool_rounds,
    )
    await run_iteration(max_tool_rounds + 1, False)


async def stream_codex_turn_into_chat_log(
    *,
    chat_log: conversation.ChatLog,
    codex: CodexClient,
    entity_id: str,
    model: str,
    instructions: str,
    input_items: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    reasoning_effort: str,
    reasoning_summary: str,
    text_verbosity: str,
    text_format: dict[str, Any] | None = None,
    allow_tools: bool = True,
    citation_sink: list[CodexCitation] | None = None,
    on_text_delta: Callable[[str], None] | None = None,
    prompt_cache_key: str | None = None,
    round_number: int | None = None,
    is_ai_task: bool = False,
) -> bool:
    """Stream one turn, with the narrow final-synthesis transport retry only."""
    tool_call_requested = False

    def mark_tool_call_requested() -> None:
        nonlocal tool_call_requested
        tool_call_requested = True

    log_payload_metrics(
        instructions=instructions,
        input_items=input_items,
        tools=tools,
        round_number=round_number,
        allow_tools=allow_tools,
        is_ai_task=is_ai_task,
    )
    emitted_text = False

    def mark_text_emitted(text: str) -> None:
        nonlocal emitted_text
        emitted_text = emitted_text or bool(text)
        if text and on_text_delta is not None:
            on_text_delta(text)

    for attempt in range(2):
        try:
            async for _delta in chat_log.async_add_delta_content_stream(
                entity_id,
                codex_stream_to_assistant_deltas(
                    codex.stream_turn(
                        **stream_turn_kwargs(
                            model=model,
                            instructions=instructions,
                            input_items=input_items,
                            tools=tools,
                            reasoning_effort=reasoning_effort,
                            reasoning_summary=reasoning_summary,
                            text_verbosity=text_verbosity,
                            text_format=text_format,
                            prompt_cache_key=prompt_cache_key,
                        )
                    ),
                    on_tool_call=mark_tool_call_requested,
                    on_text_delta=mark_text_emitted,
                    allow_tools=allow_tools,
                    citation_sink=citation_sink,
                ),
            ):
                pass
            break
        except httpx.RemoteProtocolError, httpx.ReadError:
            if allow_tools or emitted_text or attempt:
                raise
            await asyncio.sleep(0.5)
    return tool_call_requested


def stream_turn_kwargs(*, prompt_cache_key: str | None, **kwargs: Any) -> dict[str, Any]:
    """Avoid changing the upstream request shape when no cache scope exists."""
    if prompt_cache_key is not None:
        kwargs["prompt_cache_key"] = prompt_cache_key
    return kwargs


async def codex_stream_to_assistant_deltas(
    stream: AsyncIterator[CodexStreamDelta],
    *,
    on_tool_call: Callable[[], None] | None = None,
    on_text_delta: Callable[[str], None] | None = None,
    allow_tools: bool = True,
    citation_sink: list[CodexCitation] | None = None,
) -> AsyncIterator[AssistantContentDeltaDict]:
    started = False
    seen_urls: set[str] = set()
    response_items: list[dict[str, Any]] = []
    async for delta in stream:
        if isinstance(delta, CodexResponseItemDelta):
            response_items.append(delta.item)
            continue
        if isinstance(delta, CodexCitationDelta):
            citation = safe_citation(delta.citation)
            if citation is not None and citation.url not in seen_urls:
                seen_urls.add(citation.url)
                if citation_sink is not None and all(
                    existing.url != citation.url for existing in citation_sink
                ):
                    citation_sink.append(citation)
            continue
        if not started:
            yield {"role": "assistant"}
            started = True
        if isinstance(delta, CodexTextDelta):
            if on_text_delta is not None:
                on_text_delta(delta.text)
            yield {"content": delta.text}
        elif isinstance(delta, CodexToolCallDelta):
            if not allow_tools:
                raise RuntimeError(
                    "Codex Assist final synthesis returned a tool call while tools are disabled"
                )
            if on_tool_call is not None:
                on_tool_call()
            yield {
                "tool_calls": [
                    llm.ToolInput(
                        id=delta.tool_call.id,
                        tool_name=delta.tool_call.name,
                        tool_args=delta.tool_call.arguments,
                    )
                ]
            }
    if native_state := native_state_from_response_items(response_items):
        if not started:
            yield {"role": "assistant"}
        yield {"native": native_state}


def safe_citation(citation: CodexCitation) -> CodexCitation | None:
    if len(citation.url) > 2048:
        return None
    if any(character.isspace() or ord(character) < 32 for character in citation.url):
        return None
    try:
        parsed = urlsplit(citation.url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if "<" in citation.url or ">" in citation.url:
        return None
    title = " ".join(citation.title.split())[:200]
    if not title:
        return None
    title = (
        title.replace("\\", "\\\\")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return CodexCitation(
        title=title,
        url=citation.url,
        start_index=citation.start_index,
        end_index=citation.end_index,
    )
