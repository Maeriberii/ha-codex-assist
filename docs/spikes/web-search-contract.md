# Codex hosted web-search contract spike

Status: **request/protocol evidence captured; live Codex-backend acceptance still requires a Codex Assist-owned OAuth grant.**

Foundation checkpoint: `d8e2197` (`Harden Codex runtime contracts`)

## Question

Can Codex Assist add hosted web search through its existing Responses request seam without weakening the Home Assistant tool boundary or losing citations?

## Evidence

### First-party OpenAI Responses contract

At OpenAI Python commit [`9917c6e`](https://github.com/openai/openai-python/tree/9917c6e28e66e90e1227b3d223c06a8c5441515a/src/openai/types/responses):

- [`web_search_tool_param.py`](https://github.com/openai/openai-python/blob/9917c6e28e66e90e1227b3d223c06a8c5441515a/src/openai/types/responses/web_search_tool_param.py) defines hosted tools with `type: "web_search"` (or the dated variant). It supports optional domain filters, `low|medium|high` search context, approximate location, and an external-web-access switch.
- Search execution emits distinct progress events:
  - [`response.web_search_call.in_progress`](https://github.com/openai/openai-python/blob/9917c6e28e66e90e1227b3d223c06a8c5441515a/src/openai/types/responses/response_web_search_call_in_progress_event.py)
  - [`response.web_search_call.searching`](https://github.com/openai/openai-python/blob/9917c6e28e66e90e1227b3d223c06a8c5441515a/src/openai/types/responses/response_web_search_call_searching_event.py)
  - [`response.web_search_call.completed`](https://github.com/openai/openai-python/blob/9917c6e28e66e90e1227b3d223c06a8c5441515a/src/openai/types/responses/response_web_search_call_completed_event.py)
- [`response_function_web_search.py`](https://github.com/openai/openai-python/blob/9917c6e28e66e90e1227b3d223c06a8c5441515a/src/openai/types/responses/response_function_web_search.py) defines `web_search_call` output items with search, open-page, or find-in-page actions and a status.
- Citations are structured output annotations, not merely prose conventions. [`response_output_text_annotation_added_event.py`](https://github.com/openai/openai-python/blob/9917c6e28e66e90e1227b3d223c06a8c5441515a/src/openai/types/responses/response_output_text_annotation_added_event.py) defines `response.output_text.annotation.added`; `url_citation` includes title, URL, and text-span indexes. [`response_output_text.py`](https://github.com/openai/openai-python/blob/9917c6e28e66e90e1227b3d223c06a8c5441515a/src/openai/types/responses/response_output_text.py) also carries annotations on completed output text.

These files are generated from the first-party [OpenAI OpenAPI repository](https://github.com/openai/openai-openapi/tree/172101000e7be21103c405aa8bedf918039f886f).

### Public fork evidence

Fork commit [`d73bed5`](https://github.com/greimela/ha-codex-assist/commit/d73bed5b5426) adds a default-off option and appends exactly `{"type": "web_search"}` to the same tools list as HA function tools. That is a plausible request shape and matches the first-party contract.

The follow-up commits [`9876bb8`](https://github.com/greimela/ha-codex-assist/commit/9876bb807ee7) and [`a0b12a7`](https://github.com/greimela/ha-codex-assist/commit/a0b12a7e902b) strip Markdown links/source sections with regular expressions for TTS. They do **not** parse or preserve `url_citation` annotations, record raw web-search events, prove model/plan support, or show hosted CI/live probe evidence. Therefore the fork demonstrates a small product wiring idea, not a verified backend contract.

## Repository fit

The existing `CodexClient` already passes tool dictionaries through the Responses payload, so no provider abstraction or plugin registry is needed. However, its public stream delta model currently represents only text and HA function calls. Unknown search progress and annotation events are ignored.

That means simply copying the fork could produce text, but it would throw away the structured citation contract and then guess at citations with regex. We should not ship that behavior.

## Privacy-safe probe artifact

`scripts/probe_web_search_contract.py` sends one fixed request:

- no HA state, entity IDs, conversation history, attachments, tool results, location, or user text;
- `store: false`;
- `search_context_size: low`;
- results restricted to `iana.org`;
- sanitized output containing event names/key shapes and annotation types only—never response text, queries, URLs, IDs, or credentials.

Dry run:

```bash
uv run python scripts/probe_web_search_contract.py --dry-run
```

Live run requires an access token issued to **Codex Assist itself**:

```bash
CODEX_ASSIST_ACCESS_TOKEN='[ephemeral integration-owned token]' \
  uv run python scripts/probe_web_search_contract.py
```

Do not source that token from Codex CLI, an editor, or another assistant. The probe intentionally refuses to run without an explicitly supplied integration-owned token.

## Executed result

- Dry run succeeded and produced the fixed request payload.
- Privacy/sanitization tests passed.
- No integration-owned token exists in this checkout/session, so the live network request was **not** run.
- No Codex CLI/editor credentials were inspected or copied.

## Decision

**Proceed with web search, but do not port the fork directly.** The likely implementation is small at the request seam, default-off, and can coexist with HA tools. Before user-facing implementation, obtain one dedicated Codex Assist OAuth authorization and run the sanitized probe to establish:

1. whether the ChatGPT Codex backend accepts `web_search` for supported models/plans;
2. exact progress/output/annotation events it emits;
3. unsupported-model and usage-limit error shapes;
4. whether URL citations can be converted into visible HA chat links while the TTS path receives citation-free speech.

If live evidence matches the first-party contract, add an explicit citation delta/result type in `CodexClient`, preserve citations for displayed Assist/AI Task output, and clean only the TTS rendering. Keep search opt-in and never automatically turn HA state, attachments, or tool output into search queries.
