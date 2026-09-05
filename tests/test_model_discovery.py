"""Discovery uses the same rotating credentials as conversation and AI Task."""

import base64
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.codex_assist.codex_auth import CodexReauthRequiredError, CodexTokenSet
from tests.ha_fakes import install_homeassistant_fakes
from tests.test_codex_models import FakeHttpClient, FakeResponse


@pytest.fixture
def discovery(monkeypatch):
    install_homeassistant_fakes(monkeypatch)
    module = importlib.reload(
        importlib.import_module("custom_components.codex_assist.model_discovery")
    )
    return module


def environment(http, access="original-access"):
    entry = SimpleNamespace(data={"access_token": access, "refresh_token": "owned-refresh"})

    def update(target, *, data):
        assert target is entry
        entry.data = data

    hass = SimpleNamespace(
        http_client=http, config_entries=SimpleNamespace(async_update_entry=update)
    )
    return hass, entry


async def test_discovery_refreshes_expired_owned_credentials_before_query(discovery, monkeypatch):
    payload = base64.urlsafe_b64encode(json.dumps({"exp": 0}).encode()).decode().rstrip("=")
    http = FakeHttpClient([FakeResponse(200, {"models": [{"slug": "account-model"}]})])
    hass, entry = environment(http, f"header.{payload}.signature")
    auth = SimpleNamespace(refresh=AsyncMock(return_value=CodexTokenSet("fresh", "rotated")))
    monkeypatch.setattr(discovery, "CodexAuthClient", lambda **kwargs: auth)
    result = await discovery.async_entry_model_catalog(hass, entry, force=True)
    assert result.models == ("account-model",)
    auth.refresh.assert_awaited_once()
    assert http.calls[0][1]["headers"]["Authorization"] == "Bearer fresh"
    assert entry.data == {"access_token": "fresh", "refresh_token": "rotated"}


async def test_discovery_retries_rejected_credentials_once_and_caches_result(
    discovery, monkeypatch
):
    http = FakeHttpClient(
        [
            FakeResponse(401, {}),
            FakeResponse(200, {"models": [{"slug": "account-model"}]}),
        ]
    )
    hass, entry = environment(http)
    auth = SimpleNamespace(refresh=AsyncMock(return_value=CodexTokenSet("fresh", "rotated")))
    monkeypatch.setattr(discovery, "CodexAuthClient", lambda **kwargs: auth)
    assert (await discovery.async_entry_model_catalog(hass, entry)).source == "discovered"
    assert (await discovery.async_entry_model_catalog(hass, entry, force=True)).source == "cached"
    auth.refresh.assert_awaited_once()
    assert len(http.calls) == 2
    assert http.calls[1][1]["headers"]["Authorization"] == "Bearer fresh"


async def test_second_rejection_stops_refresh_loop_and_labels_fallback(discovery, monkeypatch):
    http = FakeHttpClient([FakeResponse(401, {}), FakeResponse(401, {})])
    hass, entry = environment(http)
    auth = SimpleNamespace(refresh=AsyncMock(return_value=CodexTokenSet("fresh", "rotated")))
    monkeypatch.setattr(discovery, "CodexAuthClient", lambda **kwargs: auth)
    result = await discovery.async_entry_model_catalog(hass, entry)
    assert result.source == "fallback"
    assert result.error == "authentication"
    auth.refresh.assert_awaited_once()
    assert len(http.calls) == 2


async def test_invalidated_refresh_token_returns_authentication_status(discovery, monkeypatch):
    http = FakeHttpClient([FakeResponse(401, {})])
    hass, entry = environment(http)
    auth = SimpleNamespace(refresh=AsyncMock(side_effect=CodexReauthRequiredError("invalid")))
    monkeypatch.setattr(discovery, "CodexAuthClient", lambda **kwargs: auth)
    result = await discovery.async_entry_model_catalog(hass, entry)
    assert result.source == "fallback"
    assert result.error == "authentication"
    assert entry.data["access_token"] == "original-access"
