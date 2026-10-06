"""OpenAPI schema conversion across supported Home Assistant releases."""

# HA 2026.9+ owns the native Probatio converter.  In 2026.10 the converter
# is no longer re-exported from ``homeassistant.helpers.llm``.
try:
    from probatio import to_openapi
except ImportError:
    from homeassistant.helpers import llm

    to_openapi = getattr(llm, "to_openapi", None) or getattr(llm, "convert", None)
    if to_openapi is None:
        from voluptuous_openapi import convert as to_openapi

__all__ = ["to_openapi"]
