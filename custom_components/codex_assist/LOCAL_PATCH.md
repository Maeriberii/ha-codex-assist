# Local behavioral differences from upstream

- Runtime limits for tool rounds and transport/image timeouts are configurable
  and normalized from persisted entry settings.
- Each Conversation agent explicitly selects its Home Assistant LLM API
  allowlist; unconfigured entries retain the conservative Assist default.
- Responses requests use an opaque, stable prompt-cache key per entry and
  conversation/task scope.
- Stateless replay retains at most 24 items / 128 KiB where possible, keeps the
  newest complete user-led turn intact, and replays image payloads only for the
  two newest user turns. This is a replay target, not a tool-result codec limit.
- Payload and provider-usage telemetry records numeric/count metadata only.
- The final tools-disabled synthesis has the existing narrow pre-text transport
  retry; normal tool-capable rounds do not retry.

No lossy tool-result codec, model routing, semantic history retrieval, or new
provider protocol is introduced here. `codex_protocol.py` remains the owner of
native provider transcript/state and `codex_runtime.py` coordinates token
refresh.
