"""Authenticated discovery using an entry's owned credentials and cache."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.httpx_client import get_async_client

from .codex_auth import CodexAuthClient, CodexAuthTemporaryError, CodexReauthRequiredError
from .codex_models import ModelCatalog, ModelDiscoveryError, fetch_codex_model_ids
from .codex_runtime import runtime_token_coordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


async def async_entry_model_catalog(
    hass: HomeAssistant, entry: ConfigEntry, *, force: bool = False
) -> ModelCatalog:
    coordinator = runtime_token_coordinator(entry)
    http_client = get_async_client(hass)
    auth_client = CodexAuthClient(http_client=http_client)

    def update(data: dict) -> None:
        hass.config_entries.async_update_entry(entry, data=data)

    async def fetch() -> list[str]:
        try:
            tokens = await coordinator.resolve(
                lambda: entry.data,
                auth_client=auth_client,
                async_update_entry_data=update,
            )
            try:
                return await fetch_codex_model_ids(
                    http_client=http_client, access_token=tokens.access_token
                )
            except ModelDiscoveryError as err:
                if err.reason != "authentication":
                    raise
            tokens = await coordinator.refresh_after_rejection(
                lambda: entry.data,
                rejected_tokens=tokens,
                auth_client=auth_client,
                async_update_entry_data=update,
            )
            return await fetch_codex_model_ids(
                http_client=http_client, access_token=tokens.access_token
            )
        except CodexReauthRequiredError as err:
            raise ModelDiscoveryError("authentication") from err
        except CodexAuthTemporaryError as err:
            raise ModelDiscoveryError() from err

    return await coordinator.model_cache.async_get(fetch, force=force)
