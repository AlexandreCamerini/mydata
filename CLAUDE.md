# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Structure

```
scrap/
├── brapi_client/       # the package
│   ├── client.py       # BrapiClient — one method per brapi.dev endpoint family
│   ├── exceptions.py   # BrapiError and its HTTP-status-specific subclasses
│   └── __init__.py     # public exports
├── tests/
│   └── test_client.py  # all HTTP mocked — no live network calls, no quota burned
└── pyproject.toml
```

`brapi_client` is a thin wrapper around [brapi.dev](https://brapi.dev), a free
API for B3 (Brazilian stock exchange) market data. It covers every service
family the API exposes: ações (quote/list/available), opções, criptomoedas,
moedas (FX), inflação, and taxa básica de juros (SELIC/prime rate).

**Deliberate design choice**: responses are returned as raw parsed JSON, not
typed dataclasses. brapi's response shape varies with request flags
(`modules`, `fundamental`, `dividends`) and asset type, and modeling that
precisely wasn't verified against real payloads (brapi.dev's docs site blocks
direct fetches from this environment — the endpoint/param names here come
from search-indexed doc snippets, cross-checked but not hit live). If you add
typed models later, verify field names against real API responses first.

**brapi is an aggregator, not a primary source.** Don't treat it as ground
truth for anything that matters — it re-publishes data from elsewhere, on its
own delay:

| Service | Primary source | Freshness |
|---|---|---|
| quote (stock price) | B3 | delayed by plan: free ~30min, startup ~15min, pro ~5min |
| quote fundamentals (BP/DRE/DFC/DVA) | CVM | quarterly (CVM's filing cadence) |
| financial indices | Yahoo Finance | not confirmed |
| currency (FX) | awesomeapi + BCB/forex | not confirmed |
| inflation, prime_rate | BCB | not confirmed (BCB series are typically D-1) |
| crypto | not confirmed | not confirmed |

Confidence: MEDIUM, same caveat as above — this comes from search-indexed
snippets of brapi.dev's FAQ (`/faq/fonte-de-dados`, `/faq/qual-a-frequencia`),
not a verified read of the live page. Re-confirm before a decision leans on
it. (Full table with the same caveat is duplicated in `client.py`'s module
docstring, right where the endpoints that pull this data are defined —
update both together if you re-verify it.)

## Setup

```bash
pip install -e ".[dev]"
```

Requires Python >=3.10. Only third-party runtime dependency is `requests`.

Auth: pass `token=` to `BrapiClient(...)`, or set `BRAPI_TOKEN` in the
environment. The quote endpoint works unauthenticated for brapi's four
sandbox tickers (PETR4, MGLU3, VALE3, ITUB4); most other endpoints need a
token on brapi's free plan.

## Test

```bash
python3 -m pytest tests/ -v          # all tests
python3 -m pytest tests/test_client.py::test_quote_single_ticker  # one test
```

Tests mock `requests.Session.get` (via `unittest.mock`) — none of them touch
the network. Keep it that way: hitting the real API from tests would burn
the free-tier quota just from running `pytest` and make CI flaky/rate-limited.

## Build/run

No build step — it's a plain importable package (`from brapi_client import
BrapiClient`). Nothing else lives in this repo to run.

## Lint/format

None configured yet. If you add one, prefer `ruff` (format + lint in one
tool) over a black+flake8+isort stack, and document the invocation here.

## Conventions

- One public method per brapi.dev endpoint, named after what it returns
  (`quote`, `crypto`, `prime_rate`), not after the HTTP path.
- Endpoint methods accept confirmed parameters explicitly (typed, with
  docstrings) and pass through anything else via `**extra` — don't guess at
  undocumented parameter names by hardcoding them; let the caller pass them
  through instead.
- All retry/backoff/error-mapping logic lives in `BrapiClient._get` — new
  endpoint methods should call `self._get(path, params)` rather than
  reimplementing HTTP handling.
- `snake_case` on the Python side is mapped to brapi's actual `camelCase`
  query params (e.g. `sort_by` → `sortBy`) inside the method, not pushed onto
  callers.

## Branching/PR workflow

Standard git flow — no repo-specific conventions beyond what's in this
session's branch/PR instructions.
