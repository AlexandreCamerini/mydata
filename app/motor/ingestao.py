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
from . import credenciais
from . import observabilidade as obs
from . import paginacao
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


def _relatar(sink: Sink, ds: dict, res: "Resultado", exec_id: int) -> None:
    """Mede e grava o relatório de carga. Nunca derruba a execução.

    Um relatório que quebra a carga que ele deveria descrever inverte a
    prioridade: o dado é o produto, a medição é sobre ele. Falha aqui vira
    aviso no log e a carga segue publicada.
    """
    from . import custo

    try:
        gasto = sink.um(
            "SELECT COALESCE(sum(duracao_ms), 0) AS ms FROM log_fase "
            "WHERE execucao_id = ?",
            (exec_id,),
        )
        relatorio = custo.gerar(sink, ds, res, int(gasto["ms"] or 0))
        # O eco no log é o que o operador vê sem abrir nada — é o cron do
        # Railway imprimindo o que a noite custou.
        log.info("%s", custo.resumo(relatorio))
    except Exception as e:  # noqa: BLE001 — medir não pode custar o dado
        log.warning("relatório de carga falhou (a carga não): %s", e)


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


def capturas_por_id(sink: Sink, ids: list[int]) -> list[dict]:
    """As capturas pedidas, na ordem em que a rodada as obteve, sem repetir."""
    unicos = list(dict.fromkeys(ids))
    marcas = ",".join("?" for _ in unicos)
    linhas = {
        int(r["id"]): r for r in sink.consultar(
            f"SELECT id, nome_arquivo, url, sha256, capturado_em "
            f"FROM bronze_captura WHERE id IN ({marcas})", tuple(unicos),
        )
    }
    return [linhas[i] for i in unicos if i in linhas]


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

    extras = {"captura_id": captura_id, "fonte_arquivo": nome_arquivo,
              "origem_dataset": ds["chave"]}
    if fonte["tipo_transporte"] == "http_json":
        linhas = parsing.ler_json(
            payload, colunas,
            caminho_registros=_parametros(ds).get("caminho_registros"),
            contexto=contexto, extras=extras,
            herdar=_parametros(ds).get("herdar"),
        )
    elif fonte.get("formato_registro") == "larguras":
        linhas = parsing.ler_larguras(
            payload, colunas, fonte["encoding"],
            filtro_linha=ds.get("filtro_linha"),
            contexto=contexto, extras=extras,
        )
    else:
        linhas = parsing.ler_csv(
            payload, colunas, fonte["encoding"], fonte["separador"],
            contexto=contexto, extras=extras,
            preambulo=int(_parametros(ds).get("preambulo", 0)),
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
        for linha in (primeira, *linhas):
            # Chave natural com NULL não conflita: o índice único trata cada
            # NULL como distinto, o upsert vira insert e a recarga duplica a
            # linha sem erro e sem sintoma — descoberto num campo que a B3
            # deixa em branco quando não se aplica. Falhar aqui é caro de
            # ler e barato de rodar; o silêncio custava a tabela.
            nulas = [c for c in chave_natural if linha.get(c) is None]
            if nulas:
                raise ErroIngestao(
                    f"chave natural do dataset '{ds['chave']}' veio nula em "
                    f"{', '.join(nulas)}. Chave nula não deduplica: declare um "
                    f"literal com formato 'vazio:<valor>' ou tire a coluna da "
                    f"chave."
                )
            yield [linha.get(c) for c in campos]

    # `politica_versao` declara o que a carga é. `max_versao`, o padrão, vale
    # para fonte que publica evento: cada linha nova é um fato novo e a última
    # carga manda. `nao_retroceder:<coluna>` vale para fonte que publica
    # fotografia — um cadastro diário cuja identidade é a coisa cadastrada,
    # sem a data. Sem a distinção, reingerir um dia antigo devolveria o
    # cadastro ao estado dele, em silêncio.
    politica = (ds.get("politica_versao") or "max_versao").strip()
    nao_retroceder = (
        politica.split(":", 1)[1].strip()
        if politica.startswith("nao_retroceder:") else None
    )
    return sink.carregar_em_lote(
        ds["tabela_destino"], campos, chave_natural, valores(),
        nao_retroceder=nao_retroceder,
    )


# --------------------------------------------------------------------------
# Execução
# --------------------------------------------------------------------------
def _parametros(ds: dict) -> dict:
    import json as _json

    return _json.loads(ds.get("parametros") or "{}")


def _trocar_bilhete(url: str, params: dict, baixar) -> tuple[str, str]:
    """Pede o bilhete e devolve `(endereço do arquivo, nome do arquivo)`.

    O mapeamento declara `campo_token` (onde o bilhete está no JSON) e
    `url_arquivo` (o segundo endereço, com `{token}`). `nome_arquivo` nomeia a
    captura: o segundo endereço não traz nome nenhum, e sem isto toda captura
    se chamaria `download`.
    """
    import json as _json

    campo = params.get("campo_token", "token")
    modelo = params.get("url_arquivo")
    if not modelo:
        raise ErroIngestao(
            "transporte 'http_token' exige o parâmetro 'url_arquivo' no "
            "mapeamento, com o lugar do bilhete marcado como {token}."
        )
    bruto = baixar(url)
    try:
        corpo = _json.loads(bruto.decode("utf-8", errors="replace"))
    except ValueError as e:
        raise ErroIngestao(
            f"o primeiro passo de '{url}' não devolveu JSON. "
            f"Primeiros bytes: {bruto[:80]!r}"
        ) from e
    bilhete = corpo.get(campo) if isinstance(corpo, dict) else None
    if not bilhete:
        raise ErroIngestao(
            f"o JSON do primeiro passo não traz '{campo}'. "
            f"Campos vistos: {', '.join(sorted(corpo))}"
            if isinstance(corpo, dict) else
            f"o primeiro passo devolveu {type(corpo).__name__}, não um objeto."
        )
    nome = params.get("nome_arquivo", "arquivo.csv")
    return modelo.format(token=bilhete), nome


def _urls_da_janela(fonte: dict, ds: dict, janela: str) -> list[str]:
    """Expande o template da fonte para a janela pedida."""
    import json as _json

    template = fonte["url_template"]
    contexto = {"ano": janela, "janela": janela, "dataset": ds["chave"]}
    # Janela diária: a partição é um pregão, não um ano, e o endereço da
    # fonte costuma nomear o arquivo pelos pedaços da data. Decompor aqui
    # mantém a janela em ISO — ordenável, comparável e igual à do resto do
    # sistema — em vez de obrigar o dataset a guardá-la no formato do
    # arquivo só para conseguir montar a URL.
    if len(janela) == 10 and janela[4] == "-" and janela[7] == "-":
        contexto["ano"], contexto["mes"], contexto["dia"] = janela.split("-")
    # Parâmetro declarado no dataset. O sufixo do nome fica como último
    # recurso: era a regra antiga, e adivinhava errado assim que dois
    # datasets passaram a ler o mesmo arquivo com nomes diferentes.
    declarados = _json.loads(ds.get("parametros") or "{}")
    tipo = declarados.get("tipo", ds["chave"].split("_")[-1])
    contexto["tipo"] = tipo
    contexto["TIPO"] = tipo.upper()
    contexto.update(declarados)
    # `{parametros}` pertence ao transporte JSON, que o resolve depois com o
    # modelo codificado. Devolvê-lo intacto é o que permite a mesma expansão
    # de janela valer para arquivo e para API.
    contexto.setdefault("parametros", "{parametros}")
    try:
        return [template.format(**contexto)]
    except KeyError as e:
        raise ErroIngestao(
            f"url_template usa placeholder desconhecido: {e}. "
            f"Disponíveis: {', '.join(sorted(contexto))}"
        ) from e


def _com_credencial(fonte: dict, baixar):
    """Envolve o baixador com a credencial que a fonte declara.

    Fica aqui, e não em `download.py`, porque é aqui que a fonte é conhecida —
    o downloader continua sendo uma função genérica que recebe URL e
    cabeçalhos e não sabe de onde vieram.
    """
    cred = credenciais.declarada(fonte.get("credencial_ref"))
    if cred is None:
        return baixar

    def _baixar(url: str) -> bytes:
        endereco, cabecalhos = credenciais.aplicar(fonte["credencial_ref"], url)
        return baixar(endereco, cabecalhos=cabecalhos)

    return _baixar


def previa_arquivo(
    sink: Sink, fonte_chave: str, ds_rascunho: dict, janela: str,
    *, baixar, limite: int = 5,
) -> dict:
    """Baixa a fonte agora e devolve colunas + amostra crua — sem gravar
    nada em bronze nem em silver. É o passo "Arquivo" do assistente de
    conexão nova: ver o arquivo real antes de ligar um campo, em vez de
    digitar contra um CSV aberto em outra janela.

    `ds_rascunho` é o dataset ainda não salvo — só `chave`, `padrao_arquivo`
    e `parametros` importam aqui, os mesmos três campos que `_urls_da_janela`
    já usa para montar o endereço de uma carga de verdade.

    Só cobre `http_csv` e `http_zip`. `http_json` não tem "primeira linha"
    fora da própria captura paginada, e `http_token` precisa de um passo a
    mais que a prévia não modela — para essas duas, a tela pula a etapa e o
    mapeamento continua digitado, como é hoje.
    """
    fonte = repo.fonte_vigente(sink, fonte_chave)
    if fonte is None:
        raise ErroIngestao(f"fonte '{fonte_chave}' não está configurada")
    if fonte["tipo_transporte"] not in ("http_csv", "http_zip"):
        raise ErroIngestao(
            f"prévia não cobre o transporte '{fonte['tipo_transporte']}' — "
            f"pule esta etapa."
        )

    baixador = _com_credencial(fonte, baixar)
    url = _urls_da_janela(fonte, ds_rascunho, janela)[0]
    payload = baixador(url)

    if fonte["tipo_transporte"] == "http_zip":
        padrao = ds_rascunho.get("padrao_arquivo") or ""
        if not padrao:
            raise ErroIngestao(
                "informe o padrão de arquivo para escolher o membro do zip."
            )
        membro = next(iter(parsing.membros_do_zip(payload, padrao)), None)
        if membro is None:
            raise ErroIngestao(f"nenhum arquivo no zip casa com '{padrao}'.")
        nome_arquivo, payload_arquivo, _ = membro
    else:
        nome_arquivo, payload_arquivo = url.rsplit("/", 1)[-1].split("?")[0], payload

    preambulo = int(_parametros(ds_rascunho).get("preambulo", 0))
    lido = parsing.previa_csv(
        payload_arquivo, fonte["encoding"], fonte["separador"],
        preambulo=preambulo, limite=limite,
    )
    return {"nome_arquivo": nome_arquivo, **lido}


def executar(
    sink: Sink, dataset_chave: str, janela: str, *, trigger: str = "manual",
    baixar=None, apenas_bronze: bool = False, publicar: bool = True,
) -> Resultado:
    """Roda o ciclo completo para um dataset numa janela.

    Uma carga por dataset+janela de cada vez: se outra já está com a janela,
    devolve `ja_em_execucao` sem abrir execução nem tocar em bronze ou silver.
    Não é falha — quem chama decide o que fazer (o cron registra como pulado).
    """
    with repo.trava_execucao(sink, dataset_chave, janela) as obtida:
        if not obtida:
            log.info("%s/%s já está em execução; nada a fazer",
                     dataset_chave, janela)
            return Resultado(0, dataset_chave, janela, "ja_em_execucao")
        return _executar(
            sink, dataset_chave, janela, trigger=trigger, baixar=baixar,
            apenas_bronze=apenas_bronze, publicar=publicar,
        )


def janela_recuperavel(sink: Sink, dataset_chave: str) -> bool:
    """A janela diária pode ser recuperada depois, dia a dia?

    Só quando pedir outro dia devolve outro arquivo e reingerir um dia velho
    é seguro. Duas coisas dizem que não, e as duas vêm da configuração: o
    endereço não muda com a janela (API por companhia, arquivo único), ou a
    carga é fotografia (`nao_retroceder`) — recuperar o cadastro de anteontem
    baixaria megabytes para não mudar nada.
    """
    ds = repo.dataset_vigente(sink, dataset_chave)
    if ds is None or str(ds.get("politica_versao") or "").startswith("nao_retroceder"):
        return False
    fonte = repo.fonte_vigente(sink, ds["fonte_chave"])
    if fonte is None:
        return False
    try:
        return (_urls_da_janela(fonte, ds, "2001-01-01")
                != _urls_da_janela(fonte, ds, "2001-01-02"))
    except ErroIngestao:
        return False


def _executar(
    sink: Sink, dataset_chave: str, janela: str, *, trigger: str = "manual",
    baixar=None, apenas_bronze: bool = False, publicar: bool = True,
) -> Resultado:
    """O ciclo em si; quem chama já detém a trava da janela."""
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
        # Capturas que ESTA rodada obteve (ou reconheceu como já guardadas).
        # O bronze deduplica por hash em todo o dataset, então baixar de novo
        # um conteúdo bom que já existe não cria linha nova: a "última captura
        # da janela" continuaria sendo um lixo gravado depois dele, e o silver
        # leria o lixo mesmo com a fonte respondendo certo.
        desta_rodada: list[int] = []
        with obs.fase(sink, exec_id, "baixar"):
            if baixar is not None:
                # A credencial da fonte entra aqui, uma vez, e o resto do
                # caminho não sabe que ela existe: quem transporta continua
                # ignorando de quem é o dado. O que vai para o bronze e para o
                # log é a URL censurada — no modo `query` o segredo está no
                # próprio endereço.
                baixar = _com_credencial(fonte, baixar)
                if fonte["tipo_transporte"] == "http_json":
                    # Uma API paginada não entrega tudo numa requisição; o
                    # bronze guarda todas as páginas, cruas e na ordem.
                    #
                    # A janela expande aqui como expande para arquivo: uma API
                    # de série histórica recorta por ano no próprio endereço, e
                    # sem isso toda janela capturaria a mesma resposta.
                    #
                    # `iteracao` é a fonte que responde por valor — uma
                    # companhia por chamada. O SQL vem declarado no dataset,
                    # como vista e campo calculado já declaram os seus: o
                    # motor executa o que a configuração diz, sem saber o que
                    # os valores significam. Resolve-se aqui porque é aqui
                    # que há banco; `paginacao` só percorre.
                    url = _urls_da_janela(fonte, ds, janela)[0]
                    itens = None
                    if (iteracao := _parametros(ds).get("iteracao")):
                        linhas_it = sink.consultar(iteracao["sql"])
                        itens = [str(list(ln.values())[0]) for ln in linhas_it
                                 if list(ln.values())[0] is not None]
                        if not itens:
                            raise ErroIngestao(
                                f"a iteração do dataset '{dataset_chave}' não "
                                f"devolveu valor nenhum — sem itens não há o "
                                f"que capturar. O SQL declarado depende de "
                                f"outra classe já carregada?"
                            )
                    payload = paginacao.capturar(url, _parametros(ds), baixar,
                                                 itens=itens)
                    cid, nova = gravar_bronze(
                        sink, dataset_chave, janela,
                        credenciais.censurar(url, fonte["credencial_ref"]),
                        f"{dataset_chave}.json", payload,
                    )
                    res.capturas_novas += int(nova)
                    desta_rodada.append(cid)
                elif fonte["tipo_transporte"] == "http_token":
                    # Duas requisições para um arquivo: a primeira devolve um
                    # JSON com um bilhete, a segunda troca o bilhete pelos
                    # bytes. O que é da fonte — o nome do campo e o endereço do
                    # segundo passo — está declarado no mapeamento, como já
                    # acontece com `caminho_registros` e `paginacao` do
                    # transporte JSON. Um transporte que soubesse o nome de uma
                    # fonte específica quebraria o engine único.
                    for url in _urls_da_janela(fonte, ds, janela):
                        url_arquivo, nome = _trocar_bilhete(
                            url, _parametros(ds), baixar
                        )
                        payload = baixar(url_arquivo)
                        cid, nova = gravar_bronze(
                            sink, dataset_chave, janela,
                            # O bronze guarda o endereço do **pedido**, não o
                            # do bilhete: o bilhete vence e o segundo endereço
                            # deixa de responder em minutos, o que faria a
                            # proveniência apontar para um lugar morto.
                            credenciais.censurar(url, fonte["credencial_ref"]),
                            nome, payload,
                        )
                        res.capturas_novas += int(nova)
                        desta_rodada.append(cid)
                else:
                    for url in _urls_da_janela(fonte, ds, janela):
                        nome = url.rsplit("/", 1)[-1].split("?")[0]
                        payload = baixar(url)
                        cid, nova = gravar_bronze(
                            sink, dataset_chave, janela,
                            credenciais.censurar(url, fonte["credencial_ref"]),
                            nome, payload,
                        )
                        res.capturas_novas += int(nova)
                        desta_rodada.append(cid)
        repo.atualizar_execucao(sink, exec_id, status="capturado")

        capturas = (capturas_por_id(sink, desta_rodada) if desta_rodada
                    else capturas_da_janela(sink, dataset_chave, janela))
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
        with obs.fase(sink, exec_id, "carregar"):
            for captura in capturas:
                payload = payload_de(sink, captura["id"])
                if fonte["tipo_transporte"] == "http_zip":
                    membros = parsing.membros_do_zip(payload, ds["padrao_arquivo"])
                elif fonte["tipo_transporte"] == "http_json":
                    # Numa fonte de arquivo, o contexto das pseudo-colunas `$`
                    # vem dos grupos nomeados do nome do arquivo. Numa API não
                    # há nome que carregue nada: o que distingue uma chamada da
                    # outra — qual série, qual país, qual código — está nos
                    # parâmetros declarados no mapeamento. Só escalares entram;
                    # `modelo` e `paginacao` são do transporte, não do dado.
                    membros = [(
                        captura["nome_arquivo"], payload,
                        {k: str(v) for k, v in _parametros(ds).items()
                         if isinstance(v, (str, int, float))},
                    )]
                else:
                    import re as _re

                    base = captura["nome_arquivo"]
                    m = _re.match(ds["padrao_arquivo"], base, _re.IGNORECASE)
                    membros = (
                        [(base, payload, m.groupdict() if m else {})] if m else []
                    )
                for nome, raw, contexto in membros:
                    res.linhas_silver += carregar_arquivo(
                        sink, ds, colunas, fonte, captura["id"], nome, raw, contexto
                    )

        # ---------- calculados ----------
        repo.atualizar_execucao(sink, exec_id, status="recomputando")
        with obs.fase(sink, exec_id, "calcular"):
            calc.aplicar(
                sink, ds, repo.calculados_do(sink, ds["id"]),
                capturas=[c["id"] for c in capturas],
            )

        # ---------- qualidade ----------
        repo.atualizar_execucao(sink, exec_id, status="validando")
        with obs.fase(sink, exec_id, "validar"):
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
            # Carga bloqueada também pesa: o bronze foi capturado e continua
            # no banco. Relatar só o sucesso esconderia justamente o custo que
            # não virou dado publicado.
            _relatar(sink, ds, res, exec_id)
            return res

        # ---------- publicação ----------
        if publicar:
            with obs.fase(sink, exec_id, "publicar"):
                res.publicacao = pub.publicar(sink, exec_id)
        res.status = "publicado"
        repo.atualizar_execucao(
            sink, exec_id, status="publicado", capturas=res.capturas,
            linhas_silver=res.linhas_silver, delta_linhas=res.delta_linhas,
            publicacao=res.publicacao, terminado_em=_agora(),
        )
        _relatar(sink, ds, res, exec_id)
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
    # A trava vem antes do DELETE: apagar o silver e depois descobrir que a
    # janela é de outra carga deixaria a tabela vazia até alguém notar.
    with repo.trava_execucao(sink, dataset_chave, janela) as obtida:
        if not obtida:
            return Resultado(0, dataset_chave, janela, "ja_em_execucao")
        capturas = [c["id"] for c in capturas_da_janela(sink, dataset_chave, janela)]
        if capturas:
            marcadores = ",".join("?" for _ in capturas)
            sink.executar(
                f"DELETE FROM {ds['tabela_destino']} WHERE captura_id IN ({marcadores})",
                capturas,
            )
        return _executar(
            sink, dataset_chave, janela, trigger="replay", baixar=None,
            publicar=publicar,
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
