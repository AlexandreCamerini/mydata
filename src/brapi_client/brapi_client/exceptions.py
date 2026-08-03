"""Exceptions raised by :mod:`brapi_client`."""

from __future__ import annotations


class BrapiError(Exception):
    """Base class for all brapi_client errors."""


class BrapiHTTPError(BrapiError):
    """The API responded with a non-2xx status code."""

    def __init__(self, status_code: int, url: str, body: str):
        self.status_code = status_code
        self.url = url
        self.body = body
        super().__init__(f"brapi.dev returned HTTP {status_code} for {url}: {body[:300]}")


class BrapiAuthError(BrapiHTTPError):
    """401/403 — missing or invalid token for this endpoint/plan."""


class BrapiRateLimitError(BrapiHTTPError):
    """429 — too many requests, or 403 responses that read as a hard-capped plan/day limit."""


class BrapiNotFoundError(BrapiHTTPError):
    """404 — unknown ticker/symbol/country, or a route that doesn't exist."""
