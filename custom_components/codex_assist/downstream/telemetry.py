"""Content-free request and provider-usage telemetry."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int
    cached_input_tokens: int
    cache_write_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    rollout_budget_units: float | None = None


def serialized_bytes(value: Any) -> int:
    """Return deterministic JSON bytes without retaining payload content."""
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    )


def payload_metrics(
    *,
    instructions: str,
    input_items: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    round_number: int | None,
    allow_tools: bool,
    is_ai_task: bool,
) -> dict[str, int | bool | float]:
    """Compute numeric sizes/counts only; no payload text is returned or logged."""
    function_tools = [tool for tool in tools if tool.get("type") == "function"]
    tool_results = [item for item in input_items if item.get("type") == "function_call_output"]
    native_items = [
        item
        for item in input_items
        if item.get("type") in {"reasoning", "message", "web_search_call"}
        or (item.get("type") == "function_call" and isinstance(item.get("id"), str))
    ]
    image_parts = [
        part
        for item in input_items
        if isinstance(item.get("content"), list)
        for part in item["content"]
        if isinstance(part, dict) and part.get("type") == "input_image"
    ]
    instructions_bytes = len(instructions.encode())
    tools_bytes = serialized_bytes(tools)
    input_bytes = serialized_bytes(input_items)
    total = instructions_bytes + tools_bytes + input_bytes
    metrics: dict[str, int | bool | float] = {
        "instructions_bytes": instructions_bytes,
        "tools_bytes": tools_bytes,
        "function_tool_bytes": serialized_bytes(function_tools),
        "tool_count": len(function_tools),
        "input_items_bytes": input_bytes,
        "input_items_count": len(input_items),
        "retained_turn_count": sum(item.get("role") == "user" for item in input_items),
        "native_state_bytes": serialized_bytes(native_items),
        "native_state_item_count": len(native_items),
        "tool_result_bytes": sum(serialized_bytes(item) for item in tool_results),
        "tool_result_count": len(tool_results),
        "image_payload_bytes": sum(serialized_bytes(part) for part in image_parts),
        "image_count": len(image_parts),
        "tool_round": round_number or 0,
        "tools_enabled": allow_tools,
        "is_ai_task": is_ai_task,
    }
    if total:
        metrics.update(
            instructions_top_level_share=round(instructions_bytes / total, 6),
            tools_top_level_share=round(tools_bytes / total, 6),
            input_items_top_level_share=round(input_bytes / total, 6),
        )
    if input_bytes:
        metrics.update(
            native_state_input_items_share=round(metrics["native_state_bytes"] / input_bytes, 6),
            tool_result_input_items_share=round(metrics["tool_result_bytes"] / input_bytes, 6),
            image_payload_input_items_share=round(metrics["image_payload_bytes"] / input_bytes, 6),
        )
    return metrics


def log_payload_metrics(**kwargs: Any) -> None:
    """Log only content-free payload measurements."""
    LOGGER.debug("Codex Assist Responses payload metrics: %s", payload_metrics(**kwargs))


def provider_usage_from_event(event: dict[str, Any]) -> ProviderUsage | None:
    """Extract numeric provider counters from a completed Responses event."""
    if event.get("type") != "response.completed":
        return None
    response = event.get("response")
    usage = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        return None
    input_details = usage.get("input_tokens_details")
    output_details = usage.get("output_tokens_details")
    input_details = input_details if isinstance(input_details, dict) else {}
    output_details = output_details if isinstance(output_details, dict) else {}
    rollout = usage.get("codex_rollout_budget_units")
    return ProviderUsage(
        input_tokens=_nonnegative_int(usage.get("input_tokens")),
        cached_input_tokens=_nonnegative_int(input_details.get("cached_tokens")),
        cache_write_input_tokens=_nonnegative_int(input_details.get("cache_write_tokens")),
        output_tokens=_nonnegative_int(usage.get("output_tokens")),
        reasoning_output_tokens=_nonnegative_int(output_details.get("reasoning_tokens")),
        total_tokens=_nonnegative_int(usage.get("total_tokens")),
        rollout_budget_units=float(rollout)
        if not isinstance(rollout, bool) and isinstance(rollout, (int, float))
        else None,
    )


def log_provider_usage(operation: str, usage: ProviderUsage) -> None:
    """Log numeric provider usage without request or response content."""
    ratio = usage.cached_input_tokens / usage.input_tokens if usage.input_tokens else 0.0
    LOGGER.debug(
        "Codex %s usage input=%d cached=%d cache_hit_ratio=%.6f cache_write=%d "
        "output=%d reasoning=%d total=%d rollout_budget=%s",
        operation,
        usage.input_tokens,
        usage.cached_input_tokens,
        ratio,
        usage.cache_write_input_tokens,
        usage.output_tokens,
        usage.reasoning_output_tokens,
        usage.total_tokens,
        usage.rollout_budget_units,
    )


def _nonnegative_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
