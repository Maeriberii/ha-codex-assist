# Downstream v2 resync map

This branch starts from upstream `main` and keeps upstream mechanics in their
original files. Downstream behavior is isolated in `downstream/` wherever a
small seam is sufficient.

## Upstream-facing seams

- `conversation.py`: selects the explicitly configured HA LLM API allowlist;
  obtains runtime limits and a prompt-cache key; applies bounded replay after
  upstream translation; records content-free request telemetry; and performs
  the one bounded pre-text retry for a tools-disabled final synthesis.
- `ai_task.py`: uses the same runtime, cache, replay, and telemetry seams as
  Conversation, including after its upstream auth-refresh retry.
- `codex_client.py`: accepts caller-supplied generic transport timeouts,
  attaches an optional opaque `prompt_cache_key`, and forwards numeric provider
  usage to downstream telemetry. It does not read Home Assistant options.
- `config_flow.py`: delegates LLM selection and runtime validation to
  downstream policies while retaining the upstream flow structure.

## Downstream-owned modules

- `downstream/runtime_policy.py`: immutable validated tool and timeout policy.
- `downstream/prompt_cache.py`: deterministic SHA-256 cache partition key.
- `downstream/telemetry.py`: content-free payload and provider-usage metrics.
- `downstream/llm_api_policy.py`: explicit API allowlist normalization/defaults.
- `downstream/history_policy.py`: complete-turn replay and image replay bounds.

## Deferred experimental subsystems

Tool-result codecs, reference state, lazy tools, model routing, semantic
history retrieval, and deterministic fast paths are intentionally absent.

## Resync guidance

Fetch and merge upstream first. Resolve only the small hooks listed above in
the upstream-facing files; leave the downstream modules unchanged unless their
explicit policy changes. Do not transplant ChatLog translation, schema
conversion, stream-delta conversion, auth refresh, citations, or image plumbing
into downstream modules.
