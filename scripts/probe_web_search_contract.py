"""Privacy-safe throwaway probe for the Codex hosted web-search contract.

This script records event structure, not response text, search queries, URLs, or
credentials. Use only a token issued to Codex Assist itself; never borrow Codex
CLI/editor credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.codex_assist.codex_client import (  # noqa: E402
    CODEX_BACKEND_BASE_URL,
    codex_headers,
)

DEFAULT_MODEL = "gpt-5.4"
FIXED_PROMPT = (
    "Use web search to identify the organization that maintains the IANA "
    "Reserved Domains page. Cite the source in the response."
)


def probe_payload(model: str) -> dict[str, Any]:
    """Return the fixed, data-minimized probe payload."""
    return {
        "model": model,
        "instructions": (
            "Answer only from the hosted web-search tool. Do not use or request "
            "Home Assistant state, user data, attachments, or prior conversation context."
        ),
        "input": [{"role": "user", "content": FIXED_PROMPT}],
        "tools": [
            {
                "type": "web_search",
                "filters": {"allowed_domains": ["iana.org"]},
                "search_context_size": "low",
            }
        ],
        "stream": True,
        "store": False,
    }


def summarize_event(event: dict[str, Any]) -> dict[str, Any]:
    """Keep contract shape while dropping text, queries, URLs, and identifiers."""
    summary: dict[str, Any] = {
        "type": event.get("type"),
        "keys": sorted(event),
    }
    item = event.get("item")
    if isinstance(item, dict):
        summary["item"] = {
            "type": item.get("type"),
            "status": item.get("status"),
            "keys": sorted(item),
        }
        action = item.get("action")
        if isinstance(action, dict):
            summary["item"]["action"] = {
                "type": action.get("type"),
                "keys": sorted(action),
            }
    annotation = event.get("annotation")
    if isinstance(annotation, dict):
        summary["annotation"] = {
            "type": annotation.get("type"),
            "keys": sorted(annotation),
        }
    delta = event.get("delta")
    if isinstance(delta, str):
        summary["delta_length"] = len(delta)
    response = event.get("response")
    if isinstance(response, dict):
        error = response.get("error")
        summary["response"] = {
            "status": response.get("status"),
            "error_code": error.get("code") if isinstance(error, dict) else None,
        }
    return summary


async def run_probe(*, model: str, access_token: str) -> int:
    """Run the one-shot hosted-tool probe and emit sanitized JSON lines."""
    url = f"{CODEX_BACKEND_BASE_URL}/responses"
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream(
            "POST",
            url,
            headers=codex_headers(access_token),
            json=probe_payload(model),
        ) as response:
            if response.status_code != 200:
                print(
                    json.dumps(
                        {"http_status": response.status_code, "result": "request_rejected"},
                        sort_keys=True,
                    )
                )
                return 1
            event_name: str | None = None
            data_lines: list[str] = []
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event_name = line.removeprefix("event:").strip()
                elif line.startswith("data:"):
                    data_lines.append(line.removeprefix("data:").lstrip())
                elif not line and data_lines:
                    raw = "\n".join(data_lines)
                    data_lines.clear()
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        print(json.dumps({"type": event_name, "result": "invalid_json"}))
                        event_name = None
                        continue
                    if isinstance(event, dict):
                        if event_name and "type" not in event:
                            event["type"] = event_name
                        print(json.dumps(summarize_event(event), sort_keys=True))
                    event_name = None
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    payload = probe_payload(args.model)
    if args.dry_run:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    token = os.environ.get("CODEX_ASSIST_ACCESS_TOKEN", "").strip()
    if not token:
        print(
            "No integration-owned CODEX_ASSIST_ACCESS_TOKEN is available; live probe not run.",
            file=sys.stderr,
        )
        return 2
    return asyncio.run(run_probe(model=args.model, access_token=token))


if __name__ == "__main__":
    raise SystemExit(main())
