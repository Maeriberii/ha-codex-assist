"""Downstream-owned additions to the otherwise upstream options flow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.data_entry_flow import section
from homeassistant.helpers import llm, selector

from .llm_api_policy import default_selection, normalize_selection, valid_explicit_selection
from .runtime_policy import RUNTIME_OPTION_SPECS, RuntimeOptionSpec, invalid_runtime_option_keys

try:
    from homeassistant.const import CONF_LLM_HASS_API
except ImportError:
    CONF_LLM_HASS_API = "llm_hass_api"

SECTION_RUNTIME_ORCHESTRATION = "runtime_orchestration"


def async_get_llm_apis(hass: Any) -> list[llm.API]:
    """Use the public API when present; retain contract-test compatibility."""
    getter = getattr(llm, "async_get_apis", None)
    return getter(hass) if getter is not None else []


def llm_api_selector(defaults: Mapping[str, Any], llm_apis: list[llm.API]) -> dict[Any, Any]:
    """Build the explicit, conservative HA LLM API allowlist field."""
    return {
        vol.Optional(
            CONF_LLM_HASS_API,
            default=default_selection(
                defaults.get(CONF_LLM_HASS_API), assist_api_id=llm.LLM_API_ASSIST
            ),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(value=api.id, label=api.name) for api in llm_apis
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
                multiple=True,
            )
        )
    }


def runtime_options_section(defaults: Mapping[str, Any]) -> tuple[Any, Any]:
    """Build the downstream runtime section used by the options form."""
    return (
        vol.Optional(SECTION_RUNTIME_ORCHESTRATION),
        section(
            vol.Schema(
                {
                    vol.Optional(spec.key, default=defaults.get(spec.key, spec.default)):
                    _number_selector(spec)
                    for spec in RUNTIME_OPTION_SPECS
                }
            ),
            {"collapsed": True},
        ),
    )


def validate_and_normalize_options(data: dict[str, Any]) -> dict[str, str]:
    """Validate submitted downstream options in place and return form errors."""
    errors = {key: "value_out_of_range" for key in invalid_runtime_option_keys(data)}
    if CONF_LLM_HASS_API not in data:
        return errors
    if not valid_explicit_selection(data[CONF_LLM_HASS_API]):
        errors[CONF_LLM_HASS_API] = "select_at_least_one_llm_api"
    else:
        data[CONF_LLM_HASS_API] = normalize_selection(data[CONF_LLM_HASS_API])
    return errors


def _number_selector(spec: RuntimeOptionSpec) -> selector.NumberSelector:
    config: dict[str, Any] = {
        "min": spec.minimum,
        "max": spec.maximum,
        "step": 1,
        "mode": "box",
    }
    if spec.unit is not None:
        config["unit_of_measurement"] = spec.unit
    return selector.NumberSelector(selector.NumberSelectorConfig(**config))
