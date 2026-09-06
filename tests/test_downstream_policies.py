from __future__ import annotations

from custom_components.codex_assist.downstream.history_policy import retain_complete_turns
from custom_components.codex_assist.downstream.llm_api_policy import (
    default_selection,
    normalize_selection,
    valid_explicit_selection,
)
from custom_components.codex_assist.downstream.prompt_cache import prompt_cache_key
from custom_components.codex_assist.downstream.runtime_policy import (
    normalize_runtime_policy,
)
from custom_components.codex_assist.downstream.telemetry import payload_metrics


def test_prompt_cache_key_is_stable_opaque_and_requires_scope() -> None:
    first = prompt_cache_key("entry-private", "conversation-a")
    assert first == prompt_cache_key("entry-private", "conversation-a")
    assert first != prompt_cache_key("entry-private", "conversation-b")
    assert first is not None and len(first) == 64
    assert "entry-private" not in first and "conversation-a" not in first
    assert prompt_cache_key("entry-private", None) is None


def test_runtime_policy_repairs_invalid_saved_values_and_keeps_open_sse_reads() -> None:
    policy = normalize_runtime_policy({"tool_iterations": 0, "stream_read_timeout": True})
    assert policy.tool_iterations == 8
    assert policy.stream_timeout.read is None


def test_llm_api_policy_is_explicit_and_never_auto_enables_providers() -> None:
    assert normalize_selection(["assist", "mcp-grafana", "assist", 1]) == [
        "assist",
        "mcp-grafana",
    ]
    assert default_selection(None, assist_api_id="assist") == ["assist"]
    assert not valid_explicit_selection([])


def test_history_policy_keeps_complete_newest_turns_under_byte_budget() -> None:
    old = {"role": "user", "content": "old"}
    current = [
        {"role": "user", "content": "current"},
        {"type": "function_call", "call_id": "call-1", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call-1", "output": "{}"},
    ]
    assert retain_complete_turns([old, *current], max_items=24, max_bytes=130) == current


def test_payload_metrics_never_include_content_values() -> None:
    sentinel = "do-not-log-this-prompt-or-tool-body"
    metrics = payload_metrics(
        instructions=sentinel,
        input_items=[{"role": "user", "content": sentinel}],
        tools=[{"type": "function", "name": "example", "description": sentinel}],
        round_number=1,
        allow_tools=True,
        is_ai_task=False,
    )
    assert metrics["instructions_bytes"] == len(sentinel.encode())
    assert sentinel not in repr(metrics)
