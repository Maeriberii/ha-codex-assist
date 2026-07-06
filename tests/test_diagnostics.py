from __future__ import annotations

import importlib
import types

from tests.ha_fakes import install_homeassistant_fakes


def _load_diagnostics(monkeypatch):
    install_homeassistant_fakes(monkeypatch)
    return importlib.reload(
        importlib.import_module("custom_components.codex_assist.diagnostics")
    )


async def test_diagnostics_redacts_tokens_but_keeps_settings(monkeypatch):
    module = _load_diagnostics(monkeypatch)
    entry = types.SimpleNamespace(
        data={
            "access_token": "secret-access",
            "refresh_token": "secret-refresh",
            "model": "gpt-5.4",
            "prompt": "You are helpful.",
        },
        options={"reasoning_effort": "low"},
    )

    diagnostics = await module.async_get_config_entry_diagnostics(object(), entry)

    entry_data = diagnostics["entry"]["data"]
    assert entry_data["access_token"] == module.REDACTED
    assert entry_data["refresh_token"] == module.REDACTED
    assert entry_data["model"] == "gpt-5.4"
    assert entry_data["prompt"] == "You are helpful."
    assert diagnostics["entry"]["options"] == {"reasoning_effort": "low"}


async def test_diagnostics_never_contains_raw_token_values(monkeypatch):
    module = _load_diagnostics(monkeypatch)
    entry = types.SimpleNamespace(
        data={"access_token": "raw-token-value", "refresh_token": "raw-refresh-value"},
        options={},
    )

    diagnostics = await module.async_get_config_entry_diagnostics(object(), entry)

    assert "raw-token-value" not in str(diagnostics)
    assert "raw-refresh-value" not in str(diagnostics)
