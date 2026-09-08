"""Content-free request and provider-usage telemetry."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .serialization import serialized_size

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


def payload_metrics(**kwargs: Any) -> dict[str, int | bool | float]:
    instructions = kwargs["instructions"]
    input_items = kwargs["input_items"]
    tools = kwargs["tools"]
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
    instructions_bytes, tools_bytes, input_bytes = (
        len(instructions.encode()),
        serialized_size(tools, sort_keys=True),
        serialized_size(input_items, sort_keys=True),
    )
    metrics: dict[str, int | bool | float] = {
        "instructions_bytes": instructions_bytes,
        "tools_bytes": tools_bytes,
        "function_tool_bytes": serialized_size(function_tools, sort_keys=True),
        "tool_count": len(function_tools),
        "input_items_bytes": input_bytes,
        "input_items_count": len(input_items),
        "retained_turn_count": sum(item.get("role") == "user" for item in input_items),
        "native_state_bytes": serialized_size(native_items, sort_keys=True),
        "native_state_item_count": len(native_items),
        "tool_result_bytes": sum(serialized_size(item, sort_keys=True) for item in tool_results),
        "tool_result_count": len(tool_results),
        "image_payload_bytes": sum(serialized_size(part, sort_keys=True) for part in image_parts),
        "image_count": len(image_parts),
        "tool_round": kwargs["round_number"] or 0,
        "tools_enabled": kwargs["allow_tools"],
        "is_ai_task": kwargs["is_ai_task"],
    }
    total = instructions_bytes + tools_bytes + input_bytes
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
    LOGGER.debug("Codex Assist Responses payload metrics: %s", payload_metrics(**kwargs))


def provider_usage_from_event(event: dict[str, Any]) -> ProviderUsage | None:
    if event.get("type") != "response.completed" or not isinstance(event.get("response"), dict):
        return None
    usage = event["response"].get("usage")
    if not isinstance(usage, dict):
        return None
    inputs, outputs = usage.get("input_tokens_details"), usage.get("output_tokens_details")
    inputs, outputs = (
        inputs if isinstance(inputs, dict) else {},
        outputs if isinstance(outputs, dict) else {},
    )
    rollout = usage.get("codex_rollout_budget_units")
    return ProviderUsage(
        _counter(usage.get("input_tokens")),
        _counter(inputs.get("cached_tokens")),
        _counter(inputs.get("cache_write_tokens")),
        _counter(usage.get("output_tokens")),
        _counter(outputs.get("reasoning_tokens")),
        _counter(usage.get("total_tokens")),
        float(rollout)
        if not isinstance(rollout, bool) and isinstance(rollout, (int, float))
        else None,
    )


def log_provider_usage(operation: str, usage: ProviderUsage) -> None:
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


def _counter(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
