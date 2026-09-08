from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path

import pytest

from custom_components.codex_assist.codex_client import CodexTextDelta
from tests.ha_fakes import install_homeassistant_fakes


@dataclass
class FakeContent:
    role: str
    content: str | None = None
    attachments: list | None = None
    native: object | None = None
    tool_calls: list | None = None
    tool_call_id: str | None = None
    tool_result: dict | None = None


class FakeChatLog:
    def __init__(self, content=None):
        self.content = content or []
        self.llm_api = None
        self.streamed_deltas = []

    async def async_add_delta_content_stream(self, entity_id, stream):
        async for delta in stream:
            self.streamed_deltas.append(delta)
            yield delta


class FakeHass:
    def __init__(self):
        self.executor_jobs = []

    async def async_add_executor_job(self, func, *args):
        self.executor_jobs.append((func, args))
        return func(*args)


class FakeCodex:
    def __init__(self):
        self.calls = []

    async def _stream(self):
        yield CodexTextDelta("done")

    def stream_turn(self, **kwargs):
        self.calls.append(kwargs)
        return self._stream()


@pytest.fixture
def conversation_module(monkeypatch):
    install_homeassistant_fakes(monkeypatch)
    module = importlib.import_module("custom_components.codex_assist.conversation")
    return importlib.reload(module)


def test_conversation_prompt_cache_key_is_stable_opaque_and_scoped(conversation_module):
    first = conversation_module.prompt_cache_key("entry-private", "conversation-a")
    repeated = conversation_module.prompt_cache_key("entry-private", "conversation-a")
    other = conversation_module.prompt_cache_key("entry-private", "conversation-b")

    assert first == repeated
    assert first != other
    assert len(first) == 64
    assert "entry-private" not in first
    assert "conversation-a" not in first
    assert conversation_module.prompt_cache_key("entry-private", None) is None


@pytest.mark.asyncio
async def test_stream_turn_forwards_prompt_cache_key_when_present(conversation_module):
    codex = FakeCodex()
    chat_log = FakeChatLog()

    await conversation_module.turn_runtime.stream_codex_turn_into_chat_log(
        chat_log=chat_log,
        codex=codex,
        entity_id="conversation.codex_assist",
        model="gpt-5.4",
        instructions="Be concise.",
        input_items=[{"role": "user", "content": "ping"}],
        tools=[],
        reasoning_effort="low",
        reasoning_summary="off",
        text_verbosity="medium",
        prompt_cache_key="opaque-key",
    )

    assert codex.calls[0]["prompt_cache_key"] == "opaque-key"


def test_payload_component_metrics_are_numeric_and_content_free(conversation_module, caplog):
    user_marker = "PRIVATE_USER_MARKER"
    result_marker = "PRIVATE_RESULT_MARKER"
    metrics = conversation_module.telemetry.payload_metrics(
        instructions="PRIVATE_INSTRUCTIONS_MARKER",
        input_items=[
            {"role": "user", "content": user_marker},
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": result_marker,
            },
        ],
        tools=[
            {
                "type": "function",
                "name": "PRIVATE_TOOL_NAME",
                "description": "PRIVATE_TOOL_DESCRIPTION",
                "parameters": {},
            },
            {"type": "web_search"},
        ],
        round_number=2,
        allow_tools=True,
        is_ai_task=False,
    )

    assert metrics["tool_count"] == 1
    assert metrics["tool_result_count"] == 1
    assert metrics["retained_turn_count"] == 1
    assert metrics["tools_bytes"] > metrics["function_tool_bytes"]
    assert all(not isinstance(value, str) for value in metrics.values())
    conversation_module.LOGGER.debug("Codex Assist Responses payload metrics: %s", metrics)
    assert user_marker not in caplog.text
    assert result_marker not in caplog.text
    assert "PRIVATE_TOOL_DESCRIPTION" not in caplog.text


def test_payload_metrics_count_only_trimmed_input_items(conversation_module):
    old_native = {
        "id": "old-provider-item",
        "type": "reasoning",
        "encrypted_content": "old native state that was trimmed",
    }
    retained_native = {
        "id": "retained-provider-item",
        "type": "reasoning",
        "encrypted_content": "retained native state",
    }
    input_items = [
        {"role": "user", "content": "retained user turn"},
        retained_native,
        {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": '{"ok":true}',
        },
    ]
    chat_log = FakeChatLog(
        [
            FakeContent(role="user", content="old user turn"),
            FakeContent(role="assistant", native=type("Native", (), {"items": (old_native,)})()),
            FakeContent(role="user", content="retained user turn"),
        ]
    )

    metrics = conversation_module.telemetry.payload_metrics(
        instructions="final instructions",
        input_items=input_items,
        tools=[],
        round_number=1,
        allow_tools=True,
        is_ai_task=False,
    )

    assert chat_log.content[0].content == "old user turn"
    assert metrics["retained_turn_count"] == 1
    assert metrics["native_state_item_count"] == 1
    assert metrics["native_state_bytes"] == conversation_module.serialization.serialized_size(
        [retained_native], sort_keys=True
    )
    assert metrics["input_items_bytes"] == conversation_module.serialization.serialized_size(
        input_items, sort_keys=True
    )
    assert metrics["instructions_top_level_share"] + metrics["tools_top_level_share"] + metrics[
        "input_items_top_level_share"
    ] == pytest.approx(1, abs=0.000001)


def test_history_byte_budget_drops_old_complete_turn(conversation_module):
    old_turn = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "x" * 300},
    ]
    current_turn = [{"role": "user", "content": "latest"}]
    items = [*old_turn, *current_turn]

    result = conversation_module.transcript.retain_complete_turns(
        items,
        max_items=24,
        max_bytes=100,
    )

    assert result == current_turn


def test_history_byte_budget_never_splits_or_rejects_current_turn(conversation_module):
    current_turn = [
        {"role": "user", "content": "current"},
        {"role": "assistant", "content": "x" * 500},
    ]

    result = conversation_module.transcript.retain_complete_turns(
        current_turn,
        max_items=24,
        max_bytes=50,
    )

    assert result == current_turn


@pytest.mark.asyncio
async def test_old_image_payloads_are_not_replayed_indefinitely(
    conversation_module,
    tmp_path: Path,
):
    contents = []
    for index in range(3):
        path = tmp_path / f"image-{index}.png"
        path.write_bytes(f"image-{index}".encode())
        attachment = type(
            "Attachment",
            (),
            {"mime_type": "image/png", "path": path},
        )()
        contents.append(
            FakeContent(
                role="user",
                content=f"image turn {index}",
                attachments=[attachment],
            )
        )
        contents.append(FakeContent(role="assistant", content=f"reply {index}"))

    hass = FakeHass()
    result = await conversation_module.transcript.codex_input_from_chat_log(
        hass,
        FakeChatLog(contents),
    )

    user_items = [item for item in result if item.get("role") == "user"]
    assert user_items[0]["content"] == "image turn 0"
    assert isinstance(user_items[1]["content"], list)
    assert isinstance(user_items[2]["content"], list)
    assert len(hass.executor_jobs) == 2
