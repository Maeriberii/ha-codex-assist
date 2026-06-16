from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from custom_components.codex_assist.codex_client import (
    CodexTextDelta,
    CodexToolCall,
    CodexToolCallDelta,
)
from tests.ha_fakes import install_homeassistant_fakes


@dataclass
class FakeContent:
    role: str
    content: str | None = None
    tool_call_id: str | None = None
    tool_result: dict | None = None
    tool_calls: list | None = None
    attachments: list | None = None


@dataclass
class FakeToolCall:
    id: str
    tool_name: str
    tool_args: dict


class FakeChatLog:
    def __init__(self, content=None, llm_api=None):
        self.content = content or []
        self.llm_api = llm_api
        self.streamed_entity_id = None
        self.streamed_deltas = []

    async def async_add_delta_content_stream(self, entity_id, stream):
        self.streamed_entity_id = entity_id
        async for delta in stream:
            self.streamed_deltas.append(delta)
            yield delta


class FakeCodex:
    def __init__(self, deltas):
        self.deltas = deltas
        self.calls = []

    async def _stream(self):
        for delta in self.deltas:
            yield delta

    def stream_turn(self, **kwargs):
        self.calls.append(kwargs)
        return self._stream()


class FakeHass:
    def __init__(self):
        self.executor_jobs = []

    async def async_add_executor_job(self, func, *args):
        self.executor_jobs.append((func, args))
        return func(*args)


@pytest.fixture
def conversation_module(monkeypatch):
    install_homeassistant_fakes(monkeypatch)
    module = importlib.import_module("custom_components.codex_assist.conversation")
    return importlib.reload(module)


@pytest.mark.asyncio
async def test_codex_input_from_chat_log_preserves_history_tools_and_results(
    conversation_module,
):
    chat_log = FakeChatLog(
        [
            FakeContent(role="system", content="system prompt"),
            FakeContent(role="user", content="turn on kitchen"),
            FakeContent(
                role="assistant",
                content="",
                tool_calls=[
                    FakeToolCall(
                        id="call-1",
                        tool_name="HassTurnOn",
                        tool_args={"name": "Kitchen", "domain": "light"},
                    )
                ],
            ),
            FakeContent(
                role="tool_result",
                tool_call_id="call-1",
                tool_result={"success": True},
            ),
            FakeContent(role="assistant", content="Done."),
        ]
    )

    result = await conversation_module._codex_input_from_chat_log(object(), chat_log)

    assert result == [
        {"role": "user", "content": "turn on kitchen"},
        {
            "type": "function_call",
            "name": "HassTurnOn",
            "arguments": json.dumps({"name": "Kitchen", "domain": "light"}),
            "call_id": "call-1",
        },
        {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": json.dumps({"success": True}),
        },
        {"role": "assistant", "content": "Done."},
    ]


@pytest.mark.asyncio
async def test_codex_stream_to_assistant_deltas_yields_text_and_tool_inputs(
    conversation_module,
):
    called = False

    def mark_called():
        nonlocal called
        called = True

    async def stream():
        yield CodexTextDelta("Working")
        yield CodexToolCallDelta(
            CodexToolCall(
                id="call-1",
                name="HassTurnOn",
                arguments={"name": "Kitchen"},
            )
        )

    deltas = [
        delta
        async for delta in conversation_module._codex_stream_to_assistant_deltas(
            stream(),
            on_tool_call=mark_called,
        )
    ]

    assert deltas[0] == {"role": "assistant"}
    assert deltas[1] == {"content": "Working"}
    assert deltas[2]["tool_calls"][0].id == "call-1"
    assert deltas[2]["tool_calls"][0].tool_name == "HassTurnOn"
    assert called is True


def test_codex_tools_from_chat_log_converts_ha_llm_api_tools(conversation_module):
    tool = type(
        "Tool",
        (),
        {
            "name": "HassTurnOn",
            "description": "Turn on a device",
            "parameters": {"type": "object", "properties": {"name": {"type": "string"}}},
        },
    )()
    llm_api = type("LLMApi", (), {"tools": [tool], "custom_serializer": None})()

    result = conversation_module._codex_tools_from_chat_log(FakeChatLog(llm_api=llm_api))

    assert result == [
        {
            "type": "function",
            "name": "HassTurnOn",
            "description": "Turn on a device",
            "parameters": {"type": "object", "properties": {"name": {"type": "string"}}},
            "strict": False,
        }
    ]


@pytest.mark.asyncio
async def test_stream_codex_turn_into_chat_log_calls_chat_log_stream_api(
    conversation_module,
):
    chat_log = FakeChatLog()
    codex = FakeCodex([CodexTextDelta("Done")])

    tool_requested = await conversation_module._stream_codex_turn_into_chat_log(
        chat_log=chat_log,
        codex=codex,
        entity_id="conversation.codex_assist",
        model="gpt-5.4",
        instructions="Be concise.",
        input_items=[{"role": "user", "content": "ping"}],
        tools=[],
        reasoning_effort="low",
        reasoning_summary="auto",
        text_verbosity="medium",
    )

    assert tool_requested is False
    assert chat_log.streamed_entity_id == "conversation.codex_assist"
    assert chat_log.streamed_deltas == [{"role": "assistant"}, {"content": "Done"}]
    assert codex.calls == [
        {
            "model": "gpt-5.4",
            "instructions": "Be concise.",
            "input_items": [{"role": "user", "content": "ping"}],
            "tools": [],
            "reasoning_effort": "low",
            "reasoning_summary": "auto",
            "text_verbosity": "medium",
        }
    ]


@pytest.mark.asyncio
async def test_codex_input_from_chat_log_translates_image_attachments(
    conversation_module,
    tmp_path: Path,
):
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"fake-image")
    attachment = type(
        "Attachment",
        (),
        {"mime_type": "image/png", "path": image_path},
    )()
    chat_log = FakeChatLog(
        [FakeContent(role="user", content="describe this", attachments=[attachment])]
    )

    hass = FakeHass()

    result = await conversation_module._codex_input_from_chat_log(hass, chat_log)

    content = result[0]["content"]
    assert content[0] == {"type": "input_text", "text": "describe this"}
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    assert hass.executor_jobs[0][0] is conversation_module._image_attachments_for_codex


def test_trim_codex_input_items_drops_orphaned_tool_outputs(conversation_module):
    input_items = [
        {
            "type": "function_call",
            "name": "OldTool",
            "arguments": "{}",
            "call_id": "old-call",
        },
        {
            "type": "function_call_output",
            "call_id": "old-call",
            "output": "{}",
        },
        {"role": "user", "content": "latest"},
        {
            "type": "function_call",
            "name": "NewTool",
            "arguments": "{}",
            "call_id": "new-call",
        },
        {
            "type": "function_call_output",
            "call_id": "new-call",
            "output": "{}",
        },
    ]

    result = conversation_module._trim_codex_input_items(input_items, max_items=4)

    assert result == [
        {"role": "user", "content": "latest"},
        {
            "type": "function_call",
            "name": "NewTool",
            "arguments": "{}",
            "call_id": "new-call",
        },
        {
            "type": "function_call_output",
            "call_id": "new-call",
            "output": "{}",
        },
    ]


def test_trim_codex_input_items_leaves_short_history_unchanged(conversation_module):
    input_items = [{"role": "user", "content": "hello"}]

    assert conversation_module._trim_codex_input_items(input_items, max_items=24) is input_items


def test_trim_codex_input_items_keeps_pair_at_retained_boundary(conversation_module):
    input_items = [
        {"role": "user", "content": "old"},
        {
            "type": "function_call",
            "name": "BoundaryTool",
            "arguments": "{}",
            "call_id": "boundary-call",
        },
        {
            "type": "function_call_output",
            "call_id": "boundary-call",
            "output": "{}",
        },
        {"role": "assistant", "content": "Done."},
    ]

    assert conversation_module._trim_codex_input_items(input_items, max_items=3) == [
        {
            "type": "function_call",
            "name": "BoundaryTool",
            "arguments": "{}",
            "call_id": "boundary-call",
        },
        {
            "type": "function_call_output",
            "call_id": "boundary-call",
            "output": "{}",
        },
        {"role": "assistant", "content": "Done."},
    ]
