import httpx

from custom_components.codex_assist.runtime_options import (
    normalize_runtime_options,
)


def test_default_runtime_options_keep_unbounded_sse_read():
    options = normalize_runtime_options({})

    assert options.tool_iterations == 8
    assert options.stream_timeout == httpx.Timeout(
        connect=10, read=None, write=30, pool=10
    )
    assert options.image_generation_timeout == 300


def test_custom_transport_options_are_honored():
    options = normalize_runtime_options(
        {
            "stream_connect_timeout": 12,
            "stream_write_timeout": 45,
            "stream_pool_timeout": 17,
            "stream_read_timeout": 90,
        }
    )

    assert options.stream_timeout == httpx.Timeout(
        connect=12, read=90, write=45, pool=17
    )


def test_custom_tool_iteration_budget_is_honored():
    assert normalize_runtime_options({"tool_iterations": 6}).tool_iterations == 6


def test_invalid_persisted_values_fall_back_to_safe_defaults():
    options = normalize_runtime_options(
        {
            "tool_iterations": 0,
            "stream_connect_timeout": -1,
            "stream_write_timeout": 0,
            "stream_pool_timeout": 121,
            "stream_read_timeout": 3601,
            "image_generation_timeout": 29,
        }
    )

    assert options.tool_iterations == 8
    assert options.stream_timeout == httpx.Timeout(
        connect=10, read=None, write=30, pool=10
    )
    assert options.image_generation_timeout == 300
