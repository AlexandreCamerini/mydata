"""Tests for brapi_client.BrapiClient.

All HTTP is mocked — these tests never hit the network, both so they run
offline/in CI and so they don't burn brapi.dev's free-tier quota just by
existing. What's being verified is that each method builds the right
URL/query string and that the retry/error-mapping logic in _get behaves
correctly, not that brapi.dev's actual responses match some assumed shape
(the client intentionally returns raw JSON rather than asserting a schema —
see client.py's module docstring for why).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from brapi_client import (
    BrapiAuthError,
    BrapiClient,
    BrapiError,
    BrapiHTTPError,
    BrapiNotFoundError,
    BrapiRateLimitError,
)


def make_response(status_code=200, json_data=None, headers=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.headers = headers or {}
    resp.text = text or str(json_data)
    resp.json.return_value = json_data if json_data is not None else {}
    return resp


@pytest.fixture
def client():
    c = BrapiClient(token="test-token", backoff_base=0.0)
    c.session = MagicMock(spec=requests.Session)
    return c


# -- URL / param construction, one per endpoint family ----------------------


def test_quote_single_ticker(client):
    client.session.get.return_value = make_response(json_data={"results": [{"symbol": "PETR4"}]})
    result = client.quote("PETR4")
    assert result == {"results": [{"symbol": "PETR4"}]}
    url, kwargs = client.session.get.call_args
    assert url[0] == "https://brapi.dev/api/quote/PETR4"
    assert kwargs["params"] == {}


def test_quote_multiple_tickers_and_options(client):
    client.session.get.return_value = make_response(json_data={"results": []})
    client.quote(
        ["PETR4", "VALE3"],
        range="1mo",
        interval="1d",
        fundamental=True,
        dividends=True,
        modules=["balanceSheetHistory", "defaultKeyStatistics"],
    )
    url, kwargs = client.session.get.call_args
    assert url[0] == "https://brapi.dev/api/quote/PETR4,VALE3"
    assert kwargs["params"] == {
        "range": "1mo",
        "interval": "1d",
        "fundamental": True,
        "dividends": True,
        "modules": "balanceSheetHistory,defaultKeyStatistics",
    }


def test_quote_list_maps_snake_case_to_brapi_camel_case(client):
    client.session.get.return_value = make_response(json_data={"stocks": []})
    client.quote_list(search="PETR", sort_by="close", sort_order="desc")
    url, kwargs = client.session.get.call_args
    assert url[0] == "https://brapi.dev/api/quote/list"
    assert kwargs["params"] == {"search": "PETR", "sortBy": "close", "sortOrder": "desc"}


def test_available(client):
    client.session.get.return_value = make_response(json_data={"stocks": ["PETR4"]})
    client.available(search="PETR")
    url, kwargs = client.session.get.call_args
    assert url[0] == "https://brapi.dev/api/available"
    assert kwargs["params"] == {"search": "PETR"}


@pytest.mark.parametrize(
    "method,args,path",
    [
        ("options_expirations", ("PETR4",), "/v2/options/expirations"),
        ("options_strikes", ("PETR4",), "/v2/options/strikes"),
        ("options_chain", ("PETR4",), "/v2/options/chain"),
        ("options_analytics", ("PETR4",), "/v2/options/analytics"),
    ],
)
def test_options_underlying_endpoints(client, method, args, path):
    client.session.get.return_value = make_response(json_data={})
    getattr(client, method)(*args)
    url, kwargs = client.session.get.call_args
    assert url[0] == f"https://brapi.dev/api{path}"
    assert kwargs["params"] == {"underlying": "PETR4"}


@pytest.mark.parametrize(
    "method,path",
    [
        ("options_historical", "/v2/options/historical"),
        ("options_analytics_history", "/v2/options/analytics/history"),
    ],
)
def test_options_symbol_endpoints(client, method, path):
    client.session.get.return_value = make_response(json_data={})
    getattr(client, method)("PETRA123")
    url, kwargs = client.session.get.call_args
    assert url[0] == f"https://brapi.dev/api{path}"
    assert kwargs["params"] == {"symbol": "PETRA123"}


def test_crypto(client):
    client.session.get.return_value = make_response(json_data={"coins": []})
    client.crypto(["BTC", "ETH"], currency="USD")
    url, kwargs = client.session.get.call_args
    assert url[0] == "https://brapi.dev/api/v2/crypto"
    assert kwargs["params"] == {"coin": "BTC,ETH", "currency": "USD"}


def test_crypto_available(client):
    client.session.get.return_value = make_response(json_data={"coins": []})
    client.crypto_available(search="BT")
    url, kwargs = client.session.get.call_args
    assert url[0] == "https://brapi.dev/api/v2/crypto/available"
    assert kwargs["params"] == {"search": "BT"}


def test_currency(client):
    client.session.get.return_value = make_response(json_data={"currency": []})
    client.currency("USD-BRL")
    url, kwargs = client.session.get.call_args
    assert url[0] == "https://brapi.dev/api/v2/currency"
    assert kwargs["params"] == {"currency": "USD-BRL"}


def test_inflation_historical_range(client):
    client.session.get.return_value = make_response(json_data={"inflation": []})
    client.inflation("brazil", historical=True, start="01/2020", end="01/2024", sort_by="date", sort_order="asc")
    url, kwargs = client.session.get.call_args
    assert url[0] == "https://brapi.dev/api/v2/inflation"
    assert kwargs["params"] == {
        "country": "brazil",
        "historical": True,
        "start": "01/2020",
        "end": "01/2024",
        "sortBy": "date",
        "sortOrder": "asc",
    }


def test_prime_rate_available(client):
    client.session.get.return_value = make_response(json_data={"countries": ["brazil"]})
    client.prime_rate_available()
    url, kwargs = client.session.get.call_args
    assert url[0] == "https://brapi.dev/api/v2/prime-rate/available"


# -- auth --------------------------------------------------------------


def test_token_from_constructor_sets_auth_header(client):
    client.session.get.return_value = make_response(json_data={})
    client.available()
    _, kwargs = client.session.get.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer test-token"


def test_token_from_env_var(monkeypatch):
    monkeypatch.setenv("BRAPI_TOKEN", "env-token")
    c = BrapiClient(backoff_base=0.0)
    c.session = MagicMock(spec=requests.Session)
    c.session.get.return_value = make_response(json_data={})
    c.available()
    _, kwargs = c.session.get.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer env-token"


def test_no_token_omits_auth_header(monkeypatch):
    monkeypatch.delenv("BRAPI_TOKEN", raising=False)
    c = BrapiClient(backoff_base=0.0)
    c.session = MagicMock(spec=requests.Session)
    c.session.get.return_value = make_response(json_data={})
    c.available()
    _, kwargs = c.session.get.call_args
    assert "Authorization" not in kwargs["headers"]


# -- retry / error mapping ----------------------------------------------


def test_429_retries_then_succeeds(client):
    client.session.get.side_effect = [
        make_response(status_code=429, headers={}),
        make_response(status_code=200, json_data={"ok": True}),
    ]
    result = client.available()
    assert result == {"ok": True}
    assert client.session.get.call_count == 2


def test_429_exhausts_retries_raises_rate_limit_error(client):
    client.session.get.return_value = make_response(status_code=429, text="rate limited")
    with pytest.raises(BrapiRateLimitError):
        client.available()
    assert client.session.get.call_count == client.max_retries


def test_401_raises_auth_error_without_retrying(client):
    client.session.get.return_value = make_response(status_code=401, text="no token")
    with pytest.raises(BrapiAuthError):
        client.available()
    assert client.session.get.call_count == 1


def test_404_raises_not_found_without_retrying(client):
    client.session.get.return_value = make_response(status_code=404, text="unknown ticker")
    with pytest.raises(BrapiNotFoundError):
        client.quote("NOTAREALTICKER99")
    assert client.session.get.call_count == 1


def test_500_retries_then_raises_http_error(client):
    client.session.get.return_value = make_response(status_code=503, text="upstream down")
    with pytest.raises(BrapiHTTPError):
        client.available()
    assert client.session.get.call_count == client.max_retries


def test_network_error_retries_then_raises_brapi_error(client):
    client.session.get.side_effect = requests.ConnectionError("boom")
    with pytest.raises(BrapiError):
        client.available()
    assert client.session.get.call_count == client.max_retries


def test_none_params_are_not_sent(client):
    client.session.get.return_value = make_response(json_data={})
    client.quote("PETR4", range=None, interval=None)
    _, kwargs = client.session.get.call_args
    assert kwargs["params"] == {}
