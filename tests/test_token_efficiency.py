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
    first = conversation_module._conversation_prompt_cache_key("entry-private", "conversation-a")
    repeated = conversation_module._conversation_prompt_cache_key(
        "entry-private", "conversation-a"
    )
    other = conversation_module._conversation_prompt_cache_key(
        "entry-private", "conversation-b"
    )

    assert first == repeated
    assert first != other
    assert first.startswith("ha-codex-assist:")
    assert "entry-private" not in first
    assert "conversation-a" not in first


@pytest.mark.asyncio
async def test_stream_turn_forwards_prompt_cache_key_when_present(conversation_module):
    codex = FakeCodex()
    chat_log = FakeChatLog()

    await conversation_module._stream_codex_turn_into_chat_log(
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


def test_history_byte_budget_drops_old_complete_turn(conversation_module):
    old_turn = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "x" * 300},
    ]
    current_turn = [{"role": "user", "content": "latest"}]
    items = [*old_turn, *current_turn]

    result = conversation_module._trim_codex_input_items(
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

    result = conversation_module._trim_codex_input_items(
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
    result = await conversation_module._codex_input_from_chat_log(
        hass,
        FakeChatLog(contents),
    )

    user_items = [item for item in result if item.get("role") == "user"]
    assert user_items[0]["content"] == "image turn 0"
    assert isinstance(user_items[1]["content"], list)
    assert isinstance(user_items[2]["content"], list)
    assert len(hass.executor_jobs) == 2
