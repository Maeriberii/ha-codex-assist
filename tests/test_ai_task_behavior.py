from __future__ import annotations

import importlib

import pytest

from custom_components.codex_assist.codex_auth import (
    CodexAuthTemporaryError,
    CodexReauthRequiredError,
    CodexTokenSet,
)
from custom_components.codex_assist.codex_client import CodexAuthenticationError
from tests.ha_fakes import install_homeassistant_fakes


@pytest.fixture
def ai_task_module(monkeypatch):
    install_homeassistant_fakes(monkeypatch)
    importlib.reload(importlib.import_module("custom_components.codex_assist.conversation"))
    module = importlib.import_module("custom_components.codex_assist.ai_task")
    return importlib.reload(module)


def test_ai_task_entity_advertises_data_image_and_attachment_support(ai_task_module):
    entity = ai_task_module.CodexAssistAITaskEntity(type("Entry", (), {"entry_id": "abc"})())

    assert entity._attr_name == "Codex Assist AI Task"
    assert entity._attr_unique_id == "abc_ai_task"
    assert entity._attr_supported_features == 7


def test_structured_data_from_text_returns_plain_text_without_structure(ai_task_module):
    assert ai_task_module._structured_data_from_text("plain response", None) == "plain response"


def test_structured_data_from_text_parses_json_when_structure_requested(ai_task_module):
    assert ai_task_module._structured_data_from_text('{"state":"on"}', {"type": "object"}) == {
        "state": "on"
    }


def test_structured_data_from_text_rejects_invalid_json_when_structure_requested(
    ai_task_module,
    caplog,
):
    with pytest.raises(RuntimeError, match="invalid JSON"):
        ai_task_module._structured_data_from_text("not json", {"type": "object"})
    assert "not json" not in caplog.text
    assert "Failed to parse Codex Assist AI Task JSON response (8 chars)" in caplog.text


@pytest.mark.asyncio
async def test_ai_task_generate_data_reports_temporary_auth_without_reauth(
    ai_task_module,
    monkeypatch,
):
    async def fail_temporarily(*args, **kwargs):
        raise CodexAuthTemporaryError("rate limited")

    class Entry:
        entry_id = "abc"
        data = {}
        options = {}
        reauth_started = False

        def async_start_reauth(self, hass):
            self.reauth_started = True

    entry = Entry()
    entity = ai_task_module.CodexAssistAITaskEntity(entry)
    entity.hass = type(
        "Hass",
        (),
        {"http_client": None, "config_entries": object()},
    )()
    task = type("Task", (), {"structure": None})()
    chat_log = type("ChatLog", (), {})()
    monkeypatch.setattr(ai_task_module, "resolve_runtime_tokens", fail_temporarily)

    with pytest.raises(RuntimeError, match="rate limited"):
        await entity._async_generate_data(task, chat_log)

    assert entry.reauth_started is False


@pytest.mark.asyncio
async def test_ai_task_chat_log_retry_propagates_reauth_required(
    ai_task_module,
    monkeypatch,
):
    async def reject_access_token(**kwargs):
        raise CodexAuthenticationError("invalid token")

    class ReauthAuthClient:
        async def refresh(self, tokens):
            raise CodexReauthRequiredError("invalid refresh")

    chat_log = type(
        "ChatLog",
        (),
        {"unresponded_tool_results": False, "content": [], "llm_api": None},
    )()
    monkeypatch.setattr(
        ai_task_module,
        "_stream_codex_turn_into_chat_log",
        reject_access_token,
    )

    with pytest.raises(CodexReauthRequiredError):
        await ai_task_module._run_codex_ai_task_chat_log(
            hass=type(
                "Hass",
                (),
                {
                    "http_client": None,
                    "config_entries": type(
                        "ConfigEntries",
                        (),
                        {"async_update_entry": lambda self, entry, *, data: None},
                    )(),
                },
            )(),
            entry=type("Entry", (), {"data": {}})(),
            auth_client=ReauthAuthClient(),
            tokens=CodexTokenSet("access-1", "refresh-1"),
            codex=object(),
            chat_log=chat_log,
            entity_id="ai_task.codex_assist",
            model="gpt-5.4",
            prompt="Be concise.",
            reasoning_effort="low",
            reasoning_summary="auto",
            text_verbosity="medium",
        )


@pytest.mark.asyncio
async def test_ai_task_chat_log_retry_reauths_when_refreshed_token_is_rejected(
    ai_task_module,
    monkeypatch,
):
    calls = 0

    async def reject_both_tokens(**kwargs):
        nonlocal calls
        calls += 1
        raise CodexAuthenticationError("invalid token")

    class RefreshAuthClient:
        async def refresh(self, tokens):
            return CodexTokenSet("access-2", "refresh-2")

    chat_log = type(
        "ChatLog",
        (),
        {"unresponded_tool_results": False, "content": [], "llm_api": None},
    )()
    monkeypatch.setattr(
        ai_task_module,
        "_stream_codex_turn_into_chat_log",
        reject_both_tokens,
    )

    with pytest.raises(CodexReauthRequiredError, match="rejected after refresh"):
        await ai_task_module._run_codex_ai_task_chat_log(
            hass=type(
                "Hass",
                (),
                {
                    "http_client": None,
                    "config_entries": type(
                        "ConfigEntries",
                        (),
                        {"async_update_entry": lambda self, entry, *, data: None},
                    )(),
                },
            )(),
            entry=type("Entry", (), {"data": {}})(),
            auth_client=RefreshAuthClient(),
            tokens=CodexTokenSet("access-1", "refresh-1"),
            codex=object(),
            chat_log=chat_log,
            entity_id="ai_task.codex_assist",
            model="gpt-5.4",
            prompt="Be concise.",
            reasoning_effort="low",
            reasoning_summary="auto",
            text_verbosity="medium",
        )

    assert calls == 2


@pytest.mark.asyncio
async def test_ai_task_image_retry_reauths_when_refreshed_token_is_rejected(
    ai_task_module,
    monkeypatch,
):
    class RejectingImageCodex:
        async def generate_image(self, **kwargs):
            raise CodexAuthenticationError("invalid token")

    class RefreshAuthClient:
        async def refresh(self, tokens):
            return CodexTokenSet("access-2", "refresh-2")

    class FakeCodexClient(RejectingImageCodex):
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    chat_log = type("ChatLog", (), {"content": [], "llm_api": None})()
    task = type("Task", (), {"instructions": "draw it"})()
    monkeypatch.setattr(ai_task_module, "CodexClient", FakeCodexClient)

    with pytest.raises(CodexReauthRequiredError, match="rejected after refresh"):
        await ai_task_module._generate_codex_ai_task_image(
            hass=type(
                "Hass",
                (),
                {
                    "http_client": None,
                    "config_entries": type(
                        "ConfigEntries",
                        (),
                        {"async_update_entry": lambda self, entry, *, data: None},
                    )(),
                },
            )(),
            entry=type("Entry", (), {"data": {}})(),
            auth_client=RefreshAuthClient(),
            tokens=CodexTokenSet("access-1", "refresh-1"),
            codex=RejectingImageCodex(),
            chat_log=chat_log,
            task=task,
            chat_model="gpt-5.4",
            image_model="gpt-image-2-medium",
            image_size="1024x1024",
        )
