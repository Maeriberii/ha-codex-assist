import httpx

from custom_components.codex_assist.runtime_options import (
    DEFAULT_TOOL_ITERATIONS,
    normalize_runtime_options,
)


def test_runtime_options_keep_quiet_sse_reads_unbounded_by_default():
    options = normalize_runtime_options({})

    assert options.tool_iterations == DEFAULT_TOOL_ITERATIONS
    assert options.stream_timeout == httpx.Timeout(connect=10, read=None, write=30, pool=10)


def test_runtime_options_repair_invalid_persisted_values():
    options = normalize_runtime_options({"tool_iterations": 0, "stream_read_timeout": True})

    assert options.tool_iterations == DEFAULT_TOOL_ITERATIONS
    assert options.stream_timeout.read is None
