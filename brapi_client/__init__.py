"""A client covering every public service on brapi.dev (Brazilian market data API)."""

from .client import BrapiClient
from .exceptions import (
    BrapiAuthError,
    BrapiError,
    BrapiHTTPError,
    BrapiNotFoundError,
    BrapiRateLimitError,
)

__all__ = [
    "BrapiClient",
    "BrapiError",
    "BrapiHTTPError",
    "BrapiAuthError",
    "BrapiRateLimitError",
    "BrapiNotFoundError",
]

__version__ = "0.1.0"
