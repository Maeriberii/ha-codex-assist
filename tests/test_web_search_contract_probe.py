from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _probe_module():
    path = Path(__file__).parents[1] / "scripts" / "probe_web_search_contract.py"
    spec = importlib.util.spec_from_file_location("probe_web_search_contract", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_payload_is_fixed_and_data_minimized() -> None:
    module = _probe_module()

    payload = module.probe_payload("gpt-test")

    assert payload["model"] == "gpt-test"
    assert payload["tools"] == [
        {
            "type": "web_search",
            "filters": {"allowed_domains": ["iana.org"]},
            "search_context_size": "low",
        }
    ]
    assert payload["store"] is False
    assert all("attachments" not in item for item in payload["input"])
    assert all("entity_id" not in item for item in payload["input"])


def test_event_summary_preserves_shape_without_text_queries_urls_or_ids() -> None:
    module = _probe_module()
    event = {
        "type": "response.output_item.done",
        "item_id": "private-item-id",
        "item": {
            "type": "web_search_call",
            "status": "completed",
            "id": "private-call-id",
            "action": {
                "type": "search",
                "query": "private search query",
                "sources": [{"type": "url", "url": "https://example.invalid/private"}],
            },
        },
        "delta": "private response text",
        "annotation": {
            "type": "url_citation",
            "url": "https://example.invalid/private",
            "title": "Private title",
            "start_index": 0,
            "end_index": 4,
        },
    }

    summary = module.summarize_event(event)
    rendered = json.dumps(summary)

    assert summary["type"] == "response.output_item.done"
    assert summary["item"]["type"] == "web_search_call"
    assert summary["item"]["action"]["type"] == "search"
    assert summary["annotation"]["type"] == "url_citation"
    assert summary["delta_length"] == len("private response text")
    assert "private" not in rendered
    assert "example.invalid" not in rendered
    assert "private-item-id" not in rendered
