"""OpenAPI schema conversion across supported Home Assistant releases."""

from homeassistant.helpers import llm

# Use the converter paired with HA's serializer and its UNSUPPORTED sentinel.
# Package availability is insufficient: older HA may also have Probatio installed.
try:
    to_openapi = llm.to_openapi
except AttributeError:
    to_openapi = llm.convert

__all__ = ["to_openapi"]
