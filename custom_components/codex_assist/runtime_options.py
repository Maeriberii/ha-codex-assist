"""Validated, user-configurable Codex Assist runtime options."""

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

DEFAULT_TOOL_ITERATIONS = 8
DEFAULT_STREAM_CONNECT_TIMEOUT = 10
DEFAULT_STREAM_WRITE_TIMEOUT = 30
DEFAULT_STREAM_POOL_TIMEOUT = 10
DEFAULT_STREAM_READ_TIMEOUT = 0
DEFAULT_IMAGE_GENERATION_TIMEOUT = 300


@dataclass(frozen=True)
class RuntimeOptions:
    """Normalized orchestration and transport settings."""

    tool_iterations: int = DEFAULT_TOOL_ITERATIONS
    stream_connect_timeout: int = DEFAULT_STREAM_CONNECT_TIMEOUT
    stream_write_timeout: int = DEFAULT_STREAM_WRITE_TIMEOUT
    stream_pool_timeout: int = DEFAULT_STREAM_POOL_TIMEOUT
    stream_read_timeout: int = DEFAULT_STREAM_READ_TIMEOUT
    image_generation_timeout: int = DEFAULT_IMAGE_GENERATION_TIMEOUT

    @property
    def stream_timeout(self) -> httpx.Timeout:
        """Build a per-client timeout, keeping read=0 explicitly unbounded."""
        return httpx.Timeout(
            connect=self.stream_connect_timeout,
            read=None if self.stream_read_timeout == 0 else self.stream_read_timeout,
            write=self.stream_write_timeout,
            pool=self.stream_pool_timeout,
        )


@dataclass(frozen=True)
class RuntimeOptionSpec:
    """UI and validation contract for one runtime option."""

    key: str
    default: int
    minimum: int
    maximum: int
    unit: str | None = None


RUNTIME_OPTION_SPECS = (
    RuntimeOptionSpec(
        CONF_TOOL_ITERATIONS, DEFAULT_TOOL_ITERATIONS, 1, 20
    ),
    RuntimeOptionSpec(
        CONF_STREAM_CONNECT_TIMEOUT, DEFAULT_STREAM_CONNECT_TIMEOUT, 1, 120, "s"
    ),
    RuntimeOptionSpec(
        CONF_STREAM_WRITE_TIMEOUT, DEFAULT_STREAM_WRITE_TIMEOUT, 1, 300, "s"
    ),
    RuntimeOptionSpec(
        CONF_STREAM_POOL_TIMEOUT, DEFAULT_STREAM_POOL_TIMEOUT, 1, 120, "s"
    ),
    RuntimeOptionSpec(
        CONF_STREAM_READ_TIMEOUT, DEFAULT_STREAM_READ_TIMEOUT, 0, 3600, "s"
    ),
    RuntimeOptionSpec(
        CONF_IMAGE_GENERATION_TIMEOUT,
        DEFAULT_IMAGE_GENERATION_TIMEOUT,
        30,
        1800,
        "s",
    ),
)


def _bounded_int(
    settings: Mapping[str, Any], key: str, default: int, minimum: int, maximum: int
) -> int:
    value = settings.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    value = int(value)
    return value if minimum <= value <= maximum else default


def normalize_runtime_options(settings: Mapping[str, Any]) -> RuntimeOptions:
    """Normalize persisted options defensively to safe, bounded integers."""
    values = [
        _bounded_int(settings, spec.key, spec.default, spec.minimum, spec.maximum)
        for spec in RUNTIME_OPTION_SPECS
    ]
    return RuntimeOptions(*values)


def invalid_runtime_options(settings: Mapping[str, Any]) -> set[str]:
    """Return explicitly persisted/submitted runtime values outside bounds."""
    invalid: set[str] = set()
    for spec in RUNTIME_OPTION_SPECS:
        value = settings.get(spec.key)
        if value is None:
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or int(value) != value
            or not spec.minimum <= int(value) <= spec.maximum
        ):
            invalid.add(spec.key)
    return invalid
