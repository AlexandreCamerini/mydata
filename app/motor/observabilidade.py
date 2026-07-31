"""As três perguntas que o operador precisa responder sem abrir o banco.

*O que está desatualizado* — frescor por classe, contra o SLA que ela declara.
*O que quebrou* — a linha do tempo da execução, fase a fase, com duração.
*De onde veio este número* — a linhagem completa de um atributo.

Tudo por classe, não por dataset: quem opera pensa em "a Empresa está velha",
não em "o cvm_cadastro não rodou". Qual mapeamento causou o atraso é a
resposta seguinte, não a primeira.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from .. import repositorio as repo
from ..sinks import Sink


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _horas_desde(quando) -> float | None:
    if quando is None:
        return None
    if not hasattr(quando, "tzinfo"):
        return None
    momento = quando if quando.tzinfo else quando.replace(tzinfo=timezone.utc)
    return (_agora() - momento).total_seconds() / 3600


# --------------------------------------------------------------------------
# Linha do tempo da execução
# --------------------------------------------------------------------------
@contextmanager
def fase(sink: Sink, execucao_id: int, nome: str):
    """Cronometra uma fase do ciclo. Falha registra a fase mesmo assim.

    Sem isto dá para saber que uma carga levou meia hora, mas não se foi o
    download, o parse ou a regra de qualidade — e é a diferença entre saber
    o que otimizar e adivinhar.
    """
    fase_id = sink.proximo_id("log_fase")
    inicio = _agora()
    sink.executar(
        "INSERT INTO log_fase (id, execucao_id, fase, iniciado_em) VALUES (?,?,?,?)",
        (fase_id, execucao_id, nome, inicio),
    )
    try:
        yield
    finally:
        fim = _agora()
        sink.executar(
            "UPDATE log_fase SET terminado_em = ?, duracao_ms = ? WHERE id = ?",
            (fim, int((fim - inicio).total_seconds() * 1000), fase_id),
        )


def linha_do_tempo(sink: Sink, execucao_id: int) -> list[dict]:
    return sink.consultar(
        "SELECT fase, iniciado_em, terminado_em, duracao_ms FROM log_fase "
        "WHERE execucao_id = ? ORDER BY id",
        (execucao_id,),
    )


# --------------------------------------------------------------------------
# Frescor
# --------------------------------------------------------------------------
def frescor(sink: Sink) -> list[dict]:
    """Idade do dado de cada classe, contra o SLA que ela declara."""
    saida = []
    for classe in repo.listar_classes(sink, so_ativas=True):
        datasets = repo.datasets_da_classe(sink, classe["chave"])
        chaves = [d["chave"] for d in datasets]
        ultima, ultima_falha = None, None
        if chaves:
            marcadores = ",".join("?" for _ in chaves)
            ultima = sink.um(
                f"SELECT id, dataset_chave, janela, terminado_em, linhas_silver "
                f"FROM log_execucao WHERE dataset_chave IN ({marcadores}) "
                f"AND status = 'publicado' ORDER BY terminado_em DESC, id DESC",
                chaves,
            )
            ultima_falha = sink.um(
                f"SELECT id, dataset_chave, janela, status, erro, terminado_em "
                f"FROM log_execucao WHERE dataset_chave IN ({marcadores}) "
                f"AND status IN ('falha','bloqueada') "
                f"ORDER BY terminado_em DESC, id DESC",
                chaves,
            )
        idade = _horas_desde(ultima["terminado_em"]) if ultima else None
        sla = classe["sla_horas"]
        if idade is None:
            situacao = "sem_carga"
        elif sla and idade > sla:
            situacao = "atrasada"
        else:
            situacao = "em_dia"
        saida.append({
            "classe": classe["chave"],
            "nome": classe["nome"],
            "tabela": classe["tabela"],
            "fontes": chaves,
            "sla_horas": sla,
            "idade_horas": round(idade, 2) if idade is not None else None,
            "situacao": situacao,
            "ultima_publicacao": ultima,
            "ultima_falha": ultima_falha,
        })
    return saida


# --------------------------------------------------------------------------
# Linhagem
# --------------------------------------------------------------------------
def linhagem(sink: Sink, classe_chave: str, atributo: str) -> dict:
    """A cadeia inteira de um atributo: fonte, captura, regra, publicação.

    Responde "de onde veio este número" sem que ninguém precise abrir o
    banco nem confiar na memória de quem configurou.
    """
    from . import ddl

    classe = repo.classe_vigente(sink, classe_chave)
    if classe is None:
        raise repo.ErroConfiguracao(f"classe '{classe_chave}' não existe")
    atributos = {a["nome"]: a for a in repo.atributos_de(sink, classe["id"])}
    if atributo not in atributos:
        raise repo.ErroConfiguracao(
            f"classe '{classe_chave}' não tem o atributo '{atributo}'. "
            f"Atributos: {', '.join(sorted(atributos))}"
        )

    mapa = ddl.datasets_por_atributo(sink, classe)
    candidatos = mapa.get(atributo, [])
    ordem = ddl.precedencia_do_atributo(classe, atributos[atributo], candidatos)

    origens = []
    for chave in ordem:
        ds = repo.dataset_vigente(sink, chave)
        if ds is None:
            continue
        fonte = repo.fonte_vigente(sink, ds["fonte_chave"])
        coluna = next(
            (c for c in repo.colunas_do(sink, ds["id"])
             if c["nome_destino"] == atributo), None
        )
        calculado = next(
            (c for c in repo.calculados_do(sink, ds["id"])
             if c["nome"] == atributo), None
        )
        capturas = sink.consultar(
            "SELECT id, nome_arquivo, url, sha256, capturado_em, tamanho_bytes "
            "FROM bronze_captura WHERE dataset_chave = ? "
            "ORDER BY capturado_em DESC, id DESC LIMIT 5",
            (chave,),
        )
        origens.append({
            "dataset": chave,
            "fonte": {"chave": ds["fonte_chave"],
                      "url_template": fonte["url_template"] if fonte else None},
            "coluna_de_origem": coluna["nome_origem"] if coluna else None,
            "formato": coluna["formato"] if coluna else None,
            "expressao": calculado["expressao"] if calculado else None,
            "colunas_que_usa": (
                calculado["colunas_origem"].split(",") if calculado else []
            ),
            "capturas_recentes": capturas,
            "regras": [
                {"nome": r["nome"], "severidade": r["severidade"],
                 "descricao": r["descricao"]}
                for r in repo.regras_do(sink, ds["id"])
            ],
        })

    vistas = [
        v["chave"] for v in repo.listar_vistas(sink)
        if v["classe_chave"] == classe_chave
    ]
    if classe.get("resolucao") == "precedencia":
        vistas.append(f"gold_{classe_chave}")

    return {
        "classe": classe_chave,
        "atributo": atributo,
        "tipo": atributos[atributo]["tipo"],
        "descricao": atributos[atributo]["descricao"],
        # Duas fontes alimentando o atributo só são disputa quando a classe
        # resolve por precedência. Em `demonstracao_financeira`, DFP e ITR
        # alimentam os mesmos atributos e nunca a mesma linha: o tipo do
        # documento faz parte da identidade.
        "disputado": (len(candidatos) > 1
                      and classe.get("resolucao") == "precedencia"),
        "precedencia": ordem,
        "origens": origens,
        "vistas": sorted(set(vistas)),
        "publicacao_atual": sink.um("SELECT max(versao) AS v FROM publicacao")["v"],
    }
