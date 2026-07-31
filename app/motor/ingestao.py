"""Motor de ingestão dirigido por configuração.

Ciclo: baixar → gravar bronze → parsear → carregar silver → recomputar
calculados → avaliar qualidade → publicar gold.

Nada aqui sabe o que é a CVM. Tudo o que é específico dela mora em linhas de
`cfg_fonte` / `cfg_dataset` / `cfg_coluna` / `cfg_campo_calculado`.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .. import repositorio as repo
from ..sinks import Sink
from . import calculados as calc
from . import parsing
from . import publicacao as pub
from . import qualidade as qa

log = logging.getLogger("portal.motor")


class ErroIngestao(RuntimeError):
    pass


@dataclass
class Resultado:
    execucao_id: int
    dataset_chave: str
    janela: str
    status: str
    capturas: int = 0
    capturas_novas: int = 0
    linhas_silver: int = 0
    delta_linhas: int | None = None
    publicacao: int | None = None
    violacoes: list[dict] = field(default_factory=list)
    erro: str | None = None


def _agora() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Bronze
# --------------------------------------------------------------------------
def gravar_bronze(
    sink: Sink, dataset_chave: str, janela: str, url: str, nome: str, payload: bytes
) -> tuple[int, bool]:
    """Grava a captura. Conteúdo idêntico já capturado é no-op.

    Devolve (captura_id, é_nova). A unicidade (dataset, sha256) é o que faz
    o cron rebaixar o mesmo ano sem inflar a tabela.
    """
    sha = hashlib.sha256(payload).hexdigest()
    ja = sink.um(
        "SELECT id FROM bronze_captura WHERE dataset_chave = ? AND sha256 = ?",
        (dataset_chave, sha),
    )
    if ja:
        return int(ja["id"]), False

    novo_id = sink.proximo_id("bronze_captura")
    sink.executar(
        """INSERT INTO bronze_captura
           (id, dataset_chave, janela, url, nome_arquivo, sha256,
            tamanho_bytes, payload) VALUES (?,?,?,?,?,?,?,?)""",
        (novo_id, dataset_chave, janela, url, nome, sha, len(payload), payload),
    )
    return novo_id, True


def capturas_da_janela(sink: Sink, dataset_chave: str, janela: str) -> list[dict]:
    """Última captura por nome de arquivo dentro da janela."""
    linhas = sink.consultar(
        """SELECT id, nome_arquivo, url, sha256, capturado_em
           FROM bronze_captura WHERE dataset_chave = ? AND janela = ?
           ORDER BY nome_arquivo, capturado_em DESC, id DESC""",
        (dataset_chave, janela),
    )
    vistos: dict[str, dict] = {}
    for linha in linhas:
        vistos.setdefault(linha["nome_arquivo"], linha)
    return list(vistos.values())


def payload_de(sink: Sink, captura_id: int) -> bytes:
    linha = sink.um("SELECT payload FROM bronze_captura WHERE id = ?", (captura_id,))
    if linha is None:
        raise ErroIngestao(f"captura {captura_id} não existe")
    dado = linha["payload"]
    return bytes(dado) if not isinstance(dado, bytes) else dado


# --------------------------------------------------------------------------
# Silver
# --------------------------------------------------------------------------
def _colunas_da_tabela(sink: Sink, tabela: str) -> set[str]:
    linhas = sink.consultar(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
        (tabela,),
    )
    return {linha["column_name"] for linha in linhas}


def carregar_arquivo(
    sink: Sink, ds: dict, colunas: list[dict], fonte: dict, captura_id: int,
    nome_arquivo: str, payload: bytes, contexto: dict[str, str],
) -> int:
    """Parseia e carrega um arquivo em silver, com upsert pela chave natural.

    A deduplicação dentro do arquivo — a CVM repete a mesma chave natural em
    alguns CSVs — é resolvida no SQL da staging, pela ordem de leitura. Antes
    era um `set` em Python que segurava a chave de cada linha do arquivo: para
    um CSV de meio milhão de linhas, isso era memória que o container não tem.
    """
    fisicas = _colunas_da_tabela(sink, ds["tabela_destino"])
    chave_natural = [c.strip() for c in ds["chave_natural"].split(",") if c.strip()]
    # O upsert tem de resolver conflito pelo mesmo critério do índice único.
    # `origem_dataset` faz parte dele: duas fontes na mesma classe coexistem
    # em vez de a segunda carga sobrescrever a primeira.
    if "origem_dataset" in fisicas:
        chave_natural = [*chave_natural, "origem_dataset"]

    linhas = parsing.ler_csv(
        payload, colunas, fonte["encoding"], fonte["separador"],
        contexto=contexto,
        extras={"captura_id": captura_id, "fonte_arquivo": nome_arquivo,
                "origem_dataset": ds["chave"]},
    )

    primeira = next(iter(linhas), None)
    if primeira is None:
        return 0
    campos = [c for c in primeira if c in fisicas]
    ausentes = [c for c in chave_natural if c not in campos]
    if ausentes:
        raise ErroIngestao(
            f"chave natural do dataset '{ds['chave']}' cita coluna que o "
            f"arquivo não produz: {', '.join(ausentes)}"
        )

    def valores():
        yield [primeira.get(c) for c in campos]
        for linha in linhas:
            yield [linha.get(c) for c in campos]

    return sink.carregar_em_lote(
        ds["tabela_destino"], campos, chave_natural, valores()
    )


# --------------------------------------------------------------------------
# Execução
# --------------------------------------------------------------------------
def _urls_da_janela(fonte: dict, ds: dict, janela: str) -> list[str]:
    """Expande o template da fonte para a janela pedida."""
    import json as _json

    template = fonte["url_template"]
    contexto = {"ano": janela, "janela": janela, "dataset": ds["chave"]}
    # Parâmetro declarado no dataset. O sufixo do nome fica como último
    # recurso: era a regra antiga, e adivinhava errado assim que dois
    # datasets passaram a ler o mesmo arquivo com nomes diferentes.
    declarados = _json.loads(ds.get("parametros") or "{}")
    tipo = declarados.get("tipo", ds["chave"].split("_")[-1])
    contexto["tipo"] = tipo
    contexto["TIPO"] = tipo.upper()
    contexto.update(declarados)
    try:
        return [template.format(**contexto)]
    except KeyError as e:
        raise ErroIngestao(
            f"url_template usa placeholder desconhecido: {e}. "
            f"Disponíveis: {', '.join(sorted(contexto))}"
        ) from e


def executar(
    sink: Sink, dataset_chave: str, janela: str, *, trigger: str = "manual",
    baixar=None, apenas_bronze: bool = False, publicar: bool = True,
) -> Resultado:
    """Roda o ciclo completo para um dataset numa janela."""
    ds = repo.dataset_vigente(sink, dataset_chave)
    if ds is None:
        raise ErroIngestao(f"dataset '{dataset_chave}' não está configurado")
    fonte = repo.fonte_vigente(sink, ds["fonte_chave"])
    if fonte is None:
        raise ErroIngestao(f"fonte '{ds['fonte_chave']}' não está configurada")

    colunas = repo.colunas_do(sink, ds["id"])
    exec_id = repo.abrir_execucao(sink, dataset_chave, ds["id"], janela, trigger)
    res = Resultado(exec_id, dataset_chave, janela, "pendente")
    antes = _contar(sink, ds["tabela_destino"])

    try:
        # ---------- baixar + bronze ----------
        repo.atualizar_execucao(sink, exec_id, status="baixando")
        if baixar is not None:
            for url in _urls_da_janela(fonte, ds, janela):
                nome = url.rsplit("/", 1)[-1]
                payload = baixar(url)
                _, nova = gravar_bronze(
                    sink, dataset_chave, janela, url, nome, payload
                )
                res.capturas_novas += int(nova)
        repo.atualizar_execucao(sink, exec_id, status="capturado")

        capturas = capturas_da_janela(sink, dataset_chave, janela)
        res.capturas = len(capturas)
        if not capturas:
            raise ErroIngestao(
                f"nenhuma captura em bronze para {dataset_chave}/{janela}. "
                f"Rode com download habilitado para capturar."
            )
        if apenas_bronze:
            res.status = "capturado"
            repo.atualizar_execucao(
                sink, exec_id, status="capturado", capturas=res.capturas,
                terminado_em=_agora(),
            )
            return res

        # ---------- silver ----------
        repo.atualizar_execucao(sink, exec_id, status="carregando")
        for captura in capturas:
            payload = payload_de(sink, captura["id"])
            if fonte["tipo_transporte"] == "http_zip":
                membros = parsing.membros_do_zip(payload, ds["padrao_arquivo"])
            else:
                import re as _re

                base = captura["nome_arquivo"]
                m = _re.match(ds["padrao_arquivo"], base, _re.IGNORECASE)
                membros = [(base, payload, m.groupdict() if m else {})] if m else []
            for nome, raw, contexto in membros:
                res.linhas_silver += carregar_arquivo(
                    sink, ds, colunas, fonte, captura["id"], nome, raw, contexto
                )

        # ---------- calculados ----------
        repo.atualizar_execucao(sink, exec_id, status="recomputando")
        calc.aplicar(sink, ds, repo.calculados_do(sink, ds["id"]))

        # ---------- qualidade ----------
        repo.atualizar_execucao(sink, exec_id, status="validando")
        res.violacoes = qa.avaliar(sink, repo.regras_do(sink, ds["id"]))
        bloqueia = [v for v in res.violacoes if v["severidade"] == "bloqueia"]

        depois = _contar(sink, ds["tabela_destino"])
        res.delta_linhas = depois - antes

        if bloqueia:
            # O gate só vale se o dado reprovado sumir de vista: as linhas
            # desta execução ainda não têm rótulo de publicação, então saem
            # de silver sem tocar em nada que já estava publicado.
            descartadas = pub.descartar_nao_publicado(
                sink, [c["id"] for c in capturas]
            )
            res.status = "bloqueada"
            res.delta_linhas = _contar(sink, ds["tabela_destino"]) - antes
            repo.atualizar_execucao(
                sink, exec_id, status="bloqueada", capturas=res.capturas,
                linhas_silver=res.linhas_silver, delta_linhas=res.delta_linhas,
                terminado_em=_agora(),
                erro="; ".join(f"{v['nome']}: {v['linhas']} linhas" for v in bloqueia)
                     + f" | {descartadas} linhas descartadas de silver",
            )
            return res

        # ---------- publicação ----------
        if publicar:
            res.publicacao = pub.publicar(sink, exec_id)
        res.status = "publicado"
        repo.atualizar_execucao(
            sink, exec_id, status="publicado", capturas=res.capturas,
            linhas_silver=res.linhas_silver, delta_linhas=res.delta_linhas,
            publicacao=res.publicacao, terminado_em=_agora(),
        )
        return res

    except Exception as e:  # noqa: BLE001 — o erro vira estado no log
        res.status = "falha"
        res.erro = f"{type(e).__name__}: {e}"
        repo.atualizar_execucao(
            sink, exec_id, status="falha", erro=res.erro[:2000],
            capturas=res.capturas, linhas_silver=res.linhas_silver,
            terminado_em=_agora(),
        )
        raise


def recomputar(
    sink: Sink, dataset_chave: str, janela: str, *, publicar: bool = True
) -> Resultado:
    """Reconstrói silver, calculados e gold a partir do bronze já capturado.

    Sem rede. É a rotina padrão de correção — não um último recurso.
    """
    ds = repo.dataset_vigente(sink, dataset_chave)
    if ds is None:
        raise ErroIngestao(f"dataset '{dataset_chave}' não está configurado")
    capturas = [c["id"] for c in capturas_da_janela(sink, dataset_chave, janela)]
    if capturas:
        marcadores = ",".join("?" for _ in capturas)
        sink.executar(
            f"DELETE FROM {ds['tabela_destino']} WHERE captura_id IN ({marcadores})",
            capturas,
        )
    return executar(
        sink, dataset_chave, janela, trigger="replay", baixar=None, publicar=publicar
    )


def janelas_capturadas(sink: Sink, dataset_chave: str) -> list[str]:
    return [
        linha["janela"]
        for linha in sink.consultar(
            "SELECT DISTINCT janela FROM bronze_captura "
            "WHERE dataset_chave = ? ORDER BY janela",
            (dataset_chave,),
        )
    ]


def recomputar_tudo(sink: Sink) -> list[Resultado]:
    """Reconstrói todo o derivado a partir do bronze existente. Sem rede.

    É a rede de segurança das mudanças de modelo: se o bronze é suficiente
    para reconstruir tudo, qualquer etapa é reversível. Publica ao final de
    cada janela em vez de uma vez só no fim — assim uma falha no meio deixa
    o que já foi refeito visível, em vez de gold vazia.
    """
    resultados: list[Resultado] = []
    for ds in repo.listar_datasets(sink):
        for janela in janelas_capturadas(sink, ds["chave"]):
            resultados.append(recomputar(sink, ds["chave"], janela))
    return resultados


def _contar(sink: Sink, tabela: str) -> int:
    linha = sink.um(f"SELECT count(*) AS n FROM {tabela}")
    return int(linha["n"]) if linha else 0
