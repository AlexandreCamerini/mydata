"""A CVM como linhas de configuração — nenhuma linha de código específica dela.

Tudo o que o sistema sabe sobre a CVM está aqui, em dados: o template de URL,
o regex do nome do arquivo (cujos grupos nomeados viram colunas), o mapa de
colunas e os campos calculados que resolvem as sete armadilhas do dado.

Trocar isto por outra fonte é cadastrar outras linhas — não é editar o motor.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from .repositorio import (
    Atributo, CampoCalculado, Classe, Coluna, Dataset, Fonte, RegraQualidade,
    Vista, salvar_agendamento, salvar_classe, salvar_dataset, salvar_fonte,
    salvar_vista,
)
from .motor import ddl
from .sinks import Sink

FONTE = Fonte(
    chave="cvm",
    nome="CVM Dados Abertos",
    descricao="Companhias abertas — demonstrações (DFP/ITR) e cadastro.",
    tipo_transporte="http_zip",
    url_template=(
        "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{TIPO}/DADOS/"
        "{tipo}_cia_aberta_{ano}.zip"
    ),
    encoding="latin-1",   # ler como utf-8 corrompe DENOM_CIA e DS_CONTA
    separador=";",
)

FONTE_CADASTRO = Fonte(
    chave="cvm_cadastro",
    nome="CVM — cadastro de companhias abertas",
    descricao="cad_cia_aberta.csv, dataset separado do de demonstrações.",
    tipo_transporte="http_csv",
    url_template="https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv",
    encoding="latin-1",
    separador=";",
)

# Grupos nomeados do regex viram colunas via `$nome`. É por isso que tipo_doc,
# grupo e con/ind não precisam de código: saem do nome do arquivo.
PADRAO_CONTA = (
    r"^(?P<tipo_doc>dfp|itr)_cia_aberta_"
    r"(?P<grupo>BPA|BPP|DRE|DFC_MI|DFC_MD|DVA|DRA|DMPL)_"
    r"(?P<escopo>con|ind)_(?P<ano>\d{4})\.csv$"
)

COLUNAS_CONTA = [
    Coluna("$tipo_doc", "tipo_doc", "texto", obrigatoria=True, ordem=1),
    Coluna("$grupo", "grupo", "texto", obrigatoria=True, ordem=2),
    # `consolidado` sai do nome do arquivo e não pode ser campo calculado:
    # está na chave natural, e calculado só roda depois do insert — con e ind
    # colidiriam no ON CONFLICT antes de existir o valor que os distingue.
    Coluna("$escopo", "consolidado", "booleano", "igual:con", obrigatoria=True, ordem=2),
    Coluna("CD_CVM", "cd_cvm", "inteiro", obrigatoria=True, ordem=3),
    Coluna("CNPJ_CIA", "cnpj", "texto", ordem=4),
    Coluna("DENOM_CIA", "denom_cia", "texto", ordem=5),
    Coluna("DT_REFER", "dt_refer", "data", "data_iso", obrigatoria=True, ordem=6),
    Coluna("DT_INI_EXERC", "dt_ini_exerc", "data", "data_iso", ordem=7),
    Coluna("DT_FIM_EXERC", "dt_fim_exerc", "data", "data_iso", ordem=8),
    Coluna("ORDEM_EXERC", "ordem_exerc", "texto", obrigatoria=True, ordem=9),
    Coluna("VERSAO", "versao", "inteiro", obrigatoria=True, ordem=10),
    Coluna("CD_CONTA", "cd_conta", "texto", obrigatoria=True, ordem=11),
    Coluna("DS_CONTA", "ds_conta", "texto", ordem=12),
    Coluna("ST_CONTA_FIXA", "st_conta_fixa", "texto", ordem=13),
    Coluna("MOEDA", "moeda", "texto", ordem=14),
    Coluna("ESCALA_MOEDA", "escala_moeda", "texto", obrigatoria=True, ordem=15),
    Coluna("COLUNA_DF", "coluna_df", "texto", ordem=16),
    Coluna("VL_CONTA", "vl_conta", "numero", "decimal_ptbr", obrigatoria=True, ordem=17),
]

# As armadilhas 3, 4, 5 e 1 viram campos calculados — não transformação.
CALCULADOS_CONTA = [
    CampoCalculado(
        nome="vl_conta_norm",
        expressao=(
            "vl_conta * CASE upper(escala_moeda) "
            "WHEN 'MIL' THEN 1000 WHEN 'MILHAO' THEN 1000000 "
            "WHEN 'MILHÃO' THEN 1000000 ELSE 1 END"
        ),
        colunas_origem=["vl_conta", "escala_moeda"],
        descricao="Armadilha 3: a escala varia por empresa. vl_conta original "
                  "permanece intacto ao lado.",
        ordem=2,
    ),
    CampoCalculado(
        nome="itr_acumulado",
        # tipo_doc e grupo vêm do nome do arquivo, cuja caixa a CVM não
        # garante — comparação insensível a maiúscula é parte do contrato.
        expressao=(
            "upper(tipo_doc) = 'ITR' AND upper(grupo) IN "
            "('DRE','DFC_MI','DFC_MD','DVA','DRA')"
        ),
        colunas_origem=["tipo_doc", "grupo"],
        tipo_retorno="boolean",
        descricao="Armadilha 5: no ITR, conta de fluxo é acumulada no ano (YTD). "
                  "Conta de posição (BPA/BPP/DMPL) não acumula.",
        ordem=3,
    ),
    CampoCalculado(
        nome="is_latest",
        classe="janela",
        expressao="versao = max(versao) {OVER}",
        colunas_origem=["versao", "cd_cvm", "tipo_doc", "dt_refer"],
        particao_por=["cd_cvm", "tipo_doc", "dt_refer"],
        tipo_retorno="boolean",
        descricao="Armadilha 1: reapresentação. Partição global — reingerir um "
                  "ano antigo pode rebaixar documento de outro ano, então este "
                  "campo é recomputado sobre a tabela inteira.",
        ordem=4,
    ),
]

REGRAS_CONTA = [
    RegraQualidade(
        nome="escala_desconhecida",
        expressao_sql=(
            "SELECT 1 FROM fato_conta WHERE escala_moeda IS NOT NULL "
            "AND upper(escala_moeda) NOT IN ('UNIDADE','MIL','MILHAO','MILHÃO')"
        ),
        severidade="bloqueia",
        descricao="Escala nova na fonte significa vl_conta_norm errado em silêncio.",
    ),
    RegraQualidade(
        nome="valor_nao_convertido",
        expressao_sql=(
            "SELECT 1 FROM fato_conta WHERE vl_conta IS NULL "
            "AND vl_conta_txt IS NOT NULL AND vl_conta_txt <> ''"
        ),
        severidade="bloqueia",
        descricao="Texto presente e número nulo = formato numérico mudou.",
    ),
    RegraQualidade(
        nome="ordem_exerc_inesperada",
        expressao_sql=(
            "SELECT 1 FROM fato_conta WHERE ordem_exerc NOT IN "
            "('ÚLTIMO','PENÚLTIMO')"
        ),
        severidade="alerta",
        descricao="Armadilha 2: gold filtra ÚLTIMO. Valor novo aqui muda o filtro.",
    ),
    RegraQualidade(
        nome="reconciliacao_ativo_passivo",
        expressao_sql=(
            "SELECT a.cd_cvm, a.dt_refer, a.consolidado, "
            "       a.total AS ativo, p.total AS passivo "
            "FROM (SELECT cd_cvm, dt_refer, consolidado, sum(vl_conta_norm) AS total "
            "      FROM fato_conta WHERE is_latest AND ordem_exerc = 'ÚLTIMO' "
            "      AND grupo = 'BPA' AND cd_conta = '1' "
            "      GROUP BY cd_cvm, dt_refer, consolidado) a "
            "JOIN (SELECT cd_cvm, dt_refer, consolidado, sum(vl_conta_norm) AS total "
            "      FROM fato_conta WHERE is_latest AND ordem_exerc = 'ÚLTIMO' "
            "      AND grupo = 'BPP' AND cd_conta = '2' "
            "      GROUP BY cd_cvm, dt_refer, consolidado) p "
            "ON a.cd_cvm = p.cd_cvm AND a.dt_refer = p.dt_refer "
            "AND a.consolidado = p.consolidado "
            # Tolerância relativa, não absoluta. A CVM publica em milhares ou
            # milhões, então a menor diferença representável na fonte é
            # R$ 1.000 — com limite de R$ 1,00 um único arredondamento de
            # milésimo derrubava a carga de um ano inteiro. Medido: a RGE Sul
            # diferia R$ 1.000 sobre R$ 15,5 bilhões.
            "WHERE abs(a.total - p.total) > greatest(1000.0, 0.0001 * abs(a.total))"
        ),
        severidade="bloqueia",
        # A regra existe para pegar erro sistêmico *do pipeline* — escala
        # trocada, filtro errado —, que quebraria centenas de empresas de uma
        # vez. Uma declaração inconsistente na origem é assunto da companhia,
        # não motivo para reter o ano inteiro: fica registrada na violação e o
        # operador decide. Acima de dez, é o pipeline que está errado.
        tolerancia=10,
        descricao="Ativo = Passivo + PL, com folga de 0,01% ou R$ 1.000. "
                  "Acima de dez companhias fora, o erro é da carga.",
    ),
]

CHAVE_NATURAL_CONTA = [
    "cd_cvm", "tipo_doc", "dt_refer", "grupo", "consolidado", "cd_conta",
    "ordem_exerc", "versao",
]

# --------------------------------------------------------------------------
# Classes de informação
# --------------------------------------------------------------------------
# A classe é o que o consumidor pergunta ("me dá a empresa"), independente de
# quantas fontes a alimentam. Aqui ela descreve exatamente as tabelas que já
# existem: enquanto for espelho verificado, nada muda de comportamento.
def _atr(nome, tipo="texto", **kw):
    return Atributo(nome=nome, tipo=tipo, **kw)


CLASSE_DEMONSTRACAO = Classe(
    chave="demonstracao_financeira",
    nome="Demonstração financeira",
    descricao="Uma conta contábil de uma companhia num período, como publicada.",
    tabela="fato_conta",
    chave_identidade=CHAVE_NATURAL_CONTA,
    indices=[["cd_cvm", "dt_refer"], ["cd_conta"]],
    sla_horas=24 * 120,   # DFP sai uma vez por ano; ITR, a cada trimestre.
    atributos=[
        _atr("cd_cvm", "inteiro", obrigatorio=True, ordem=1,
             descricao="Código da companhia na CVM."),
        _atr("cnpj", ordem=2),
        _atr("denom_cia", ordem=3, descricao="Denominação como consta no arquivo."),
        _atr("tipo_doc", obrigatorio=True, ordem=4, descricao="DFP ou ITR."),
        _atr("grupo", obrigatorio=True, ordem=5,
             descricao="BPA, BPP, DRE, DFC_MI, DFC_MD, DVA, DRA ou DMPL."),
        _atr("consolidado", "booleano", obrigatorio=True, ordem=6),
        _atr("dt_refer", "data", obrigatorio=True, ordem=7),
        _atr("dt_ini_exerc", "data", ordem=8),
        _atr("dt_fim_exerc", "data", ordem=9),
        _atr("ordem_exerc", obrigatorio=True, ordem=10,
             descricao="ÚLTIMO ou PENÚLTIMO. Somar sem filtrar dobra os valores."),
        _atr("versao", "inteiro", obrigatorio=True, ordem=11,
             descricao="Versão do documento. Reapresentação cria versão nova."),
        _atr("cd_conta", obrigatorio=True, ordem=12),
        _atr("ds_conta", ordem=13),
        _atr("st_conta_fixa", ordem=14, descricao="'N' indica conta customizada."),
        _atr("moeda", ordem=15),
        _atr("escala_moeda", obrigatorio=True, ordem=16,
             descricao="UNIDADE, MIL ou MILHÃO — varia por companhia."),
        _atr("coluna_df", ordem=17),
        _atr("vl_conta", "numero", ordem=18, guarda_texto=True,
             descricao="Valor na escala original. O texto do arquivo fica ao lado."),
        _atr("vl_conta_norm", "numero", origem="calculado", ordem=19,
             unidade="BRL", descricao="Valor em reais, com a escala aplicada."),
        _atr("is_latest", "booleano", origem="calculado", ordem=20,
             descricao="Última versão do documento para a companhia e a data."),
        _atr("itr_acumulado", "booleano", origem="calculado", ordem=21,
             descricao="Conta de fluxo do ITR: valor acumulado no exercício."),
    ],
)

CLASSE_EMPRESA = Classe(
    chave="empresa",
    nome="Empresa",
    descricao="Companhia aberta registrada na CVM.",
    tabela="dim_empresa",
    chave_identidade=["cd_cvm"],
    sla_horas=24 * 14,    # o cadastro é semanal; duas semanas já é atraso.
    # Duas fontes descrevem a mesma empresa e discordam: o cadastro traz
    # DENOM_SOCIAL, e o próprio arquivo de DFP traz DENOM_CIA. O cadastro é a
    # fonte de registro; a DFP cobre companhia que publicou balanço e ainda
    # não apareceu no cadastro do dia.
    resolucao="precedencia",
    precedencia=["cvm_cadastro", "cvm_dfp_empresa"],
    atributos=[
        _atr("cd_cvm", "inteiro", obrigatorio=True, ordem=1),
        _atr("cnpj", ordem=2),
        _atr("denom_social", obrigatorio=True, ordem=3,
             precedencia=["cvm_cadastro", "cvm_dfp_empresa"],
             descricao="Razão social. O cadastro vence: é o registro formal, "
                       "enquanto a DFP repete o nome como estava na entrega."),
        _atr("denom_comerc", ordem=4),
        _atr("setor_atividade", ordem=5),
        _atr("situacao", ordem=6),
        _atr("controle_acionario", ordem=7),
        _atr("uf", ordem=8),
        _atr("municipio", ordem=9),
        _atr("dt_registro", "data", ordem=10),
    ],
)

CLASSES = [CLASSE_DEMONSTRACAO, CLASSE_EMPRESA]

# --------------------------------------------------------------------------
# Vistas de gold — o contrato que o consumidor lê
# --------------------------------------------------------------------------
# `{V}` é a publicação: sem esse filtro, linha carregada e reprovada no gate
# apareceria para o consumidor no instante da carga.
VISTAS = [
    Vista(
        chave="gold_demonstracoes",
        classe_chave="demonstracao_financeira",
        descricao="Só o dado correto: última versão do documento, exercício "
                  "de referência. Armadilhas 1 e 2 resolvidas no filtro.",
        ordem=1,
        corpo="""
        SELECT cd_cvm, denom_cia, cnpj, tipo_doc, grupo, consolidado,
               dt_refer, dt_ini_exerc, dt_fim_exerc, versao,
               cd_conta, ds_conta, st_conta_fixa, escala_moeda, moeda,
               vl_conta, vl_conta_norm, itr_acumulado,
               captura_id, fonte_arquivo, publicado_em_versao
        FROM fato_conta
        WHERE is_latest AND ordem_exerc = 'ÚLTIMO'
          AND publicado_em_versao IS NOT NULL AND publicado_em_versao <= {V}
    """,
    ),
    Vista(
        chave="gold_itr_trimestre",
        classe_chave="demonstracao_financeira",
        descricao="Armadilha 5: no ITR a conta de fluxo vem acumulada no ano. "
                  "Trimestre isolado = acumulado menos o período anterior do "
                  "mesmo exercício; no primeiro trimestre os dois coincidem.",
        ordem=2,
        corpo="""
        WITH acumulado AS (
          SELECT cd_cvm, denom_cia, grupo, consolidado, cd_conta, ds_conta,
                 dt_refer, vl_conta_norm, substr(dt_refer, 1, 4) AS exercicio,
                 captura_id, fonte_arquivo, publicado_em_versao
          FROM fato_conta
          WHERE is_latest AND ordem_exerc = 'ÚLTIMO'
            AND upper(tipo_doc) = 'ITR' AND itr_acumulado
            AND publicado_em_versao IS NOT NULL AND publicado_em_versao <= {V}
        )
        SELECT a.cd_cvm, a.denom_cia, a.grupo, a.consolidado, a.cd_conta,
               a.ds_conta, a.dt_refer, a.exercicio,
               a.vl_conta_norm AS vl_acumulado,
               a.vl_conta_norm - COALESCE(
                 LAG(a.vl_conta_norm) OVER (
                   PARTITION BY a.cd_cvm, a.grupo, a.consolidado, a.cd_conta,
                                a.exercicio
                   ORDER BY a.dt_refer
                 ), 0) AS vl_trimestre,
               a.captura_id, a.fonte_arquivo, a.publicado_em_versao
        FROM acumulado a
    """,
    ),
    # `gold_empresa` não está aqui: a classe `empresa` resolve por precedência
    # e sua vista é gerada por `motor.ddl.vistas_resolvidas`. Escrevê-la à mão
    # duplicaria a regra de precedência em dois lugares que divergiriam.
]

# Colunas do arquivo de DFP que também descrevem a empresa. É a segunda fonte
# da classe `empresa` — e discorda do cadastro na razão social.
COLUNAS_EMPRESA_DFP = [
    Coluna("CD_CVM", "cd_cvm", "inteiro", obrigatoria=True, ordem=1),
    Coluna("CNPJ_CIA", "cnpj", "texto", ordem=2),
    Coluna("DENOM_CIA", "denom_social", "texto", obrigatoria=True, ordem=3),
]

COLUNAS_CADASTRO = [
    Coluna("CD_CVM", "cd_cvm", "inteiro", obrigatoria=True, ordem=1),
    Coluna("CNPJ_CIA", "cnpj", "texto", ordem=2),
    Coluna("DENOM_SOCIAL", "denom_social", "texto", obrigatoria=True, ordem=3),
    Coluna("DENOM_COMERC", "denom_comerc", "texto", ordem=4),
    Coluna("SETOR_ATIV", "setor_atividade", "texto", ordem=5),
    Coluna("SIT", "situacao", "texto", ordem=6),
    Coluna("CONTROLE_ACIONARIO", "controle_acionario", "texto", ordem=7),
    Coluna("UF", "uf", "texto", ordem=8),
    Coluna("MUN", "municipio", "texto", ordem=9),
    Coluna("DT_REG", "dt_registro", "data", "data_iso", ordem=10),
]


def datasets() -> list[Dataset]:
    comum = dict(
        fonte_chave="cvm",
        padrao_arquivo=PADRAO_CONTA,
        tabela_destino="fato_conta",
        classe_chave="demonstracao_financeira",
        chave_natural=CHAVE_NATURAL_CONTA,
        colunas=COLUNAS_CONTA,
        calculados=CALCULADOS_CONTA,
        regras=REGRAS_CONTA,
    )
    return [
        Dataset(
            chave="cvm_dfp",
            nome="Demonstrações Financeiras Padronizadas (anual)",
            descricao="DFP — um ZIP por ano, 16 CSVs por grupo e escopo.",
            parametros={"tipo": "dfp"},
            **comum,
        ),
        Dataset(
            chave="cvm_itr",
            nome="Informações Trimestrais",
            descricao="ITR — contas de fluxo vêm acumuladas no ano.",
            parametros={"tipo": "itr"},
            **comum,
        ),
        Dataset(
            chave="cvm_cadastro",
            fonte_chave="cvm_cadastro",
            nome="Cadastro de companhias abertas",
            descricao="Base do endpoint /v1/empresas.",
            padrao_arquivo=r"^cad_cia_aberta\.csv$",
            tabela_destino="dim_empresa",
            classe_chave="empresa",
            chave_natural=["cd_cvm"],
            colunas=COLUNAS_CADASTRO,
            calculados=[],
            regras=[
                RegraQualidade(
                    nome="empresa_sem_denominacao",
                    expressao_sql="SELECT 1 FROM dim_empresa WHERE denom_social IS NULL",
                    severidade="alerta",
                ),
            ],
        ),
        Dataset(
            chave="cvm_dfp_empresa",
            fonte_chave="cvm",
            nome="Empresas citadas nas DFPs",
            descricao="Segunda fonte da classe empresa: o próprio arquivo de "
                      "demonstrações traz CD_CVM, CNPJ e denominação. Cobre "
                      "companhia que publicou balanço e ainda não entrou no "
                      "cadastro do dia.",
            padrao_arquivo=PADRAO_CONTA,
            tabela_destino="dim_empresa",
            classe_chave="empresa",
            chave_natural=["cd_cvm"],
            parametros={"tipo": "dfp"},
            colunas=COLUNAS_EMPRESA_DFP,
            calculados=[],
            regras=[],
        ),
    ]


# Indicadores fundamentalistas como configuração. `c('X')` é a conta contábil
# no padrão CVM: 1.01 Ativo Circulante, 2.01 Passivo Circulante,
# 2.02 Passivo Não Circulante, 2.03 Patrimônio Líquido, 3.01 Receita,
# 3.11 Lucro/Prejuízo do período.
METRICAS = [
    ("liquidez_corrente", "Liquidez corrente", "c('1.01') / c('2.01')", "razao",
     "Ativo Circulante / Passivo Circulante. Abaixo de 1 indica aperto de caixa."),
    ("alavancagem", "Alavancagem", "(c('2.01') + c('2.02')) / c('2.03')", "razao",
     "(Passivo Circulante + Não Circulante) / Patrimônio Líquido."),
    ("margem_liquida", "Margem líquida", "c('3.11') / c('3.01')", "percentual",
     "Lucro do período / Receita. Negativa indica prejuízo."),
    ("roe", "Retorno sobre o PL", "c('3.11') / c('2.03')", "percentual",
     "Lucro do período / Patrimônio Líquido."),
    ("imobilizacao_pl", "Imobilização do PL", "c('1.02') / c('2.03')", "razao",
     "Ativo Não Circulante / Patrimônio Líquido."),
]


AGENDAMENTOS = [
    ("cvm_dfp_anual", "cvm_dfp", "0 6 1 4 *"),
    ("cvm_dfp_empresa_anual", "cvm_dfp_empresa", "0 7 1 4 *"),
    ("cvm_itr_trimestral", "cvm_itr", "0 6 15 2,5,8,11 *"),
    ("cvm_cadastro_semanal", "cvm_cadastro", "0 5 * * 1"),
]


def aplicar_metricas(sink: Sink) -> None:
    from .repositorio import _aposentar

    for chave, nome, formula, unidade, descricao in METRICAS:
        versao = _aposentar(sink, "cfg_metrica", chave)
        sink.executar(
            """INSERT INTO cfg_metrica
               (id, nome, formula, unidade, descricao, ativo, chave, versao,
                vigente, vigente_chave, criado_por)
               VALUES (?,?,?,?,?,TRUE,?,?,TRUE,?,'seed')""",
            (sink.proximo_id("cfg_metrica"), nome, formula, unidade, descricao,
             chave, versao, chave),
        )


def impressao() -> str:
    """Digest do conteúdo pretendido do seed.

    O boot do Railway roda `migrar --seed`. Sem isto, cada deploy criaria uma
    versão nova de cada fonte, classe, dataset e métrica sem nenhuma mudança
    real — o histórico de configuração viraria ruído de deploy.
    """
    corpo = json.dumps(
        {
            "classes": [asdict(c) for c in CLASSES],
            "vistas": [asdict(v) for v in VISTAS],
            "fontes": [asdict(FONTE), asdict(FONTE_CADASTRO)],
            "datasets": [asdict(d) for d in datasets()],
            "metricas": METRICAS,
            "agendamentos": AGENDAMENTOS,
        },
        ensure_ascii=False, sort_keys=True, default=str,
    )
    return hashlib.sha256(corpo.encode()).hexdigest()


def aplicar(sink: Sink, forcar: bool = False) -> bool:
    """Cadastra (ou reversiona) a configuração da CVM.

    Devolve `True` se gravou. Configuração idêntica à vigente é no-op: o
    marcador em `cfg_seed` é o que torna `migrar --seed` seguro a cada boot.
    """
    digest = impressao()
    ja = sink.um("SELECT sha256 FROM cfg_seed WHERE chave = 'cvm'")
    if ja and ja["sha256"] == digest and not forcar:
        ddl.garantir_classes(sink)   # a tabela pode faltar mesmo com config igual
        return False

    for c in CLASSES:
        salvar_classe(sink, c, autor="seed")
    ddl.garantir_classes(sink)
    for v in VISTAS:
        salvar_vista(sink, v, autor="seed")
    salvar_fonte(sink, FONTE, autor="seed")
    salvar_fonte(sink, FONTE_CADASTRO, autor="seed")
    for d in datasets():
        salvar_dataset(sink, d, autor="seed")
    for chave, dataset_chave, cron in AGENDAMENTOS:
        salvar_agendamento(sink, chave, dataset_chave, cron, autor="seed")
    aplicar_metricas(sink)

    sink.executar("DELETE FROM cfg_seed WHERE chave = 'cvm'")
    sink.executar(
        "INSERT INTO cfg_seed (chave, sha256) VALUES ('cvm', ?)", (digest,)
    )
    return True
