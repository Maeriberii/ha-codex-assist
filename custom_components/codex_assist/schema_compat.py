"""OpenAPI schema conversion across supported Home Assistant releases."""

# Prefer the converter exported by Home Assistant so it stays paired with HA's
# selector serializer and UNSUPPORTED sentinel. HA 2026.10 no longer re-exports
# it from ``homeassistant.helpers.llm`` and uses Probatio directly instead.
try:
    from homeassistant.helpers import llm
except ImportError:
    llm = None

if llm is not None and (to_openapi := getattr(llm, "to_openapi", None)) is None:
    to_openapi = getattr(llm, "convert", None)

if llm is None or to_openapi is None:
    try:
        from probatio import to_openapi
    except ImportError:
        from voluptuous_openapi import convert as to_openapi

__all__ = ["to_openapi"]
