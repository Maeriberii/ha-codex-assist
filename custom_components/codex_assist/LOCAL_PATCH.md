# Maeriberii downstream patches

This fork intentionally keeps the following small changes on top of upstream
`v0.4.2`. They are integration contracts, not generic Codex Assist features.

## Explicit Home Assistant LLM API selection

The options form lists `llm.async_get_apis(hass)` in Advanced chat settings.
The selected `str | list[str]` is passed to `chat_log.async_provide_llm_data`.
The default is only `assist`; configured providers are never auto-enabled.
Legacy single-string values are normalized to a one-item list. An empty
submission is rejected by the options flow, and runtime defensively falls back
to `assist` so `async_provide_llm_data` never receives `[]`.

## Tool-round final synthesis

`MAX_CONVERSATION_TOOL_ITERATIONS` allows eight tool-capable model rounds. If
all of them request tools, one no-tools synthesis request follows, producing a
real final assistant message. A synthesis interrupted by `RemoteProtocolError`
or `ReadError` is retried once after 0.5 seconds only before a text delta emitted.

## Streaming timeout

Responses SSE uses `httpx.Timeout(connect=10, read=None, write=30, pool=10)`.
An overall conversation deadline, if required, belongs around the entire turn,
not as a read timeout on an open SSE stream.
