"""OpenAPI schema conversion across supported Home Assistant releases."""

try:
    from probatio import to_openapi
except ImportError:
    from voluptuous_openapi import convert as to_openapi

__all__ = ["to_openapi"]
