from custom_components.codex_assist.codex_protocol import (
    CodexNativeState,
    responses_items_from_content,
    stable_prompt_cache_key,
)


class Assistant:
    role = "assistant"
    content = ""
    tool_calls = None

    def __init__(self, *, native=None, thinking_content=None):
        self.native = native
        self.thinking_content = thinking_content


def test_reasoning_native_item_round_trips_without_visible_text():
    encrypted = "encrypted-reasoning-state"
    content = Assistant(
        thinking_content="I need a tool.",
        native=CodexNativeState(
            ({"type": "reasoning", "id": "rs_1", "encrypted_content": encrypted},)
        ),
    )

    items = responses_items_from_content([content])

    assert items == [
        {
            "type": "reasoning",
            "id": "rs_1",
            "encrypted_content": encrypted,
            "summary": [{"type": "summary_text", "text": "I need a tool."}],
        }
    ]
    assert all(
        encrypted not in str(getattr(content, field, ""))
        for field in ("content", "thinking_content")
    )


def test_native_web_search_and_reasoning_items_round_trip_in_provider_order():
    reasoning = {"type": "reasoning", "id": "rs_1", "encrypted_content": "state"}
    item = {"type": "web_search_call", "id": "ws_1", "status": "completed"}

    assert responses_items_from_content(
        [Assistant(native=CodexNativeState((reasoning, item)))]
    ) == [reasoning, item]


def test_prompt_cache_key_is_stable_and_opaque():
    first = stable_prompt_cache_key("entry-a", "conversation-a")

    assert first == stable_prompt_cache_key("entry-a", "conversation-a")
    assert first != stable_prompt_cache_key("entry-a", "conversation-b")
    assert "conversation-a" not in first
    assert "entry-a" not in first
