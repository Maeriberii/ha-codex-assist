"""Runtime settings source of truth, independent of Home Assistant forms."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .runtime_options import RuntimeOptions, normalize_runtime_options

CONF_LLM_HASS_API = "llm_hass_api"
CONF_PROMPT = "prompt"
CONF_MODEL = "model"
CONF_IMAGE_MODEL = "image_model"
CONF_IMAGE_SIZE = "image_size"
CONF_REASONING_EFFORT = "reasoning_effort"
CONF_REASONING_SUMMARY = "reasoning_summary"
CONF_TEXT_VERBOSITY = "text_verbosity"
CONF_WEB_SEARCH = "web_search"
DEFAULT_MODEL = "gpt-5.4"
DEFAULT_PROMPT = "You are a concise Home Assistant Assist conversation agent."
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_REASONING_SUMMARY = "off"
DEFAULT_TEXT_VERBOSITY = "medium"
DEFAULT_WEB_SEARCH = False


@dataclass(frozen=True)
class RuntimeSettings:
    values: Mapping[str, Any]
    runtime_options: RuntimeOptions

    @classmethod
    def from_entry(cls, data: Mapping[str, Any], options: Mapping[str, Any]) -> RuntimeSettings:
        values = {**data, **options}
        return cls(values, normalize_runtime_options(values))

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


def normalize_llm_api_selection(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(item for item in value if isinstance(item, str) and item))


def default_llm_api_selection(value: Any, *, assist_api_id: str) -> list[str]:
    return normalize_llm_api_selection(value) or [assist_api_id]


def prompt_cache_key(entry_id: str, scope: object) -> str | None:
    if not isinstance(scope, str) or not scope:
        return None
    return hashlib.sha256(f"{entry_id}\0{scope}".encode()).hexdigest()
