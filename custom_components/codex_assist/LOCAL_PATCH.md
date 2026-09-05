# Maeriberii downstream delta

This fork is rebased on upstream `v0.4.5`. Upstream implementations are used
unchanged for schema compatibility, strict structured output, authenticated
model discovery, Responses transcript state, web search, citations, and image
handling.

- **Explicit Home Assistant LLM API selection.** Options expose
  `llm.async_get_apis(hass)` as an allowlist. The default is Assist only;
  configured providers are never enabled automatically. Legacy single values
  normalize to a one-item list, empty selections are rejected, and runtime
  falls back to Assist.
- **Configurable runtime limits.** Tool-capable rounds and the Responses
  connect/read/write/pool and image-generation timeouts are bounded options.
  After the selected tool budget is exhausted, upstream's one no-tools final
  synthesis remains in effect.
- **Responses SSE transport policy.** A read timeout of `0` means unlimited
  idle reads for an open SSE response; connect, write, and pool limits stay
  bounded. Auth-retry clients retain the same policy.

These options are runtime-only. Provider transcript state, prompts, tokens,
and tool arguments are not written to options, diagnostics, or telemetry.
