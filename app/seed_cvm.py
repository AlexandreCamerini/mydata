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
    Atributo, CampoCalculado, Classe, Coluna, Correlacao, Dataset, Fonte,
    RegraQualidade, Vista, salvar_agendamento, salvar_classe,
    salvar_correlacao, salvar_dataset, salvar_fonte, salvar_vista,
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

# --------------------------------------------------------------------------
# B3 — quem realmente negocia em bolsa
# --------------------------------------------------------------------------
# A CVM registra ~2.600 companhias abertas; só uma fração delas tem ação
# negociada. Nada nos arquivos da CVM diz quais — a B3 é que diz, e traz
# `codeCVM`, que liga as duas bases sem heurística de nome.
#
# Esta é a primeira dependência de terceiro do sistema. Fica isolada como
# fonte: se a B3 mudar o endpoint, quebra a captura desta fonte e nada mais.
FONTE_B3 = Fonte(
    chave="b3",
    nome="B3 — companhias listadas",
    descricao="Empresas com registro de negociação na B3, com ticker, "
              "segmento de listagem e o código CVM que faz a ligação.",
    tipo_transporte="http_json",
    url_template=(
        "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/"
        "CompanyCall/GetInitialCompanies/{parametros}"
    ),
    encoding="utf-8",
)

# A API pagina em 100 e recusa páginas maiores; os parâmetros vão em JSON
# codificado em base64 dentro do caminho, não em query string.
PARAMETROS_B3 = {
    "modelo": {"language": "pt-br", "pageNumber": "{pagina}", "pageSize": 100},
    "codificacao": "base64_json",
    "paginacao": {"tamanho": 100, "caminho_total_paginas": "page.totalPages"},
    "caminho_registros": "results",
}

COLUNAS_B3 = [
    Coluna("codeCVM", "cd_cvm", "inteiro", obrigatoria=True, ordem=1),
    Coluna("issuingCompany", "ticker", "texto", obrigatoria=True, ordem=2),
    Coluna("companyName", "denom_social", "texto", ordem=3),
    Coluna("tradingName", "nome_pregao", "texto", ordem=4),
    Coluna("cnpj", "cnpj", "texto", ordem=5),
    Coluna("segment", "setor_b3", "texto", ordem=6),
    Coluna("market", "segmento_listagem", "texto", ordem=7),
    Coluna("dateListing", "dt_listagem", "data", ordem=8),
]

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
    precedencia=["cvm_cadastro", "b3_listadas", "cvm_dfp_empresa"],
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
        # Vindos da B3. `listada_b3` é calculado: a presença de ticker é o
        # que responde "negocia em bolsa", e derivar disso evita um campo
        # que possa discordar da própria evidência.
        _atr("ticker", ordem=11, precedencia=["b3_listadas"],
             descricao="Código de negociação na B3, sem o dígito da espécie."),
        _atr("nome_pregao", ordem=12, precedencia=["b3_listadas"],
             descricao="Nome curto usado no pregão."),
        _atr("setor_b3", ordem=13, precedencia=["b3_listadas"],
             descricao="Setor de atuação segundo a B3, ex.: Bancos."),
        _atr("segmento_listagem", ordem=14, precedencia=["b3_listadas"],
             descricao="Nível de governança: NM (Novo Mercado), N1, N2, MB, "
                       "DR* (BDR). Vazio é o segmento básico."),
        _atr("dt_listagem", "data", ordem=15, precedencia=["b3_listadas"]),
        _atr("listada_b3", "booleano", origem="calculado", ordem=16,
             descricao="Tem registro de negociação na B3. Derivado da "
                       "presença de ticker, não declarado à parte."),
    ],
)

# --------------------------------------------------------------------------
# Banco Central — indicadores macroeconômicos
# --------------------------------------------------------------------------
# Terceira fonte, e a primeira que não é da CVM nem da B3. Entrou inteira como
# configuração: nenhuma linha de `app/motor/`, `app/api/` ou `app/migracoes.py`
# sabe que ela existe.
#
# O SGS é dado aberto de verdade — ao contrário das séries da B3, cujos termos
# vedam redistribuição (ver `docs/pesquisa-mercado.md` § Q4). É por isso que o
# preço não está aqui e o indicador macro está.
FONTE_BCB = Fonte(
    chave="bcb",
    nome="Banco Central — Sistema Gerenciador de Séries Temporais (SGS)",
    descricao="Séries oficiais do BCB: Selic, IPCA, câmbio, CDI. Uma série "
              "por mapeamento; o código dela é parâmetro, não código.",
    tipo_transporte="http_json",
    # A série e a janela entram no próprio endereço. `{ano}` é a janela da
    # execução; `{serie}` vem dos parâmetros declarados no mapeamento.
    url_template=(
        "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados"
        "?formato=json&dataInicial=01/01/{ano}&dataFinal=31/12/{ano}"
    ),
    encoding="utf-8",
)

# --------------------------------------------------------------------------
# brapi.dev — agregador, e a primeira fonte que exige credencial
# --------------------------------------------------------------------------
# Entra como *fonte*, sem mapeamento ativo. O motivo está em
# `docs/fontes-terceiros.md`: quase tudo que o brapi oferece ou já é ingerido
# aqui na origem (fundamentos são CVM; inflação, juros e câmbio são BCB) ou
# esbarra nos termos da B3 (preço e histórico). O que sobra — proventos,
# opções e o mapa de tickers — depende de responder de onde o brapi tira
# aquilo, e a documentação oficial não diz.
#
# Cadastrá-la mesmo assim tem função concreta: é a única fonte do sistema que
# exige token, e por isso é o caso de teste do mecanismo de credencial.
# `{recurso}` vem dos parâmetros do mapeamento — `quote/list`,
# `v2/options/chain` —, então acrescentar uma carga é uma linha, não um campo
# de URL novo.
FONTE_BRAPI = Fonte(
    chave="brapi",
    nome="brapi.dev — agregador de mercado brasileiro",
    descricao="Agregador, não origem. Menor precedencia, marcado como terceiro "
              "na proveniência, e nunca apresentado como dado primário.",
    tipo_transporte="http_json",
    url_template="https://brapi.dev/api/{recurso}",
    encoding="utf-8",
    # O token não mora aqui: este campo é o nome da variável de ambiente que o
    # contém. A documentação do brapi manda `Authorization: Bearer <token>`,
    # que é o modo padrão quando não há prefixo.
    credencial_ref="BRAPI_TOKEN",
)

CLASSE_INDICADOR = Classe(
    chave="indicador_macro",
    nome="Indicador macroeconômico",
    descricao="Uma série oficial numa data: Selic, IPCA, câmbio, CDI.",
    tabela="fato_indicador",
    chave_identidade=["indicador", "dt_referencia"],
    indices=[["indicador", "dt_referencia"]],
    # O IPCA sai uma vez por mês, com defasagem. Quarenta dias é atraso real;
    # menos que isso marcaria a classe como velha na maior parte do mês.
    sla_horas=24 * 40,
    atributos=[
        _atr("indicador", obrigatorio=True, ordem=1,
             descricao="Nome curto da série, estável entre janelas."),
        _atr("dt_referencia", "data", obrigatorio=True, ordem=2),
        _atr("valor", "numero", ordem=3, guarda_texto=True,
             descricao="Como o BCB publicou, sem conversão de unidade."),
        _atr("unidade", ordem=4,
             descricao="Declarada no mapeamento: a resposta do SGS não a traz."),
    ],
)

# `$indicador` e `$unidade` são pseudo-colunas: não vêm da resposta, vêm dos
# parâmetros declarados no mapeamento. É o mesmo mecanismo que, numa fonte de
# arquivo, tira `tipo_doc` do nome do arquivo — a diferença é de onde o
# contexto vem, não de como ele é declarado.
COLUNAS_BCB = [
    Coluna("$indicador", "indicador", "texto", obrigatoria=True, ordem=1),
    Coluna("data", "dt_referencia", "data", obrigatoria=True, ordem=2),
    Coluna("valor", "valor", "numero", ordem=3),
    Coluna("$unidade", "unidade", "texto", ordem=4),
]

# chave do mapeamento, código SGS, nome curto, descrição, unidade
SERIES_BCB = [
    ("bcb_selic_meta", "432", "selic_meta",
     "Meta da taxa Selic definida pelo Copom", "% a.a."),
    ("bcb_ipca", "433", "ipca",
     "IPCA — variação percentual mensal", "% a.m."),
    ("bcb_cambio_usd", "1", "cambio_usd_brl",
     "Dólar dos EUA, taxa de venda, diária", "BRL/USD"),
    ("bcb_cdi", "4389", "cdi",
     "Taxa CDI anualizada, base 252 dias úteis", "% a.a."),
]

# --------------------------------------------------------------------------
# B3 — séries históricas de negociação (COTAHIST)
# --------------------------------------------------------------------------
# Primeira fonte de layout posicional: 245 bytes por linha, campo em faixa de
# posições, três tipos de registro no mesmo arquivo. O motor aprendeu isso
# como formato (`formato_registro='larguras'`), então aqui é declaração.
#
# O arquivo é o mesmo para ação, opção, termo e fracionário — o que distingue
# é `TPMERC`/`CODBDI`. Por isso a classe é *negociação*, não *opção*: o
# arquivo publica um pregão de um instrumento, e opção é um recorte dele.
# Fazer duas classes obrigaria a filtrar na carga, e o filtro viraria juízo
# do motor sobre qual linha do arquivo oficial merece existir.
FONTE_B3_SERIE = Fonte(
    chave="b3_serie_historica",
    nome="B3 — séries históricas de cotação (COTAHIST)",
    descricao="Pregão diário de todos os instrumentos: ação, opção, termo, "
              "fracionário e índice. Arquivo posicional de 245 bytes.",
    tipo_transporte="http_zip",
    # O endereço de download da página de pesquisa devolve ZIP vazio para
    # requisição direta — ele depende da sessão do formulário. Este é o
    # endereço do arquivo em si, que responde a um GET simples.
    url_template=(
        "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/"
        "COTAHIST_D{dia}{mes}{ano}.ZIP"
    ),
    encoding="latin-1",   # acento de NOMRES; utf-8 estrito recusa o arquivo
    formato_registro="larguras",
)

CHAVE_NEGOCIACAO = ["dt_pregao", "codneg", "tp_mercado", "cod_bdi", "prazo_termo"]

CLASSE_NEGOCIACAO = Classe(
    chave="negociacao_b3",
    nome="Negociação na B3",
    descricao="O pregão de um instrumento num dia: preços, volume e, quando "
              "é derivativo, strike e vencimento.",
    tabela="fato_negociacao",
    # `prazo_termo` parece supérfluo até você contar as linhas: sem ele, no
    # pregão de 31/07/2026, quinze contratos a termo do mesmo papel com
    # prazos diferentes colidiam na mesma chave e o upsert guardava um só.
    chave_identidade=CHAVE_NEGOCIACAO,
    indices=[["dt_pregao", "isin", "tp_mercado"], ["codneg"],
             ["dt_vencimento"]],
    sla_horas=24 * 4,     # pregão é diário; feriado prolongado cabe em quatro dias
    atributos=[
        _atr("dt_pregao", "data", obrigatorio=True, ordem=1),
        _atr("codneg", obrigatorio=True, ordem=2,
             descricao="Código de negociação do instrumento. Para opção é o "
                       "código do contrato, ex.: ABCBH255."),
        _atr("tp_mercado", obrigatorio=True, ordem=3,
             descricao="010 vista, 070 opção de compra, 080 opção de venda, "
                       "030 termo, 012/013 exercício de opção."),
        _atr("cod_bdi", obrigatorio=True, ordem=4,
             descricao="02 lote padrão, 78 opção de compra, 82 opção de "
                       "venda, 74/75 opção de índice, 96 fracionário."),
        _atr("prazo_termo", ordem=5,
             descricao="Prazo em dias do contrato a termo. Vazio fora do termo, "
                       "e parte da identidade porque dois termos do mesmo papel "
                       "só se distinguem por ele."),
        _atr("nome_resumido", ordem=6),
        _atr("especificacao", ordem=7, descricao="ON, PN, UNT, DRN…"),
        _atr("moeda_referencia", ordem=8),
        _atr("preco_abertura", "numero", ordem=9, guarda_texto=True),
        _atr("preco_maximo", "numero", ordem=10, guarda_texto=True),
        _atr("preco_minimo", "numero", ordem=11, guarda_texto=True),
        _atr("preco_medio", "numero", ordem=12, guarda_texto=True),
        _atr("preco_fechamento", "numero", ordem=13, guarda_texto=True,
             descricao="Preço do último negócio. Para opção é o prêmio."),
        _atr("melhor_oferta_compra", "numero", ordem=14),
        _atr("melhor_oferta_venda", "numero", ordem=15),
        _atr("total_negocios", "inteiro", ordem=16),
        _atr("quantidade_negociada", "inteiro", ordem=17),
        _atr("volume_financeiro", "numero", ordem=18),
        _atr("preco_exercicio", "numero", ordem=19, guarda_texto=True,
             descricao="Strike. Zero fora de opção e termo."),
        _atr("indicador_correcao_exercicio", ordem=20),
        _atr("dt_vencimento", "data", ordem=21,
             descricao="Vencimento do derivativo. Ação traz a sentinela "
                       "9999-12-31, que é o que a B3 grava — a vista de gold "
                       "é que decide o que isso significa."),
        _atr("fator_cotacao", "inteiro", ordem=22,
             descricao="1 = preço unitário; 1000 = cotação por lote de mil."),
        _atr("preco_exercicio_pontos", "numero", ordem=23,
             descricao="Strike em pontos, para opção referenciada em índice "
                       "ou dólar. Seis casas decimais implícitas."),
        _atr("isin", ordem=24,
             descricao="Código ISIN. Num registro de opção ele é o do "
                       "*ativo-objeto*, não o do contrato — é o que liga a "
                       "opção ao papel sem inferir pelo prefixo do código."),
        _atr("num_distribuicao", ordem=25),
        _atr("ticker_objeto", origem="calculado", ordem=26,
             descricao="Código de negociação do ativo-objeto, resolvido pelo "
                       "ISIN contra os registros à vista do mesmo pregão."),
        _atr("preco_objeto", "numero", origem="calculado", ordem=27,
             descricao="Fechamento do ativo-objeto no mesmo pregão — o spot "
                       "que entra em Black-Scholes."),
        _atr("taxa_livre_risco", "numero", origem="calculado", ordem=28,
             unidade="fração ao ano",
             descricao="CDI vigente na data, em fração (0,105 = 10,5% a.a.). "
                       "Nulo enquanto a classe de indicador não tiver carga."),
        _atr("log_retorno", "numero", origem="calculado", ordem=29,
             descricao="Log-retorno do fechamento contra o pregão anterior do "
                       "mesmo instrumento."),
        _atr("hv21", "numero", origem="calculado", ordem=30, unidade="fração ao ano",
             descricao="Volatilidade histórica de 21 pregões, anualizada por "
                       "raiz de 252. Nula até haver 21 pregões carregados."),
        _atr("hv63", "numero", origem="calculado", ordem=31, unidade="fração ao ano",
             descricao="Volatilidade histórica de 63 pregões, anualizada."),
        _atr("hv21_objeto", "numero", origem="calculado", ordem=32,
             unidade="fração ao ano",
             descricao="HV21 do ativo-objeto, trazida para a linha da opção."),
        _atr("prazo_anos", "numero", origem="calculado", ordem=33, unidade="anos",
             descricao="Dias úteis até o vencimento sobre 252. Não desconta "
                       "feriado — exigiria um calendário, que é outra fonte."),
        _atr("volatilidade_implicita", "numero", origem="calculado", ordem=34,
             unidade="fração ao ano",
             descricao="Sigma que faz o preço BSM igualar o prêmio negociado. "
                       "Nula quando o prêmio está fora do que o modelo alcança."),
        _atr("preco_teorico", "numero", origem="calculado", ordem=35,
             descricao="Preço BSM com a volatilidade implícita. Reproduz o "
                       "prêmio quando a inversão convergiu — é a conferência."),
        _atr("delta", "numero", origem="calculado", ordem=36),
        _atr("gamma", "numero", origem="calculado", ordem=37),
        _atr("vega", "numero", origem="calculado", ordem=38,
             descricao="Por ponto de volatilidade (1%), não por unidade."),
        _atr("theta", "numero", origem="calculado", ordem=39,
             descricao="Por dia útil: a perda de valor de um pregão."),
        _atr("rho", "numero", origem="calculado", ordem=40,
             descricao="Por ponto percentual de taxa."),
    ],
)

# As faixas vêm do layout oficial da B3 (SeriesHistoricas_Layout.pdf, rev. 01)
# e foram conferidas contra o arquivo de 31/07/2026. Posição 1-indexada e
# inclusiva, como no PDF; `implicito:N` é a vírgula que o arquivo não tem.
COLUNAS_COTAHIST = [
    Coluna("DATA@3-10", "dt_pregao", "data", obrigatoria=True, ordem=1),
    Coluna("CODNEG@13-24", "codneg", "texto", obrigatoria=True, ordem=2),
    Coluna("TPMERC@25-27", "tp_mercado", "texto", obrigatoria=True, ordem=3),
    Coluna("CODBDI@11-12", "cod_bdi", "texto", obrigatoria=True, ordem=4),
    # `000` é o que a própria B3 grava fora do termo — nas opções, por
    # exemplo. Fora dele o campo vem em branco, e branco na identidade
    # significa recarga que duplica em silêncio.
    Coluna("PRAZOT@50-52", "prazo_termo", "texto", "vazio:000", ordem=5),
    Coluna("NOMRES@28-39", "nome_resumido", "texto", ordem=6),
    Coluna("ESPECI@40-49", "especificacao", "texto", ordem=7),
    Coluna("MODREF@53-56", "moeda_referencia", "texto", ordem=8),
    Coluna("PREABE@57-69", "preco_abertura", "numero", "implicito:2", ordem=9),
    Coluna("PREMAX@70-82", "preco_maximo", "numero", "implicito:2", ordem=10),
    Coluna("PREMIN@83-95", "preco_minimo", "numero", "implicito:2", ordem=11),
    Coluna("PREMED@96-108", "preco_medio", "numero", "implicito:2", ordem=12),
    Coluna("PREULT@109-121", "preco_fechamento", "numero", "implicito:2", ordem=13),
    Coluna("PREOFC@122-134", "melhor_oferta_compra", "numero", "implicito:2",
           ordem=14),
    Coluna("PREOFV@135-147", "melhor_oferta_venda", "numero", "implicito:2",
           ordem=15),
    Coluna("TOTNEG@148-152", "total_negocios", "inteiro", ordem=16),
    Coluna("QUATOT@153-170", "quantidade_negociada", "inteiro", ordem=17),
    Coluna("VOLTOT@171-188", "volume_financeiro", "numero", "implicito:2", ordem=18),
    Coluna("PREEXE@189-201", "preco_exercicio", "numero", "implicito:2", ordem=19),
    Coluna("INDOPC@202-202", "indicador_correcao_exercicio", "texto", ordem=20),
    Coluna("DATVEN@203-210", "dt_vencimento", "data", ordem=21),
    Coluna("FATCOT@211-217", "fator_cotacao", "inteiro", ordem=22),
    Coluna("PTOEXE@218-230", "preco_exercicio_pontos", "numero", "implicito:6",
           ordem=23),
    Coluna("CODISI@231-242", "isin", "texto", ordem=24),
    Coluna("DISMES@243-245", "num_distribuicao", "texto", ordem=25),
]

CLASSES = [CLASSE_DEMONSTRACAO, CLASSE_EMPRESA, CLASSE_INDICADOR,
           CLASSE_NEGOCIACAO]

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
    Vista(
        chave="gold_indicadores",
        classe_chave="indicador_macro",
        descricao="Séries do BCB publicadas. Fonte única, então não há "
                  "precedência a resolver — só o gate de publicação.",
        ordem=3,
        corpo="""
        SELECT indicador, dt_referencia, valor, valor_txt, unidade,
               captura_id, fonte_arquivo, publicado_em_versao
        FROM fato_indicador
        WHERE publicado_em_versao IS NOT NULL AND publicado_em_versao <= {V}
    """,
    ),
    Vista(
        chave="gold_cotacoes",
        classe_chave="negociacao_b3",
        descricao="Pregão do lote padrão: uma linha por papel por dia. É o "
                  "recorte à vista de `fato_negociacao`.",
        ordem=4,
        corpo="""
        SELECT dt_pregao, codneg AS ticker, nome_resumido, especificacao, isin,
               preco_abertura, preco_maximo, preco_minimo, preco_medio,
               preco_fechamento, total_negocios, quantidade_negociada,
               volume_financeiro, log_retorno, hv21, hv63,
               captura_id, fonte_arquivo, publicado_em_versao
        FROM fato_negociacao
        WHERE tp_mercado = '010'
          AND publicado_em_versao IS NOT NULL AND publicado_em_versao <= {V}
    """,
    ),
    Vista(
        chave="gold_opcoes",
        classe_chave="negociacao_b3",
        descricao="Contratos de opção com ativo-objeto resolvido, prazo, "
                  "volatilidade implícita e gregas. Sentinela de vencimento "
                  "não chega aqui: opção tem vencimento de verdade.",
        ordem=5,
        corpo="""
        SELECT dt_pregao, codneg AS contrato, ticker_objeto,
               CASE tp_mercado WHEN '070' THEN 'CALL' WHEN '080' THEN 'PUT' END
                 AS tipo,
               preco_exercicio AS strike, dt_vencimento, prazo_anos,
               preco_fechamento AS premio, melhor_oferta_compra,
               melhor_oferta_venda, total_negocios, quantidade_negociada,
               volume_financeiro, preco_objeto, taxa_livre_risco,
               volatilidade_implicita, hv21_objeto, preco_teorico,
               delta, gamma, vega, theta, rho, isin,
               captura_id, fonte_arquivo, publicado_em_versao
        FROM fato_negociacao
        WHERE tp_mercado IN ('070', '080')
          AND publicado_em_versao IS NOT NULL AND publicado_em_versao <= {V}
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


# O ativo-objeto sai do próprio arquivo. Num registro de opção o `CODISI` é o
# ISIN do papel subjacente, não o do contrato — então casar a opção com o
# registro à vista do mesmo pregão resolve a ligação com dado publicado, sem
# arquivo auxiliar e sem inferir pelo prefixo do código de negociação. No
# pregão de 31/07/2026 isso resolve 11.320 de 11.321 opções.
#
# `min()` em vez de subconsulta escalar simples: um ISIN com dois códigos à
# vista faria o `=` explodir na carga inteira. Não acontece hoje — 1.403
# ISINs, nenhum ambíguo — e a regra de qualidade abaixo avisa se passar a
# acontecer, em vez de a carga cair.
CALCULADOS_NEGOCIACAO = [
    CampoCalculado(
        nome="ticker_objeto",
        classe="escalar",
        expressao=(
            "(SELECT min(objeto.codneg) FROM fato_negociacao AS objeto "
            " WHERE objeto.dt_pregao = fato_negociacao.dt_pregao "
            "   AND objeto.isin = fato_negociacao.isin "
            "   AND objeto.tp_mercado = '010')"
        ),
        colunas_origem=["dt_pregao", "isin", "tp_mercado", "codneg"],
        tipo_retorno="text",
        descricao="Código à vista do ativo-objeto, resolvido pelo ISIN dentro "
                  "do mesmo pregão.",
        ordem=1,
    ),
    CampoCalculado(
        nome="preco_objeto",
        classe="escalar",
        expressao=(
            "(SELECT min(objeto.preco_fechamento) FROM fato_negociacao AS objeto "
            " WHERE objeto.dt_pregao = fato_negociacao.dt_pregao "
            "   AND objeto.codneg = fato_negociacao.ticker_objeto "
            "   AND objeto.tp_mercado = '010')"
        ),
        colunas_origem=["dt_pregao", "ticker_objeto", "tp_mercado",
                        "preco_fechamento"],
        descricao="Spot do ativo-objeto no mesmo pregão.",
        ordem=2,
    ),
    CampoCalculado(
        nome="taxa_livre_risco",
        classe="escalar",
        # O CDI sai do BCB em % ao ano; Black-Scholes quer fração. A data
        # exata pode não existir na série — fim de semana, feriado —, então
        # vale a última publicada até o pregão.
        expressao=(
            "(SELECT max(taxa.valor) / 100.0 FROM fato_indicador AS taxa "
            " WHERE taxa.indicador = 'cdi' AND taxa.dt_referencia = "
            "   (SELECT max(anterior.dt_referencia) FROM fato_indicador AS anterior "
            "     WHERE anterior.indicador = 'cdi' "
            "       AND anterior.dt_referencia <= fato_negociacao.dt_pregao))"
        ),
        colunas_origem=["dt_pregao"],
        descricao="CDI vigente na data do pregão, em fração ao ano.",
        ordem=3,
    ),
    CampoCalculado(
        nome="log_retorno",
        classe="janela",
        # Fechamento zero existe em contrato que não negociou; `ln(0)` é erro
        # de execução, e derrubaria a carga do pregão inteiro.
        expressao=(
            "CASE WHEN preco_fechamento > 0 "
            "      AND lag(preco_fechamento) {OVER} > 0 "
            "     THEN ln(preco_fechamento / lag(preco_fechamento) {OVER}) END"
        ),
        colunas_origem=["preco_fechamento", "codneg", "dt_pregao"],
        particao_por=["codneg"],
        ordena_por=["dt_pregao"],
        descricao="Log-retorno contra o pregão anterior do mesmo instrumento.",
        ordem=4,
    ),
    *[
        CampoCalculado(
            nome=f"hv{janela}",
            classe="janela",
            expressao="stddev_samp(log_retorno) {OVER} * sqrt(252)",
            colunas_origem=["log_retorno", "codneg", "dt_pregao"],
            particao_por=["codneg"],
            ordena_por=["dt_pregao"],
            # Sem a moldura, o ORDER BY acumula desde a primeira captura e a
            # «volatilidade de 21 pregões» vira a volatilidade desde sempre.
            moldura=f"ROWS BETWEEN {janela - 1} PRECEDING AND CURRENT ROW",
            descricao=f"Volatilidade histórica de {janela} pregões, anualizada "
                      f"por raiz de 252.",
            ordem=5,
        )
        for janela in (21, 63)
    ],
    CampoCalculado(
        nome="hv21_objeto",
        classe="escalar",
        expressao=(
            "(SELECT min(objeto.hv21) FROM fato_negociacao AS objeto "
            " WHERE objeto.dt_pregao = fato_negociacao.dt_pregao "
            "   AND objeto.codneg = fato_negociacao.ticker_objeto "
            "   AND objeto.tp_mercado = '010')"
        ),
        colunas_origem=["dt_pregao", "ticker_objeto", "tp_mercado", "hv21"],
        descricao="HV21 do ativo-objeto, na linha da opção.",
        ordem=6,
    ),
    # --------------------------------------------------------------------
    # O que SQL não exprime. Uma onda por `ordem`: o prazo alimenta a
    # inversão, e a inversão alimenta as gregas.
    # --------------------------------------------------------------------
    CampoCalculado(
        nome="prazo_anos",
        classe="numerico",
        expressao="prazo_anos(dt_pregao, dt_vencimento)",
        colunas_origem=["dt_pregao", "dt_vencimento"],
        descricao="Dias úteis até o vencimento sobre 252.",
        ordem=10,
    ),
    CampoCalculado(
        nome="volatilidade_implicita",
        classe="numerico",
        expressao=(
            "bs_iv(tp_mercado, preco_fechamento, preco_objeto, "
            "preco_exercicio, prazo_anos, taxa_livre_risco)"
        ),
        colunas_origem=["tp_mercado", "preco_fechamento", "preco_objeto",
                        "preco_exercicio", "prazo_anos", "taxa_livre_risco"],
        descricao="Inversão de Black-Scholes sobre o prêmio negociado.",
        ordem=11,
    ),
    *[
        CampoCalculado(
            nome=nome,
            classe="numerico",
            expressao=(
                f"{funcao}(tp_mercado, preco_objeto, preco_exercicio, "
                f"prazo_anos, taxa_livre_risco, volatilidade_implicita)"
            ),
            colunas_origem=["tp_mercado", "preco_objeto", "preco_exercicio",
                            "prazo_anos", "taxa_livre_risco",
                            "volatilidade_implicita"],
            descricao=descricao,
            ordem=12,
        )
        for nome, funcao, descricao in [
            ("preco_teorico", "bs_preco",
             "Preço BSM com a volatilidade implícita — reproduz o prêmio "
             "quando a inversão convergiu."),
            ("delta", "bs_delta", "Variação do prêmio por real do ativo-objeto."),
            ("gamma", "bs_gamma", "Variação do delta por real do ativo-objeto."),
            ("vega", "bs_vega", "Por ponto de volatilidade (1%)."),
            ("theta", "bs_theta", "Por dia útil."),
            ("rho", "bs_rho", "Por ponto percentual de taxa."),
        ]
    ],
]

REGRAS_NEGOCIACAO = [
    RegraQualidade(
        nome="negociacao_isin_a_vista_ambiguo",
        expressao_sql=(
            "SELECT dt_pregao, isin FROM fato_negociacao "
            "WHERE tp_mercado = '010' AND isin IS NOT NULL "
            "GROUP BY dt_pregao, isin HAVING count(DISTINCT codneg) > 1"
        ),
        severidade="alerta",
        descricao="Dois códigos à vista para o mesmo ISIN no mesmo pregão: a "
                  "resolução do ativo-objeto passou a escolher, e o critério "
                  "vira arbitrário.",
    ),
    RegraQualidade(
        nome="negociacao_opcao_sem_ativo_objeto",
        expressao_sql=(
            "SELECT dt_pregao, codneg FROM fato_negociacao "
            "WHERE tp_mercado IN ('070','080') AND ticker_objeto IS NULL"
        ),
        severidade="alerta",
        # Acontece de verdade: no pregão medido, uma opção ficou órfã porque o
        # papel dela não negociou naquele dia. É informação, não defeito.
        tolerancia=0.02,
        descricao="Opção cujo ativo-objeto não negociou no mesmo pregão. "
                  "Esperado em papel ilíquido; em massa, é o ISIN mudando.",
    ),
    RegraQualidade(
        nome="negociacao_preco_sem_numero",
        expressao_sql=(
            "SELECT dt_pregao, codneg FROM fato_negociacao "
            "WHERE preco_fechamento IS NULL AND preco_fechamento_txt IS NOT NULL "
            "AND preco_fechamento_txt <> ''"
        ),
        severidade="bloqueia",
        descricao="Texto presente e número nulo: as posições do layout "
                  "deslocaram, ou a escala implícita mudou.",
    ),
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
            chave="b3_cotahist",
            fonte_chave="b3_serie_historica",
            nome="Séries históricas de cotação (COTAHIST diário)",
            descricao="Um pregão inteiro: ação, opção, termo e fracionário no "
                      "mesmo arquivo posicional. A janela é a data do pregão.",
            # Um único TXT por ZIP, homônimo do arquivo.
            padrao_arquivo=r"^COTAHIST_D\d{8}\.TXT$",
            # Cabeçalho e encerramento têm os mesmos 245 bytes de uma cotação.
            # Sem o recorte, `COTAHIST.202` entraria como código de negociação.
            filtro_linha=r"^01",
            tabela_destino="fato_negociacao",
            classe_chave="negociacao_b3",
            chave_natural=CHAVE_NEGOCIACAO,
            particao="dia",
            colunas=COLUNAS_COTAHIST,
            calculados=CALCULADOS_NEGOCIACAO,
            regras=REGRAS_NEGOCIACAO,
        ),
        Dataset(
            chave="b3_listadas",
            fonte_chave="b3",
            nome="Companhias listadas na B3",
            descricao="Quem realmente negocia em bolsa, com ticker e segmento. "
                      "`codeCVM` liga ao cadastro da CVM sem heurística de nome.",
            padrao_arquivo=r"^b3_listadas\.json$",
            tabela_destino="dim_empresa",
            classe_chave="empresa",
            chave_natural=["cd_cvm"],
            parametros=PARAMETROS_B3,
            colunas=COLUNAS_B3,
            calculados=[
                CampoCalculado(
                    nome="listada_b3",
                    expressao="ticker IS NOT NULL AND ticker <> ''",
                    colunas_origem=["ticker"],
                    tipo_retorno="boolean",
                    descricao="Derivado da presença de ticker: a evidência de "
                              "que negocia é o próprio código de negociação.",
                    ordem=1,
                ),
            ],
            regras=[
                RegraQualidade(
                    nome="listada_sem_codigo_cvm",
                    expressao_sql=(
                        "SELECT 1 FROM dim_empresa "
                        "WHERE origem_dataset = 'b3_listadas' AND cd_cvm IS NULL"
                    ),
                    severidade="bloqueia",
                    descricao="Sem cd_cvm a linha da B3 não liga a nada: viraria "
                              "empresa fantasma, sem balanço e sem cadastro.",
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
        *[
            Dataset(
                chave=chave,
                fonte_chave="bcb",
                nome=descricao,
                descricao=f"Série {codigo} do SGS. {descricao}.",
                padrao_arquivo=rf"^{chave}\.json$",
                tabela_destino="fato_indicador",
                classe_chave="indicador_macro",
                chave_natural=["indicador", "dt_referencia"],
                # `serie` monta a URL; `indicador` e `unidade` viram coluna via
                # as pseudo-colunas `$`. Uma série nova é uma linha aqui.
                parametros={
                    "serie": codigo, "indicador": nome, "unidade": unidade,
                },
                colunas=COLUNAS_BCB,
                calculados=[],
                regras=[
                    RegraQualidade(
                        nome=f"{chave}_sem_valor",
                        expressao_sql=(
                            "SELECT 1 FROM fato_indicador "
                            f"WHERE indicador = '{nome}' AND valor IS NULL "
                            "AND valor_txt IS NOT NULL AND valor_txt <> ''"
                        ),
                        severidade="bloqueia",
                        descricao="Texto presente e número nulo: o SGS mudou o "
                                  "formato do valor e a conversão silenciou.",
                    ),
                ],
            )
            for chave, codigo, nome, descricao, unidade in SERIES_BCB
        ],
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


# --------------------------------------------------------------------------
# Correlações — como as classes se ligam
# --------------------------------------------------------------------------
# Declarada, e não escrita na consulta de quem consome: é o que permite o
# escopo por classe da chave de API alcançar a travessia, e o que evita cada
# consumidor reinventar a ligação — inclusive errada.
CORRELACOES = [
    Correlacao(
        chave="empresa_demonstracoes",
        classe_origem="empresa",
        classe_destino="demonstracao_financeira",
        atributo_origem="cd_cvm",
        atributo_destino="cd_cvm",
        # Uma empresa tem muitas contas, em muitos exercícios: a junção
        # multiplica a linha de origem, e dizer isso é o que impede alguém
        # de contar empresa duas vezes achando que soma contas.
        relacionamento="um_para_muitos",
        descricao="A companhia e as contas que ela publicou. `cd_cvm` liga as "
                  "duas sem heurística de nome.",
    ),
]

AGENDAMENTOS = [
    ("cvm_dfp_anual", "cvm_dfp", "0 6 1 4 *"),
    ("cvm_dfp_empresa_anual", "cvm_dfp_empresa", "0 7 1 4 *"),
    ("cvm_itr_trimestral", "cvm_itr", "0 6 15 2,5,8,11 *"),
    ("cvm_cadastro_semanal", "cvm_cadastro", "0 5 * * 1"),
    # A composição da bolsa muda com IPO, fusão e saída de listagem —
    # semanal é frequente o bastante e barato (35 requisições).
    ("b3_listadas_semanal", "b3_listadas", "0 4 * * 1"),
    # O SGS publica com defasagem de um dia útil. Diário cobre câmbio e CDI;
    # Selic e IPCA mudam menos, e reingerir a mesma janela é no-op.
    *[(f"{chave}_diario", chave, "0 8 * * *") for chave, *_ in SERIES_BCB],
    # De terça a sábado, pedindo o pregão do dia anterior: cobre segunda a
    # sexta e nunca tenta um fim de semana. Dia sem pregão responde 404, e
    # feriado por isso vira execução falha — visível, que é o certo. Tratar
    # 404 como «sem pregão» esconderia o endereço quebrado no mesmo silêncio.
    ("b3_cotahist_diario", "b3_cotahist", "0 9 * * 2-6", "dia_anterior"),
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
            "fontes": [asdict(FONTE), asdict(FONTE_CADASTRO), asdict(FONTE_B3),
                       asdict(FONTE_BCB), asdict(FONTE_BRAPI),
                       asdict(FONTE_B3_SERIE)],
            "correlacoes": [asdict(c) for c in CORRELACOES],
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
    salvar_fonte(sink, FONTE_B3, autor="seed")
    salvar_fonte(sink, FONTE_BCB, autor="seed")
    salvar_fonte(sink, FONTE_BRAPI, autor="seed")
    salvar_fonte(sink, FONTE_B3_SERIE, autor="seed")
    for corr in CORRELACOES:
        salvar_correlacao(sink, corr, autor="seed")
    for d in datasets():
        salvar_dataset(sink, d, autor="seed")
    for chave, dataset_chave, cron, *resto in AGENDAMENTOS:
        salvar_agendamento(
            sink, chave, dataset_chave, cron,
            janela_padrao=resto[0] if resto else "ano_corrente", autor="seed",
        )
    aplicar_metricas(sink)

    sink.executar("DELETE FROM cfg_seed WHERE chave = 'cvm'")
    sink.executar(
        "INSERT INTO cfg_seed (chave, sha256) VALUES ('cvm', ?)", (digest,)
    )
    return True
