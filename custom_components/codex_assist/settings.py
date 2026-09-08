"""Runtime settings and normalization for Codex Assist.

This module owns persisted runtime values.  Home Assistant form construction
belongs in ``config_flow``; provider transport receives only normalized values.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

CONF_LLM_HASS_API = "llm_hass_api"
CONF_PROMPT = "prompt"
CONF_MODEL = "model"
CONF_IMAGE_MODEL = "image_model"
CONF_IMAGE_SIZE = "image_size"
CONF_REASONING_EFFORT = "reasoning_effort"
CONF_REASONING_SUMMARY = "reasoning_summary"
CONF_TEXT_VERBOSITY = "text_verbosity"
CONF_WEB_SEARCH = "web_search"
CONF_TOOL_ITERATIONS = "tool_iterations"
CONF_STREAM_CONNECT_TIMEOUT = "stream_connect_timeout"
CONF_STREAM_WRITE_TIMEOUT = "stream_write_timeout"
CONF_STREAM_POOL_TIMEOUT = "stream_pool_timeout"
CONF_STREAM_READ_TIMEOUT = "stream_read_timeout"
CONF_IMAGE_GENERATION_TIMEOUT = "image_generation_timeout"

DEFAULT_MODEL = "gpt-5.4"
DEFAULT_PROMPT = "You are a concise Home Assistant Assist conversation agent."
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_REASONING_SUMMARY = "off"
DEFAULT_TEXT_VERBOSITY = "medium"
DEFAULT_WEB_SEARCH = False


@dataclass(frozen=True)
class RuntimeOptionSpec:
    key: str
    default: int
    minimum: int
    maximum: int
    unit: str | None = None


RUNTIME_OPTION_SPECS = (
    RuntimeOptionSpec(CONF_TOOL_ITERATIONS, 8, 1, 20),
    RuntimeOptionSpec(CONF_STREAM_CONNECT_TIMEOUT, 10, 1, 120, "s"),
    RuntimeOptionSpec(CONF_STREAM_WRITE_TIMEOUT, 30, 1, 300, "s"),
    RuntimeOptionSpec(CONF_STREAM_POOL_TIMEOUT, 10, 1, 120, "s"),
    RuntimeOptionSpec(CONF_STREAM_READ_TIMEOUT, 0, 0, 3600, "s"),
    RuntimeOptionSpec(CONF_IMAGE_GENERATION_TIMEOUT, 300, 30, 1800, "s"),
)


@dataclass(frozen=True)
class RuntimePolicy:
    tool_iterations: int
    stream_connect_timeout: int
    stream_write_timeout: int
    stream_pool_timeout: int
    stream_read_timeout: int
    image_generation_timeout: int

    @property
    def stream_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self.stream_connect_timeout,
            read=None if self.stream_read_timeout == 0 else self.stream_read_timeout,
            write=self.stream_write_timeout,
            pool=self.stream_pool_timeout,
        )


@dataclass(frozen=True)
class RuntimeSettings:
    """Normalized settings consumed by Conversation and AI Task runtime paths."""

    values: Mapping[str, Any]
    policy: RuntimePolicy

    @classmethod
    def from_entry(cls, data: Mapping[str, Any], options: Mapping[str, Any]) -> RuntimeSettings:
        values = {**data, **options}
        return cls(values, normalize_runtime_policy(values))

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


def normalize_runtime_policy(settings: Mapping[str, Any]) -> RuntimePolicy:
    return RuntimePolicy(*(_value_or_default(settings, spec) for spec in RUNTIME_OPTION_SPECS))


def invalid_runtime_option_keys(settings: Mapping[str, Any]) -> set[str]:
    return {
        spec.key
        for spec in RUNTIME_OPTION_SPECS
        if spec.key in settings and not _is_valid_value(settings[spec.key], spec)
    }


def normalize_llm_api_selection(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(item for item in value if isinstance(item, str) and item))


def selected_llm_apis(value: Any, *, assist_api_id: str) -> list[str]:
    return normalize_llm_api_selection(value) or [assist_api_id]


def has_explicit_llm_api_selection(value: Any) -> bool:
    return bool(normalize_llm_api_selection(value))


def prompt_cache_key(entry_id: str, stable_scope: object) -> str | None:
    if not isinstance(stable_scope, str) or not stable_scope:
        return None
    return hashlib.sha256(f"{entry_id}\0{stable_scope}".encode()).hexdigest()


def _value_or_default(settings: Mapping[str, Any], spec: RuntimeOptionSpec) -> int:
    value = settings.get(spec.key, spec.default)
    return int(value) if _is_valid_value(value, spec) else spec.default


def _is_valid_value(value: Any, spec: RuntimeOptionSpec) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and int(value) == value
        and spec.minimum <= int(value) <= spec.maximum
    )
