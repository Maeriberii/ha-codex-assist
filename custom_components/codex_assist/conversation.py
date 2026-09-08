from __future__ import annotations

import logging

import httpx
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent, llm
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.httpx_client import get_async_client

from . import DOMAIN, serialization, telemetry, transcript, turn_runtime  # noqa: F401
from .codex_auth import (
    CodexAuthClient,
    CodexAuthTemporaryError,
    CodexReauthRequiredError,
)
from .codex_client import (
    CodexAuthenticationError,
    CodexCitation,
    CodexClient,
    CodexRateLimitError,
)
from .codex_runtime import refresh_runtime_tokens, runtime_token_coordinator
from .error_formatting import request_failure_text
from .settings import (
    CONF_LLM_HASS_API,
    CONF_WEB_SEARCH,
    DEFAULT_MODEL,
    DEFAULT_PROMPT,
    DEFAULT_REASONING_EFFORT,
    DEFAULT_REASONING_SUMMARY,
    DEFAULT_TEXT_VERBOSITY,
    DEFAULT_WEB_SEARCH,
    RuntimeSettings,
    default_llm_api_selection,
    prompt_cache_key,
)
from .transcript import (
    codex_input_from_chat_log,
    codex_tools_from_chat_log,
    instructions_from_chat_log,
)

try:
    from homeassistant.const import CONF_LLM_HASS_API
except ImportError:
    CONF_LLM_HASS_API = "llm_hass_api"

MAX_TOOL_ITERATIONS = 5
MAX_CODEX_INPUT_ITEMS = 24
MAX_CODEX_HISTORY_BYTES = 128 * 1024
IMAGE_HISTORY_USER_TURNS = 2
MAX_IMAGE_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_IMAGE_ATTACHMENTS = 4
MAX_TOTAL_IMAGE_ATTACHMENT_BYTES = 20 * 1024 * 1024
LOGGER = logging.getLogger(__name__)
_WEB_SEARCH_CITATION_INSTRUCTIONS = (
    "When using web search, do not include raw URLs, markdown links, or a Source/Sources "
    "section in the response text. Refer to sources by human-readable names only. The "
    "integration renders structured citations separately."
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([CodexAssistConversationEntity(entry)])


class CodexAssistConversationEntity(
    conversation.ConversationEntity,
    conversation.AbstractConversationAgent,
):
    _attr_has_entity_name = True
    _attr_name = "Codex Assist"
    _attr_supported_features = conversation.ConversationEntityFeature.CONTROL
    _attr_supports_streaming = True

    def __init__(self, entry: ConfigEntry) -> None:
        self.entry = entry
        self._attr_unique_id = entry.entry_id

    @property
    def supported_languages(self) -> list[str] | str:
        return MATCH_ALL

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        conversation.async_set_agent(self.hass, self.entry, self)

    async def async_will_remove_from_hass(self) -> None:
        conversation.async_unset_agent(self.hass, self.entry)
        await super().async_will_remove_from_hass()

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        settings = RuntimeSettings.from_entry(self.entry.data, self.entry.options)
        runtime_options = settings.runtime_options
        model = settings.get("model", DEFAULT_MODEL)
        prompt = settings.get("prompt", DEFAULT_PROMPT)
        reasoning_effort = settings.get("reasoning_effort", DEFAULT_REASONING_EFFORT)
        reasoning_summary = settings.get("reasoning_summary", DEFAULT_REASONING_SUMMARY)
        text_verbosity = settings.get("text_verbosity", DEFAULT_TEXT_VERBOSITY)
        web_search = bool(settings.get(CONF_WEB_SEARCH, DEFAULT_WEB_SEARCH))
        llm_hass_api = default_llm_api_selection(
            settings.get(CONF_LLM_HASS_API), assist_api_id=llm.LLM_API_ASSIST
        )
        citations: list[CodexCitation] = []
        cache_key = prompt_cache_key(
            self.entry.entry_id,
            getattr(user_input, "conversation_id", None)
            or getattr(chat_log, "conversation_id", None),
        )

        response = intent.IntentResponse(language=user_input.language)
        try:
            await chat_log.async_provide_llm_data(
                user_input.as_llm_context(DOMAIN),
                llm_hass_api,
                prompt,
                user_input.extra_system_prompt,
            )
        except conversation.ConverseError as err:
            return err.as_conversation_result()

        http_client = get_async_client(self.hass)
        auth_client = CodexAuthClient(http_client=http_client)
        try:
            tokens = await runtime_token_coordinator(self.entry).resolve(
                lambda: self.entry.data,
                auth_client=auth_client,
                async_update_entry_data=lambda data: self.hass.config_entries.async_update_entry(
                    self.entry,
                    data=data,
                ),
            )
        except CodexReauthRequiredError as err:
            LOGGER.warning("Codex Assist authentication failed; starting reauth flow: %s", err)
            return _start_reauth_result(self.hass, self.entry, response, user_input)
        except (CodexAuthTemporaryError, RuntimeError) as err:
            LOGGER.exception("Codex Assist authentication failed")
            chat_log.async_add_assistant_content_without_tools(
                conversation.AssistantContent(
                    agent_id=user_input.agent_id,
                    content=_request_failure_text(err),
                )
            )
            return conversation.async_get_result_from_chat_log(user_input, chat_log)

        codex = CodexClient(
            http_client=http_client,
            access_token=tokens.access_token,
            stream_timeout=runtime_options.stream_timeout,
            image_generation_timeout=runtime_options.image_generation_timeout,
        )
        try:
            for _iteration in range(runtime_options.tool_iterations + 1):
                allow_tools = _iteration < runtime_options.tool_iterations
                try:
                    tool_call_requested = await turn_runtime.stream_codex_turn_into_chat_log(
                        chat_log=chat_log,
                        codex=codex,
                        entity_id=self.entity_id or "",
                        model=model,
                        instructions=_instructions_for_turn(
                            chat_log, prompt, web_search=web_search
                        ),
                        input_items=await codex_input_from_chat_log(self.hass, chat_log),
                        tools=(
                            codex_tools_from_chat_log(chat_log, enable_web_search=web_search)
                            if allow_tools
                            else []
                        ),
                        reasoning_effort=reasoning_effort,
                        reasoning_summary=reasoning_summary,
                        text_verbosity=text_verbosity,
                        allow_tools=allow_tools,
                        citation_sink=citations,
                        prompt_cache_key=cache_key,
                        round_number=_iteration + 1,
                    )
                except CodexAuthenticationError as err:
                    LOGGER.warning(
                        "Codex Assist access token was rejected; refreshing and retrying once: %s",
                        err,
                    )
                    try:
                        tokens = await refresh_runtime_tokens(
                            self.hass,
                            self.entry,
                            auth_client,
                            tokens,
                        )
                    except CodexReauthRequiredError as refresh_err:
                        LOGGER.warning(
                            "Codex Assist token refresh failed; starting reauth flow: %s",
                            refresh_err,
                        )
                        return _start_reauth_result(
                            self.hass,
                            self.entry,
                            response,
                            user_input,
                        )
                    codex = CodexClient(
                        http_client=http_client,
                        access_token=tokens.access_token,
                        stream_timeout=runtime_options.stream_timeout,
                        image_generation_timeout=runtime_options.image_generation_timeout,
                    )
                    try:
                        tool_call_requested = await turn_runtime.stream_codex_turn_into_chat_log(
                            chat_log=chat_log,
                            codex=codex,
                            entity_id=self.entity_id or "",
                            model=model,
                            instructions=_instructions_for_turn(
                                chat_log, prompt, web_search=web_search
                            ),
                            input_items=await codex_input_from_chat_log(self.hass, chat_log),
                            tools=(
                                codex_tools_from_chat_log(chat_log, enable_web_search=web_search)
                                if allow_tools
                                else []
                            ),
                            reasoning_effort=reasoning_effort,
                            reasoning_summary=reasoning_summary,
                            text_verbosity=text_verbosity,
                            allow_tools=allow_tools,
                            citation_sink=citations,
                            prompt_cache_key=cache_key,
                            round_number=_iteration + 1,
                        )
                    except CodexAuthenticationError as retry_err:
                        LOGGER.warning(
                            "Codex Assist token was rejected after refresh; "
                            "starting reauth flow: %s",
                            retry_err,
                        )
                        return _start_reauth_result(
                            self.hass,
                            self.entry,
                            response,
                            user_input,
                        )
                if not tool_call_requested:
                    break
        except CodexRateLimitError as err:
            LOGGER.warning("Codex Assist hit usage or rate limit: %s", err)
            chat_log.async_add_assistant_content_without_tools(
                conversation.AssistantContent(
                    agent_id=user_input.agent_id,
                    content=(
                        "Codex Assist has hit your ChatGPT/Codex usage limit or is being "
                        "rate limited. Wait a while and try again, or check your plan's "
                        "usage limits."
                    ),
                )
            )
        except (httpx.HTTPError, RuntimeError) as err:
            LOGGER.exception("Codex Assist model request failed")
            text = _request_failure_text(err)
            chat_log.async_add_assistant_content_without_tools(
                conversation.AssistantContent(
                    agent_id=user_input.agent_id,
                    content=text,
                )
            )
        except (ValueError, TypeError) as err:
            LOGGER.exception("Codex Assist tool handling failed")
            text = f"Codex Assist tool handling failed: {err}"
            chat_log.async_add_assistant_content_without_tools(
                conversation.AssistantContent(
                    agent_id=user_input.agent_id,
                    content=text,
                )
            )

        result = conversation.async_get_result_from_chat_log(user_input, chat_log)
        _attach_citations_card(result, citations)
        return result


def _request_failure_text(err: BaseException) -> str:
    """Return a useful user-facing failure even for blank transport errors."""
    return request_failure_text("Codex Assist failed", err)


def _citation_lines(citations: list[CodexCitation]) -> str:
    return "\n".join(f"- {citation.title} — <{citation.url}>" for citation in citations)


def _attach_citations_card(
    result: conversation.ConversationResult,
    citations: list[CodexCitation],
) -> None:
    if not citations:
        return
    result.response.async_set_card("Sources", _citation_lines(citations))


def _start_reauth_result(
    hass: HomeAssistant,
    entry: ConfigEntry,
    response: intent.IntentResponse,
    user_input: conversation.ConversationInput,
) -> conversation.ConversationResult:
    entry.async_start_reauth(hass)
    response.async_set_speech(
        "Codex Assist needs you to sign in again. Open Home Assistant repairs "
        "or the integration page to reauthenticate."
    )
    return conversation.ConversationResult(
        response=response,
        conversation_id=user_input.conversation_id,
    )


def _instructions_for_turn(
    chat_log: conversation.ChatLog,
    fallback_prompt: str,
    *,
    web_search: bool,
) -> str:
    instructions = instructions_from_chat_log(chat_log, fallback_prompt)
    if not web_search:
        return instructions
    return f"{instructions.rstrip()}\n\n{_WEB_SEARCH_CITATION_INSTRUCTIONS}"
