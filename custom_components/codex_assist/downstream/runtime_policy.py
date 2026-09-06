"""Validated runtime limits owned by the downstream integration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

CONF_TOOL_ITERATIONS = "tool_iterations"
CONF_STREAM_CONNECT_TIMEOUT = "stream_connect_timeout"
CONF_STREAM_WRITE_TIMEOUT = "stream_write_timeout"
CONF_STREAM_POOL_TIMEOUT = "stream_pool_timeout"
CONF_STREAM_READ_TIMEOUT = "stream_read_timeout"
CONF_IMAGE_GENERATION_TIMEOUT = "image_generation_timeout"


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
        """Build the transport timeout without leaking option semantics to the client."""
        return httpx.Timeout(
            connect=self.stream_connect_timeout,
            read=None if self.stream_read_timeout == 0 else self.stream_read_timeout,
            write=self.stream_write_timeout,
            pool=self.stream_pool_timeout,
        )


def normalize_runtime_policy(settings: Mapping[str, Any]) -> RuntimePolicy:
    """Return safe runtime limits, repairing malformed persisted values."""
    values = [_value_or_default(settings, spec) for spec in RUNTIME_OPTION_SPECS]
    return RuntimePolicy(*values)


def invalid_runtime_option_keys(settings: Mapping[str, Any]) -> set[str]:
    """Return explicit submitted values that fail the options boundary."""
    return {
        spec.key
        for spec in RUNTIME_OPTION_SPECS
        if spec.key in settings and not _is_valid_value(settings[spec.key], spec)
    }


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
