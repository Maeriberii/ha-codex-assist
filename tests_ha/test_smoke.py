"""Smoke tests against a real Home Assistant instance.

These verify the integration wires into real HA APIs (config entries,
conversation platform, AI Task platform, chat log streaming) instead of the
lightweight fakes used by the main test suite. Only the Codex backend HTTP
calls are stubbed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import voluptuous as vol
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist import DOMAIN
from custom_components.codex_assist.ai_task import _structured_output_format
from custom_components.codex_assist.codex_client import CodexClient, CodexTextDelta
from custom_components.codex_assist.diagnostics import (
    REDACTED,
    async_get_config_entry_diagnostics,
)

ENTRY_DATA = {
    # Not a JWT, so the runtime treats it as non-expiring and skips refresh.
    "access_token": "test-access-token",
    "refresh_token": "test-refresh-token",
    "model": "gpt-5.4",
    "prompt": "You are a concise Home Assistant Assist conversation agent.",
}


def _make_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Codex Assist",
        unique_id=DOMAIN,
        data=dict(ENTRY_DATA),
    )


async def _setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    # The conversation component requires the core homeassistant component
    # (exposed-entities registry) to be set up first.
    assert await async_setup_component(hass, "homeassistant", {})
    entry = _make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_creates_conversation_and_ai_task_entities(
    hass: HomeAssistant,
) -> None:
    entry = await _setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("conversation.codex_assist") is not None
    assert hass.states.get("ai_task.codex_assist_ai_task") is not None


async def test_unload_entry_cleans_up(hass: HomeAssistant) -> None:
    entry = await _setup_entry(hass)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_conversation_turn_streams_codex_reply(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup_entry(hass)

    async def fake_stream_turn(self: CodexClient, **kwargs: object):
        yield CodexTextDelta("The porch light is on.")

    monkeypatch.setattr(CodexClient, "stream_turn", fake_stream_turn)

    result = await conversation.async_converse(
        hass,
        "Is the porch light on?",
        None,
        Context(),
        agent_id="conversation.codex_assist",
    )

    speech = result.response.speech["plain"]["speech"]
    assert speech == "The porch light is on."


async def test_diagnostics_redact_tokens_on_real_entry(hass: HomeAssistant) -> None:
    entry = await _setup_entry(hass)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    entry_data = diagnostics["entry"]["data"]
    assert entry_data["access_token"] == REDACTED
    assert entry_data["refresh_token"] == REDACTED
    assert entry_data["model"] == "gpt-5.4"
    assert "test-access-token" not in str(diagnostics)


async def test_options_flow_uses_real_home_assistant_contract(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = await _setup_entry(hass)

    async def fake_model_ids(**kwargs: object) -> list[str]:
        return ["gpt-5.4"]

    monkeypatch.setattr(
        "custom_components.codex_assist.config_flow.fetch_codex_model_ids",
        fake_model_ids,
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "model": "gpt-5.4",
            "prompt": "Keep it short.",
            "reasoning_effort": "low",
            "reasoning_summary": "auto",
            "text_verbosity": "low",
            "image_model": "gpt-image-2-medium",
            "image_size": "1024x1024",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["text_verbosity"] == "low"
    assert entry.options["prompt"] == "Keep it short."


def test_structured_output_uses_real_home_assistant_schema_converter() -> None:
    task = SimpleNamespace(
        name="Porch state",
        structure=vol.Schema({vol.Required("state"): vol.In(["on", "off"])}),
    )
    chat_log = SimpleNamespace(llm_api=None)

    text_format = _structured_output_format(task, chat_log)

    assert text_format is not None
    assert text_format["type"] == "json_schema"
    assert text_format["name"] == "porch_state"
    assert text_format["schema"]["required"] == ["state"]
    assert text_format["schema"]["properties"]["state"]["enum"] == ["on", "off"]
