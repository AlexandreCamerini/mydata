"""Download HTTP. Fica isolado para que o motor rode sem rede nos testes."""
from __future__ import annotations

import logging
import time

log = logging.getLogger("portal.download")

UA = "portal-dados/0.1 (+https://github.com/acamerini/cvm-financas)"


def baixar(url: str, tentativas: int = 3, timeout: int = 120) -> bytes:
    """Baixa uma URL com retry exponencial. Levanta em caso de falha final."""
    import requests

    ultimo: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            log.info("baixando %s (tentativa %d)", url, tentativa)
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": UA})
            resp.raise_for_status()
            return resp.content
        except Exception as e:  # noqa: BLE001
            ultimo = e
            if tentativa < tentativas:
                time.sleep(2 ** tentativa)
    raise RuntimeError(f"falha ao baixar {url}: {ultimo}") from ultimo
