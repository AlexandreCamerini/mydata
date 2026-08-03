"""Client for every public service brapi.dev exposes.

brapi.dev bundles several unrelated data feeds behind one API: B3 stock quotes
and fundamentals, options chains, crypto, FX, inflation, and the SELIC/prime
rate. Each family below is a thin, honest wrapper around one documented
endpoint group — it builds the URL and query string, handles auth/retries,
and hands back the parsed JSON as-is.

Deliberately not modeled as typed dataclasses: brapi's response shape varies
by `modules`/`fundamental`/`dividends` flags and by asset type (stock vs FII
vs BDR vs index), and getting that schema wrong silently would be worse than
just returning the dict the API actually sent. Callers that need a stable
shape should map the fields they use at the call site.

Auth: pass `token=` to the constructor, or set the BRAPI_TOKEN environment
variable. The four sandbox tickers (PETR4, MGLU3, VALE3, ITUB4) work
unauthenticated for the quote endpoint; most other endpoints require a token
on brapi's free plan.

Underlying data sources and freshness (brapi is an aggregator, not the
primary source — treat it as a convenience cache, not ground truth for
anything that matters):

    | Service                          | Primary source        | Freshness                     |
    |-----------------------------------|------------------------|--------------------------------|
    | quote (stock price)               | B3                     | delayed by plan: free ~30min, startup ~15min, pro ~5min |
    | quote fundamentals (BP/DRE/DFC/DVA)| CVM                   | quarterly (CVM's own filing cadence) |
    | financial indices                 | Yahoo Finance          | not confirmed                 |
    | currency (FX)                     | awesomeapi + BCB/forex | not confirmed                 |
    | inflation, prime_rate             | BCB                    | not confirmed (BCB series are typically D-1) |
    | crypto                            | not confirmed          | not confirmed                 |

    Confidence: MEDIUM. brapi.dev's docs/FAQ pages return HTTP 403 to direct
    fetches from this codebase's dev environment (bot protection), so this
    table is built from search-indexed snippets of their FAQ
    (brapi.dev/faq/fonte-de-dados, brapi.dev/faq/qual-a-frequencia), not a
    verified read of the full page. Re-confirm against the live FAQ or a
    real API response before relying on this for a product decision.
"""

from __future__ import annotations

import os
import time
from typing import Any, Iterable

import requests

from .exceptions import (
    BrapiAuthError,
    BrapiError,
    BrapiHTTPError,
    BrapiNotFoundError,
    BrapiRateLimitError,
)

BASE_URL = "https://brapi.dev/api"
DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.0


def _csv(value: str | Iterable[str]) -> str:
    """Accept either "PETR4,VALE3" or ["PETR4", "VALE3"] — both are natural to pass."""
    if isinstance(value, str):
        return value
    return ",".join(value)


class BrapiClient:
    def __init__(
        self,
        token: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        session: requests.Session | None = None,
    ):
        self.token = token or os.environ.get("BRAPI_TOKEN")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.session = session or requests.Session()

    # -- transport -----------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": "brapi-client/0.1 (+https://github.com/)"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{BASE_URL}{path}"
        params = {k: v for k, v in (params or {}).items() if v is not None}

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(
                    url, params=params, headers=self._headers(), timeout=self.timeout
                )
            except requests.RequestException as e:
                last_exc = e
                if attempt < self.max_retries:
                    time.sleep(self.backoff_base * (2 ** (attempt - 1)))
                    continue
                raise BrapiError(f"Failed to reach {url}: {e}") from e  # noqa: F821

            if resp.status_code == 429:
                if attempt < self.max_retries:
                    retry_after = resp.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after else self.backoff_base * (2 ** (attempt - 1))
                    time.sleep(wait)
                    continue
                raise BrapiRateLimitError(resp.status_code, url, resp.text)

            if resp.status_code >= 500:
                if attempt < self.max_retries:
                    time.sleep(self.backoff_base * (2 ** (attempt - 1)))
                    continue
                raise BrapiHTTPError(resp.status_code, url, resp.text)

            if resp.status_code in (401, 403):
                raise BrapiAuthError(resp.status_code, url, resp.text)
            if resp.status_code == 404:
                raise BrapiNotFoundError(resp.status_code, url, resp.text)
            if not resp.ok:
                raise BrapiHTTPError(resp.status_code, url, resp.text)

            return resp.json()

        # Only reached if every attempt raised a RequestException.
        raise BrapiError(f"Failed to reach {url} after {self.max_retries} attempts") from last_exc

    # -- Ações (stocks / FIIs / BDRs / indices) -------------------------

    def quote(
        self,
        tickers: str | Iterable[str],
        *,
        range: str | None = None,
        interval: str | None = None,
        fundamental: bool | None = None,
        dividends: bool | None = None,
        modules: str | Iterable[str] | None = None,
        **extra: Any,
    ) -> Any:
        """GET /api/quote/{tickers} — current price + optional history/fundamentals/dividends.

        `range`/`interval` add an OHLCV series (e.g. range="1mo", interval="1d").
        `modules` enriches the response with detailed financial data modules
        (comma-separated names, e.g. "balanceSheetHistory,defaultKeyStatistics").
        """
        params = {
            "range": range,
            "interval": interval,
            "fundamental": fundamental,
            "dividends": dividends,
            "modules": _csv(modules) if modules else None,
            **extra,
        }
        return self._get(f"/quote/{_csv(tickers)}", params)

    def quote_list(
        self,
        *,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        **extra: Any,
    ) -> Any:
        """GET /api/quote/list — every ticker brapi tracks, with paging/sort/search.

        `sort_by` accepts brapi's field names verbatim (e.g. "name", "close",
        "change", "volume", "market_cap_basic", "sector"); `sort_order` is
        "asc" or "desc".
        """
        params = {"search": search, "sortBy": sort_by, "sortOrder": sort_order, **extra}
        return self._get("/quote/list", params)

    def available(self, search: str | None = None, **extra: Any) -> Any:
        """GET /api/available — check which tickers exist / search by prefix."""
        params = {"search": search, **extra}
        return self._get("/available", params)

    # -- Opções ----------------------------------------------------------

    def options_expirations(self, underlying: str, **extra: Any) -> Any:
        """GET /api/v2/options/expirations?underlying=X — available expiration dates."""
        return self._get("/v2/options/expirations", {"underlying": underlying, **extra})

    def options_strikes(self, underlying: str, **extra: Any) -> Any:
        """GET /api/v2/options/strikes?underlying=X — available strike prices."""
        return self._get("/v2/options/strikes", {"underlying": underlying, **extra})

    def options_chain(self, underlying: str, **extra: Any) -> Any:
        """GET /api/v2/options/chain?underlying=X — the full options chain."""
        return self._get("/v2/options/chain", {"underlying": underlying, **extra})

    def options_analytics(self, underlying: str, **extra: Any) -> Any:
        """GET /api/v2/options/analytics?underlying=X — greeks/IV analytics."""
        return self._get("/v2/options/analytics", {"underlying": underlying, **extra})

    def options_historical(self, symbol: str, **extra: Any) -> Any:
        """GET /api/v2/options/historical?symbol=X — EOD history for one option contract."""
        return self._get("/v2/options/historical", {"symbol": symbol, **extra})

    def options_analytics_history(self, symbol: str, **extra: Any) -> Any:
        """GET /api/v2/options/analytics/history?symbol=X — historical greeks/IV for one contract."""
        return self._get("/v2/options/analytics/history", {"symbol": symbol, **extra})

    # -- Criptomoedas ------------------------------------------------------

    def crypto(self, coins: str | Iterable[str], currency: str = "BRL", **extra: Any) -> Any:
        """GET /api/v2/crypto?coin=X&currency=Y — real-time crypto quote(s)."""
        return self._get("/v2/crypto", {"coin": _csv(coins), "currency": currency, **extra})

    def crypto_available(self, search: str | None = None, **extra: Any) -> Any:
        """GET /api/v2/crypto/available — every crypto ticker brapi supports."""
        return self._get("/v2/crypto/available", {"search": search, **extra})

    # -- Moedas (FX) -------------------------------------------------------

    def currency(self, pairs: str | Iterable[str], **extra: Any) -> Any:
        """GET /api/v2/currency?currency=X — bid/ask/variation for one or more pairs (e.g. "USD-BRL")."""
        return self._get("/v2/currency", {"currency": _csv(pairs), **extra})

    def currency_available(self, search: str | None = None, **extra: Any) -> Any:
        """GET /api/v2/currency/available — every currency pair brapi supports."""
        return self._get("/v2/currency/available", {"search": search, **extra})

    # -- Inflação ------------------------------------------------------------

    def inflation(
        self,
        country: str = "brazil",
        *,
        historical: bool | None = None,
        start: str | None = None,
        end: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        **extra: Any,
    ) -> Any:
        """GET /api/v2/inflation?country=X — current (or historical, with `historical=true`) inflation series."""
        params = {
            "country": country,
            "historical": historical,
            "start": start,
            "end": end,
            "sortBy": sort_by,
            "sortOrder": sort_order,
            **extra,
        }
        return self._get("/v2/inflation", params)

    def inflation_available(self, **extra: Any) -> Any:
        """GET /api/v2/inflation/available — every country brapi has inflation data for."""
        return self._get("/v2/inflation/available", extra)

    # -- Taxa básica de juros (SELIC / prime rate) --------------------------

    def prime_rate(
        self,
        country: str = "brazil",
        *,
        historical: bool | None = None,
        start: str | None = None,
        end: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        **extra: Any,
    ) -> Any:
        """GET /api/v2/prime-rate?country=X — current (or historical) base interest rate."""
        params = {
            "country": country,
            "historical": historical,
            "start": start,
            "end": end,
            "sortBy": sort_by,
            "sortOrder": sort_order,
            **extra,
        }
        return self._get("/v2/prime-rate", params)

    def prime_rate_available(self, **extra: Any) -> Any:
        """GET /api/v2/prime-rate/available — every country brapi has a base rate for."""
        return self._get("/v2/prime-rate/available", extra)
