"""A CVM como linhas de configuração — nenhuma linha de código específica dela.

Tudo o que o sistema sabe sobre a CVM está aqui, em dados: o template de URL,
o regex do nome do arquivo (cujos grupos nomeados viram colunas), o mapa de
colunas e os campos calculados que resolvem as sete armadilhas do dado.

Trocar isto por outra fonte é cadastrar outras linhas — não é editar o motor.
"""
from __future__ import annotations

from .repositorio import (
    CampoCalculado, Coluna, Dataset, Fonte, RegraQualidade,
    salvar_agendamento, salvar_dataset, salvar_fonte,
)
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
            "WHERE abs(a.total - p.total) > 1.0"
        ),
        severidade="bloqueia",
        descricao="Ativo = Passivo + PL. Diferença acima de R$1 é erro de carga.",
    ),
]

CHAVE_NATURAL_CONTA = [
    "cd_cvm", "tipo_doc", "dt_refer", "grupo", "consolidado", "cd_conta",
    "ordem_exerc", "versao",
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
            **comum,
        ),
        Dataset(
            chave="cvm_itr",
            nome="Informações Trimestrais",
            descricao="ITR — contas de fluxo vêm acumuladas no ano.",
            **comum,
        ),
        Dataset(
            chave="cvm_cadastro",
            fonte_chave="cvm_cadastro",
            nome="Cadastro de companhias abertas",
            descricao="Base do endpoint /v1/empresas.",
            padrao_arquivo=r"^cad_cia_aberta\.csv$",
            tabela_destino="dim_empresa",
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


def aplicar(sink: Sink) -> None:
    """Cadastra (ou reversiona) a configuração da CVM."""
    salvar_fonte(sink, FONTE, autor="seed")
    salvar_fonte(sink, FONTE_CADASTRO, autor="seed")
    for d in datasets():
        salvar_dataset(sink, d, autor="seed")
    salvar_agendamento(sink, "cvm_dfp_anual", "cvm_dfp", "0 6 1 4 *", autor="seed")
    salvar_agendamento(sink, "cvm_itr_trimestral", "cvm_itr", "0 6 15 2,5,8,11 *", autor="seed")
    salvar_agendamento(sink, "cvm_cadastro_semanal", "cvm_cadastro", "0 5 * * 1", autor="seed")
    aplicar_metricas(sink)
