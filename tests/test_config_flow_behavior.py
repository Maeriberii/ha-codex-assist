from __future__ import annotations

import importlib

import pytest

from custom_components.codex_assist.codex_auth import (
    CodexAuthorizationCode,
    CodexDeviceCode,
    CodexTokenSet,
)
from tests.ha_fakes import install_homeassistant_fakes


class FakeAuthClient:
    def __init__(self):
        self.device_code = CodexDeviceCode(
            user_code="ABCD-EFGH",
            device_auth_id="device-1",
            verification_uri="https://auth.openai.com/codex/device",
            interval=7,
        )
        self.poll_result = CodexAuthorizationCode("auth-code-1", "verifier-1")
        self.tokens = CodexTokenSet("access-1", "refresh-1")
        self.requested = 0
        self.polls = []
        self.exchanges = []

    async def request_device_code(self):
        self.requested += 1
        return self.device_code

    async def poll_device_code(self, *, device_auth_id, user_code):
        self.polls.append((device_auth_id, user_code))
        return self.poll_result

    async def exchange_authorization_code(self, authorization):
        self.exchanges.append(authorization)
        return self.tokens


@pytest.fixture
def config_flow_module(monkeypatch):
    install_homeassistant_fakes(monkeypatch)
    module = importlib.import_module("custom_components.codex_assist.config_flow")
    return importlib.reload(module)


@pytest.mark.asyncio
async def test_config_flow_requests_device_code_before_showing_pairing_form(
    config_flow_module,
):
    flow = config_flow_module.CodexAssistConfigFlow()
    auth = FakeAuthClient()
    flow._auth_client = lambda: auth

    result = await flow.async_step_user({"model": "gpt-5.4", "prompt": "Be concise."})

    assert auth.requested == 1
    assert result["type"] == "form"
    assert result["step_id"] == "device"
    assert result["description_placeholders"] == {
        "verification_uri": "https://auth.openai.com/codex/device",
        "user_code": "ABCD-EFGH",
        "interval": "7",
    }
    assert not hasattr(flow, "unique_id")
    assert not hasattr(flow, "duplicate_checked")


@pytest.mark.asyncio
async def test_config_flow_creates_entry_only_after_device_token_exchange(
    config_flow_module,
):
    flow = config_flow_module.CodexAssistConfigFlow()
    auth = FakeAuthClient()
    flow._auth_client = lambda: auth
    flow._setup_input = {"model": "gpt-5.4", "prompt": "Be concise."}
    flow._device_code = auth.device_code
    flow.source = "user"

    result = await flow.async_step_device_wait()

    assert auth.polls == [("device-1", "ABCD-EFGH")]
    assert auth.exchanges == [CodexAuthorizationCode("auth-code-1", "verifier-1")]
    assert flow.unique_id == "codex_assist"
    assert flow.duplicate_checked is True
    assert result == {
        "type": "create_entry",
        "title": "Codex Assist",
        "data": {
            "model": "gpt-5.4",
            "prompt": "Be concise.",
            "access_token": "access-1",
            "refresh_token": "refresh-1",
        },
    }


@pytest.mark.asyncio
async def test_config_flow_pending_authorization_keeps_same_device_code(
    config_flow_module,
):
    flow = config_flow_module.CodexAssistConfigFlow()
    auth = FakeAuthClient()
    auth.poll_result = None
    flow._auth_client = lambda: auth
    flow._device_code = auth.device_code

    result = await flow.async_step_device_wait()

    assert result["type"] == "form"
    assert result["step_id"] == "device"
    assert result["errors"] == {"base": "authorization_pending"}
    assert result["description_placeholders"]["user_code"] == "ABCD-EFGH"


@pytest.mark.asyncio
async def test_reauth_updates_existing_entry_after_device_token_exchange(
    config_flow_module,
):
    flow = config_flow_module.CodexAssistConfigFlow()
    auth = FakeAuthClient()
    flow._auth_client = lambda: auth
    flow._setup_input = {"model": "gpt-5.4"}
    flow._device_code = auth.device_code
    flow.source = "reauth"
    flow.reauth_entry = object()

    result = await flow.async_step_device_wait()

    assert result["type"] == "abort"
    assert result["data_updates"] == {
        "model": "gpt-5.4",
        "access_token": "access-1",
        "refresh_token": "refresh-1",
    }
