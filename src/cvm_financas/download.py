"""Download dos ZIPs da CVM."""
from __future__ import annotations

import io
import logging
import zipfile

import requests

from .config import URL_TEMPLATE

log = logging.getLogger("cvm_financas")


def baixar_zip(tipo: str, ano: int, timeout: int = 120) -> zipfile.ZipFile:
    """Baixa o ZIP de um (tipo, ano) e devolve um ZipFile em memória.

    Requer rede com acesso a dados.cvm.gov.br. Levanta requests.HTTPError
    para respostas != 2xx (ex.: ano sem publicação).
    """
    url = URL_TEMPLATE[tipo].format(ano=ano)
    log.info("download %s", url)
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "cvm-financas/0.1"})
    resp.raise_for_status()
    return zipfile.ZipFile(io.BytesIO(resp.content))
