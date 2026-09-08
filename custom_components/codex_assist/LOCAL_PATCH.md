# Local behavioral differences from upstream

- Runtime limits for tool rounds and transport/image timeouts are configurable
  and normalized from persisted entry settings.
- Conversation explicitly selects its Home Assistant LLM API allowlist; the
  unconfigured default remains Assist only.
- Responses requests use an opaque stable prompt-cache key for an entry and
  conversation/task scope.
- Replay targets 24 items / 128 KiB, preserves the newest complete user-led
  turn, and replays images for only the two newest user turns. Tool results use
  compact lossless JSON; no lossy codec is introduced here.
- Payload and provider-usage telemetry contains numeric/count metadata only.
- The existing narrow final tools-disabled pre-text transport retry remains;
  normal tool-capable rounds do not retry.

Native provider state remains owned by `codex_protocol.py`; token refresh
coordination remains owned by `codex_runtime.py`.
