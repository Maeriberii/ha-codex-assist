from __future__ import annotations

import importlib

from tests.ha_fakes import install_homeassistant_fakes


def test_options_schema_keeps_saved_model_only_when_available(monkeypatch):
    install_homeassistant_fakes(monkeypatch)
    module = importlib.reload(
        importlib.import_module("custom_components.codex_assist.config_flow")
    )

    schema = module._settings_schema(
        {
            "model": "retired-model",
            "image_model": "bad-image-model",
            "image_size": "2048x2048",
        },
        model_options=["gpt-5.3-codex"],
    )

    defaults = {key.key: key.default for key in schema.schema}
    assert defaults["model"] == module.DEFAULT_MODEL
    assert defaults["image_model"] == "gpt-image-2-medium"
    assert defaults["image_size"] == "1024x1024"


def test_config_flow_returns_options_flow_instance(monkeypatch):
    install_homeassistant_fakes(monkeypatch)
    module = importlib.reload(
        importlib.import_module("custom_components.codex_assist.config_flow")
    )

    options_flow = module.CodexAssistConfigFlow.async_get_options_flow(object())

    assert isinstance(options_flow, module.CodexAssistOptionsFlow)


def test_options_schema_exposes_curated_controls_without_custom_model_input(monkeypatch):
    install_homeassistant_fakes(monkeypatch)
    module = importlib.reload(
        importlib.import_module("custom_components.codex_assist.config_flow")
    )

    schema = module._settings_schema({}, model_options=["gpt-5.4"])
    fields = {key.key: validator for key, validator in schema.schema.items()}

    assert [option.value for option in fields["model"].config.options] == ["gpt-5.4"]
    assert fields["reasoning_effort"].config.options == ["low", "medium", "high"]
    assert fields["reasoning_summary"].config.options == [
        "auto",
        "concise",
        "detailed",
        "off",
    ]
    assert fields["text_verbosity"].config.options == ["low", "medium", "high"]
    assert [option.value for option in fields["image_model"].config.options] == [
        "gpt-image-2-low",
        "gpt-image-2-medium",
        "gpt-image-2-high",
    ]
    assert [option.value for option in fields["image_size"].config.options] == [
        "1024x1024",
        "1536x1024",
        "1024x1536",
    ]
    assert "safety_mode" not in fields
