"""O que cada carga pesa em disco, e o que isso custa por mês.

A tabela de risco da arquitetura já dizia «bronze cresce além do plano», e não
havia nada que medisse crescimento: dava para saber que uma carga rodou, não o
que ela acrescentou. Este módulo fecha essa lacuna e grava um relatório por
execução — físico e financeiro na mesma linha.

**O que é medido e o que é estimado.** Bytes e linhas são medidos: vêm do
catálogo do próprio banco e da coluna `tamanho_bytes` do bronze. O custo é
derivado — GB medidos vezes tarifa declarada em `cfg_tarifa`. A tarifa é
configuração versionada porque preço muda, e um relatório de seis meses atrás
tem de continuar explicável pela tarifa que valia quando foi gerado.

**O que não é medido, e por que fica de fora.** CPU e memória do Railway não
são observáveis de dentro do container com precisão útil, e inventá-las daria
um número com cara de medida. O custo aqui é o de **armazenamento**, que é o
que cresce com o dado — e é o único que uma carga faz crescer.

O câmbio para real sai da própria base, e não de uma constante: o hub já
ingere a série, então usá-la é coerência — o relatório fica sem nenhuma fonte
de número que o próprio sistema não guarde. *Qual* série é configuração
(`cfg_parametro.indicador_cambio`); o motor não sabe quais indicadores
existem, e fixar a chave aqui seria o acoplamento que `cfg_dataset` existe
para evitar.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..sinks import Sink

log = logging.getLogger("portal.custo")

BYTES_POR_GB = 1024 ** 3


def tamanho_banco(sink: Sink) -> int | None:
    """Bytes ocupados pelo banco inteiro, incluindo índice e sobrecarga.

    Só o Postgres responde isso de forma útil. O DuckDB de teste roda em
    memória e devolveria zero — e zero é pior que nulo, porque parece medida.
    """
    if sink.dialeto != "postgres":
        return None
    linha = sink.um("SELECT pg_database_size(current_database()) AS b")
    return int(linha["b"]) if linha and linha["b"] is not None else None


def tamanho_tabela(sink: Sink, tabela: str) -> int | None:
    """Bytes da tabela com índices e TOAST — o que ela realmente ocupa."""
    if sink.dialeto != "postgres":
        return None
    linha = sink.um(
        "SELECT pg_total_relation_size(c.oid) AS b FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relname = ?",
        (tabela,),
    )
    return int(linha["b"]) if linha and linha["b"] is not None else None


def tarifa_vigente(sink: Sink, recurso: str, quando: str | None = None) -> dict | None:
    """A tarifa que valia na data pedida — não a de hoje.

    Recomputar um relatório antigo com o preço de hoje reescreveria a
    história: o custo daquele mês foi o que foi.
    """
    quando = quando or datetime.now(timezone.utc).date().isoformat()
    return sink.um(
        "SELECT * FROM cfg_tarifa WHERE recurso = ? AND vigente_desde <= ? "
        "ORDER BY vigente_desde DESC LIMIT 1",
        (recurso, quando),
    )


def parametro(sink: Sink, chave: str) -> str | None:
    linha = sink.um("SELECT valor FROM cfg_parametro WHERE chave = ?", (chave,))
    return linha["valor"] if linha else None


def cambio_do_dia(sink: Sink, quando: str | None = None) -> float | None:
    """USD/BRL da própria base, pela série que a configuração indicar.

    Nulo em dois casos, e os dois são o mesmo fato: ou nenhuma série de
    câmbio foi declarada, ou a declarada ainda não tem carga. Zero seria
    pior — R$ 0,00 pareceria de graça.
    """
    indicador = parametro(sink, "indicador_cambio")
    if not indicador:
        return None
    quando = quando or datetime.now(timezone.utc).date().isoformat()
    linha = sink.um(
        "SELECT valor FROM fato_indicador WHERE indicador = ? "
        "AND dt_referencia <= ? ORDER BY dt_referencia DESC LIMIT 1",
        (indicador, quando),
    )
    return float(linha["valor"]) if linha and linha["valor"] is not None else None


def _anterior(sink: Sink, dataset_chave: str) -> dict | None:
    return sink.um(
        "SELECT bytes_banco, gerado_em FROM relatorio_carga "
        "WHERE dataset_chave = ? AND bytes_banco IS NOT NULL "
        "ORDER BY gerado_em DESC LIMIT 1",
        (dataset_chave,),
    )


def _crescimento_por_dia(anterior: dict | None, bytes_agora: int | None,
                         agora: datetime) -> float | None:
    """GB por dia entre este relatório e o anterior do mesmo dataset.

    Duas cargas no mesmo instante dariam divisão por zero; menos de um minuto
    de intervalo não é amostra de crescimento diário, é ruído.
    """
    if anterior is None or bytes_agora is None or anterior["bytes_banco"] is None:
        return None
    antes = anterior["gerado_em"]
    if antes.tzinfo is None:
        antes = antes.replace(tzinfo=timezone.utc)
    dias = (agora - antes).total_seconds() / 86400
    if dias < 1 / 1440:
        return None
    delta_gb = (int(bytes_agora) - int(anterior["bytes_banco"])) / BYTES_POR_GB
    return delta_gb / dias


def gerar(sink: Sink, ds: dict, resultado, duracao_ms: int | None = None) -> dict:
    """Mede a execução, precifica e grava a linha do relatório.

    Nunca levanta: um relatório que derruba a carga que ele deveria descrever
    inverte a prioridade. Falha aqui vira aviso no log, e a carga segue.
    """
    agora = datetime.now(timezone.utc)
    tabela = ds["tabela_destino"]

    bytes_banco = tamanho_banco(sink)
    bytes_classe = tamanho_tabela(sink, tabela)
    linhas_classe = int(sink.um(f"SELECT count(*) AS n FROM {tabela}")["n"])
    bronze_total = sink.um(
        "SELECT COALESCE(sum(tamanho_bytes), 0) AS b FROM bronze_captura"
    )
    bronze_execucao = sink.um(
        "SELECT COALESCE(sum(tamanho_bytes), 0) AS b FROM bronze_captura "
        "WHERE dataset_chave = ? AND janela = ?",
        (ds["chave"], resultado.janela),
    )

    anterior = _anterior(sink, ds["chave"])
    crescimento = _crescimento_por_dia(anterior, bytes_banco, agora)
    delta_banco = (
        int(bytes_banco) - int(anterior["bytes_banco"])
        if anterior and bytes_banco is not None and anterior["bytes_banco"] is not None
        else None
    )

    tarifa = tarifa_vigente(sink, "armazenamento")
    cambio = cambio_do_dia(sink)
    gb = bytes_banco / BYTES_POR_GB if bytes_banco is not None else None
    preco = float(tarifa["preco_usd"]) if tarifa else None

    custo_usd = gb * preco if gb is not None and preco is not None else None
    custo_brl = custo_usd * cambio if custo_usd is not None and cambio else None
    projecao_gb = (
        gb + crescimento * 365
        if gb is not None and crescimento is not None else None
    )
    projecao_usd = (
        projecao_gb * preco
        if projecao_gb is not None and preco is not None else None
    )

    relatorio = {
        "execucao_id": resultado.execucao_id,
        "dataset_chave": ds["chave"],
        "classe_chave": ds.get("classe_chave"),
        "janela": resultado.janela,
        "status": resultado.status,
        "linhas_carregadas": resultado.linhas_silver,
        "delta_linhas": resultado.delta_linhas,
        "capturas_novas": resultado.capturas_novas,
        "bytes_capturados": int(bronze_execucao["b"] or 0),
        "linhas_classe": linhas_classe,
        "bytes_classe": bytes_classe,
        "bytes_bronze": int(bronze_total["b"] or 0),
        "bytes_banco": bytes_banco,
        "delta_bytes_banco": delta_banco,
        "duracao_ms": duracao_ms,
        "gb_armazenados": gb,
        "custo_mes_usd": custo_usd,
        "custo_mes_brl": custo_brl,
        "cambio_usd_brl": cambio,
        "crescimento_gb_dia": crescimento,
        "projecao_12m_gb": projecao_gb,
        "projecao_12m_usd": projecao_usd,
        "tarifa_id": tarifa["id"] if tarifa else None,
    }

    campos = list(relatorio)
    sink.executar(
        f"INSERT INTO relatorio_carga (id, {', '.join(campos)}) "
        f"VALUES ({', '.join('?' for _ in range(len(campos) + 1))})",
        [sink.proximo_id("relatorio_carga"), *[relatorio[c] for c in campos]],
    )
    return relatorio


def resumo(relatorio: dict) -> str:
    """Uma linha para o log do cron — é onde o operador vê primeiro.

    Cabe numa linha de propósito: relatório que ocupa vinte linhas no log some
    no meio da saída da carga, que é justamente quando ele importa.
    """
    def mb(valor):
        return "?" if valor is None else f"{valor / 1e6:.1f}MB"

    partes = [
        f"carga {relatorio['dataset_chave']}/{relatorio['janela']}",
        f"status={relatorio['status']}",
        f"linhas={relatorio['linhas_carregadas']}",
        f"delta={relatorio['delta_linhas']}",
        f"bronze+={mb(relatorio['bytes_capturados'])}",
        f"banco={mb(relatorio['bytes_banco'])}",
    ]
    if relatorio["delta_bytes_banco"] is not None:
        partes.append(f"banco+={mb(relatorio['delta_bytes_banco'])}")
    if relatorio["custo_mes_usd"] is not None:
        custo = f"custo/mês=US$ {relatorio['custo_mes_usd']:.2f}"
        if relatorio["custo_mes_brl"] is not None:
            custo += f" (R$ {relatorio['custo_mes_brl']:.2f})"
        partes.append(custo)
    if relatorio["projecao_12m_usd"] is not None:
        partes.append(
            f"projeção 12m={relatorio['projecao_12m_gb']:.1f}GB / "
            f"US$ {relatorio['projecao_12m_usd']:.2f}"
        )
    return " | ".join(partes)
