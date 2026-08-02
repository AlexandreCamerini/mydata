# scrap

## brapi_client

A Python client covering every public service on [brapi.dev](https://brapi.dev) — the free B3 (Brazilian stock exchange) market data API. See [CLAUDE.md](./CLAUDE.md) for setup, testing, and structure.

```python
from brapi_client import BrapiClient

client = BrapiClient(token="...")  # or set BRAPI_TOKEN in the environment
client.quote("PETR4", fundamental=True, dividends=True)
client.options_chain("PETR4")
client.crypto("BTC", currency="BRL")
client.inflation("brazil", historical=True)
client.prime_rate("brazil")
```

Covers: ações (quote + list + available), opções (expirations/strikes/chain/analytics/historical), criptomoedas, moedas (FX), inflação, and taxa básica de juros (SELIC/prime rate).
