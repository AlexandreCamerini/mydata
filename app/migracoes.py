"""Migrações idempotentes, aplicáveis em Postgres e DuckDB.

Cada migração é uma lista de statements. `sql` roda nos dois dialetos após
substituição dos placeholders de tipo; `so_postgres` roda só no Postgres
(triggers, plpgsql — DuckDB não tem).

Versionamento da configuração: append-only. Cada alteração insere uma linha
nova com `versao + 1` e apaga o `vigente_chave` da anterior. A unicidade de
`vigente_chave` garante, no banco, no máximo um vigente por chave lógica —
truque portátil, já que DuckDB não tem índice parcial.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .sinks import Sink, render


@dataclass
class Migracao:
    nome: str
    sql: list[str] = field(default_factory=list)
    so_postgres: list[str] = field(default_factory=list)


# Colunas de versionamento repetidas nas tabelas de configuração.
_VERSAO = """
    chave         {TEXTO} NOT NULL,
    versao        {INT}   NOT NULL DEFAULT 1,
    vigente       {BOOL}  NOT NULL DEFAULT TRUE,
    vigente_chave {TEXTO} UNIQUE,
    criado_em     {TSTZ}  NOT NULL DEFAULT {AGORA},
    criado_por    {TEXTO},
    CHECK ((vigente AND vigente_chave IS NOT NULL)
        OR (NOT vigente AND vigente_chave IS NULL))
"""

MIGRACOES: list[Migracao] = [
    Migracao(
        nome="0001_controle",
        sql=[
            """CREATE TABLE IF NOT EXISTS schema_migracao (
                 nome        {TEXTO} PRIMARY KEY,
                 aplicada_em {TSTZ} NOT NULL DEFAULT {AGORA}
               )""",
        ],
    ),
    Migracao(
        nome="0002_plano_de_controle",
        sql=[
            "CREATE SEQUENCE IF NOT EXISTS seq_cfg_fonte START 1",
            "CREATE SEQUENCE IF NOT EXISTS seq_cfg_dataset START 1",
            "CREATE SEQUENCE IF NOT EXISTS seq_cfg_coluna START 1",
            "CREATE SEQUENCE IF NOT EXISTS seq_cfg_campo_calculado START 1",
            "CREATE SEQUENCE IF NOT EXISTS seq_cfg_regra_qualidade START 1",
            "CREATE SEQUENCE IF NOT EXISTS seq_cfg_agendamento START 1",
            "CREATE SEQUENCE IF NOT EXISTS seq_cfg_chave_api START 1",
            "CREATE SEQUENCE IF NOT EXISTS seq_log_execucao START 1",
            # ---------------- fonte: de onde vem ----------------
            """CREATE TABLE IF NOT EXISTS cfg_fonte (
                 id              {INT} PRIMARY KEY,
                 nome            {TEXTO} NOT NULL,
                 descricao       {TEXTO},
                 tipo_transporte {TEXTO} NOT NULL,
                 url_template    {TEXTO} NOT NULL,
                 encoding        {TEXTO} NOT NULL DEFAULT 'utf-8',
                 separador       {TEXTO} NOT NULL DEFAULT ';',
                 credencial_ref  {TEXTO},
                 ativo           {BOOL} NOT NULL DEFAULT TRUE,
               """ + _VERSAO + ")",
            # ---------------- dataset: o que extrair ----------------
            """CREATE TABLE IF NOT EXISTS cfg_dataset (
                 id              {INT} PRIMARY KEY,
                 fonte_chave     {TEXTO} NOT NULL,
                 nome            {TEXTO} NOT NULL,
                 descricao       {TEXTO},
                 padrao_arquivo  {TEXTO} NOT NULL,
                 tabela_destino  {TEXTO} NOT NULL,
                 chave_natural   {TEXTO} NOT NULL,
                 politica_versao {TEXTO} NOT NULL DEFAULT 'max_versao',
                 particao        {TEXTO} NOT NULL DEFAULT 'ano',
                 ativo           {BOOL} NOT NULL DEFAULT TRUE,
               """ + _VERSAO + ")",
            # -------- filhos do dataset: apontam para a VERSÃO do pai --------
            """CREATE TABLE IF NOT EXISTS cfg_coluna (
                 id           {INT} PRIMARY KEY,
                 dataset_id   {INT} NOT NULL,
                 nome_origem  {TEXTO} NOT NULL,
                 nome_destino {TEXTO} NOT NULL,
                 tipo         {TEXTO} NOT NULL,
                 formato      {TEXTO},
                 obrigatoria  {BOOL} NOT NULL DEFAULT FALSE,
                 ordem        {INT} NOT NULL DEFAULT 0
               )""",
            """CREATE TABLE IF NOT EXISTS cfg_campo_calculado (
                 id             {INT} PRIMARY KEY,
                 dataset_id     {INT} NOT NULL,
                 nome           {TEXTO} NOT NULL,
                 classe         {TEXTO} NOT NULL DEFAULT 'escalar',
                 expressao      {TEXTO} NOT NULL,
                 colunas_origem {TEXTO} NOT NULL,
                 tipo_retorno   {TEXTO} NOT NULL DEFAULT 'numeric',
                 particao_por   {TEXTO},
                 ordena_por     {TEXTO},
                 materializacao {TEXTO} NOT NULL DEFAULT 'coluna',
                 descricao      {TEXTO},
                 ativo          {BOOL} NOT NULL DEFAULT TRUE,
                 ordem          {INT} NOT NULL DEFAULT 0,
                 CHECK (classe IN ('escalar','janela'))
               )""",
            """CREATE TABLE IF NOT EXISTS cfg_regra_qualidade (
                 id            {INT} PRIMARY KEY,
                 dataset_id    {INT} NOT NULL,
                 nome          {TEXTO} NOT NULL,
                 expressao_sql {TEXTO} NOT NULL,
                 severidade    {TEXTO} NOT NULL DEFAULT 'alerta',
                 tolerancia    {NUM}  NOT NULL DEFAULT 0,
                 descricao     {TEXTO},
                 ativo         {BOOL} NOT NULL DEFAULT TRUE,
                 CHECK (severidade IN ('informa','alerta','bloqueia'))
               )""",
            # ---------------- agendamento ----------------
            """CREATE TABLE IF NOT EXISTS cfg_agendamento (
                 id             {INT} PRIMARY KEY,
                 dataset_chave  {TEXTO} NOT NULL,
                 cron           {TEXTO} NOT NULL,
                 timezone       {TEXTO} NOT NULL DEFAULT 'America/Sao_Paulo',
                 janela_padrao  {TEXTO} NOT NULL DEFAULT 'ano_corrente',
                 ativo          {BOOL} NOT NULL DEFAULT TRUE,
               """ + _VERSAO + ")",
            # ---------------- chaves de API (estado, não config) -------------
            """CREATE TABLE IF NOT EXISTS cfg_chave_api (
                 id            {INT} PRIMARY KEY,
                 consumidor    {TEXTO} NOT NULL,
                 prefixo       {TEXTO} NOT NULL UNIQUE,
                 hash_chave    {TEXTO} NOT NULL,
                 quota_minuto  {INT} NOT NULL DEFAULT 120,
                 quota_dia     {INT} NOT NULL DEFAULT 50000,
                 escopos       {TEXTO} NOT NULL DEFAULT 'leitura',
                 criada_em     {TSTZ} NOT NULL DEFAULT {AGORA},
                 revogada_em   {TSTZ}
               )""",
            """CREATE TABLE IF NOT EXISTS uso_chave_api (
                 prefixo   {TEXTO} NOT NULL,
                 janela    {TEXTO} NOT NULL,
                 balde     {TEXTO} NOT NULL,
                 chamadas  {INT} NOT NULL DEFAULT 0,
                 PRIMARY KEY (prefixo, janela, balde)
               )""",
            # ---------------- log de execução ----------------
            """CREATE TABLE IF NOT EXISTS log_execucao (
                 id             {INT} PRIMARY KEY,
                 dataset_chave  {TEXTO} NOT NULL,
                 dataset_id     {INT},
                 janela         {TEXTO} NOT NULL,
                 status         {TEXTO} NOT NULL,
                 trigger_tipo   {TEXTO} NOT NULL DEFAULT 'manual',
                 cfg_snapshot   {JSON},
                 iniciado_em    {TSTZ} NOT NULL DEFAULT {AGORA},
                 terminado_em   {TSTZ},
                 capturas       {INT} NOT NULL DEFAULT 0,
                 linhas_silver  {INT} NOT NULL DEFAULT 0,
                 delta_linhas   {INT},
                 publicacao     {INT},
                 erro           {TEXTO},
                 CHECK (status IN ('pendente','baixando','capturado','carregando',
                                   'recomputando','validando','publicado',
                                   'bloqueada','falha'))
               )""",
            "CREATE INDEX IF NOT EXISTS ix_log_dataset ON log_execucao (dataset_chave, iniciado_em)",
        ],
        so_postgres=[
            # Integridade referencial completa só no Postgres: o DuckDB recusa
            # UPDATE em linha referenciada por FK, o que quebraria o
            # versionamento (aposentar a versão vigente é um UPDATE no pai).
            # Em dev a integridade é garantida pelo repositório.
            """ALTER TABLE cfg_coluna ADD CONSTRAINT fk_cfg_coluna_dataset
                 FOREIGN KEY (dataset_id) REFERENCES cfg_dataset(id)""",
            """ALTER TABLE cfg_campo_calculado ADD CONSTRAINT fk_cfg_calc_dataset
                 FOREIGN KEY (dataset_id) REFERENCES cfg_dataset(id)""",
            """ALTER TABLE cfg_regra_qualidade ADD CONSTRAINT fk_cfg_regra_dataset
                 FOREIGN KEY (dataset_id) REFERENCES cfg_dataset(id)""",
        ],
    ),
    Migracao(
        nome="0003_bronze",
        sql=[
            "CREATE SEQUENCE IF NOT EXISTS seq_bronze_captura START 1",
            """CREATE TABLE IF NOT EXISTS bronze_captura (
                 id            {INT} PRIMARY KEY,
                 dataset_chave {TEXTO} NOT NULL,
                 janela        {TEXTO} NOT NULL,
                 url           {TEXTO} NOT NULL,
                 nome_arquivo  {TEXTO} NOT NULL,
                 sha256        {TEXTO} NOT NULL,
                 tamanho_bytes {INT} NOT NULL,
                 capturado_em  {TSTZ} NOT NULL DEFAULT {AGORA},
                 payload       {BINARIO} NOT NULL,
                 UNIQUE (dataset_chave, sha256)
               )""",
            "CREATE INDEX IF NOT EXISTS ix_bronze_janela ON bronze_captura (dataset_chave, janela)",
        ],
        so_postgres=[
            # ZIP já vem comprimido: não vale a pena o Postgres tentar de novo.
            "ALTER TABLE bronze_captura ALTER COLUMN payload SET STORAGE EXTERNAL",
            """CREATE OR REPLACE FUNCTION bronze_imutavel() RETURNS trigger AS $$
               BEGIN
                 RAISE EXCEPTION 'bronze_captura é imutável: % na captura %',
                   TG_OP, OLD.id;
               END $$ LANGUAGE plpgsql""",
            "DROP TRIGGER IF EXISTS trg_bronze_imutavel ON bronze_captura",
            """CREATE TRIGGER trg_bronze_imutavel
                 BEFORE UPDATE OR DELETE ON bronze_captura
                 FOR EACH ROW EXECUTE FUNCTION bronze_imutavel()""",
        ],
    ),
    Migracao(
        nome="0004_silver_cvm",
        sql=[
            """CREATE TABLE IF NOT EXISTS fato_conta (
                 captura_id     {INT} NOT NULL,
                 fonte_arquivo  {TEXTO} NOT NULL,
                 cd_cvm         {INT},
                 cnpj           {TEXTO},
                 denom_cia      {TEXTO},
                 tipo_doc       {TEXTO},
                 grupo          {TEXTO},
                 consolidado    {BOOL},
                 dt_refer       {TEXTO},
                 dt_ini_exerc   {TEXTO},
                 dt_fim_exerc   {TEXTO},
                 ordem_exerc    {TEXTO},
                 versao         {INT},
                 cd_conta       {TEXTO},
                 ds_conta       {TEXTO},
                 st_conta_fixa  {TEXTO},
                 moeda          {TEXTO},
                 escala_moeda   {TEXTO},
                 coluna_df      {TEXTO},
                 vl_conta_txt   {TEXTO},
                 vl_conta       {NUM},
                 vl_conta_norm  {NUM},
                 is_latest      {BOOL},
                 itr_acumulado  {BOOL},
                 carregado_em   {TSTZ} NOT NULL DEFAULT {AGORA}
               )""",
            """CREATE UNIQUE INDEX IF NOT EXISTS ux_fato_conta_natural ON fato_conta
                 (cd_cvm, tipo_doc, dt_refer, grupo, consolidado, cd_conta,
                  ordem_exerc, versao)""",
            "CREATE INDEX IF NOT EXISTS ix_fato_cvm_refer ON fato_conta (cd_cvm, dt_refer)",
            "CREATE INDEX IF NOT EXISTS ix_fato_conta_cd ON fato_conta (cd_conta)",
            """CREATE TABLE IF NOT EXISTS dim_empresa (
                 captura_id     {INT} NOT NULL,
                 fonte_arquivo  {TEXTO} NOT NULL,
                 cd_cvm         {INT},
                 cnpj           {TEXTO},
                 denom_social   {TEXTO},
                 denom_comerc   {TEXTO},
                 setor_atividade {TEXTO},
                 situacao       {TEXTO},
                 controle_acionario {TEXTO},
                 uf             {TEXTO},
                 municipio      {TEXTO},
                 dt_registro    {TEXTO},
                 carregado_em   {TSTZ} NOT NULL DEFAULT {AGORA}
               )""",
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_empresa_natural ON dim_empresa (cd_cvm)",
            """CREATE TABLE IF NOT EXISTS publicacao (
                 versao      {INT} PRIMARY KEY,
                 publicado_em {TSTZ} NOT NULL DEFAULT {AGORA},
                 execucao_id {INT},
                 observacao  {TEXTO}
               )""",
        ],
    ),
    Migracao(
        # Sem isto, o gate de qualidade não protege nada: gold é view sobre
        # silver, então linha carregada e reprovada já apareceria para o
        # consumidor. O rótulo marca quais linhas foram promovidas; gold só
        # enxerga linha rotulada. Bloqueio deixa a linha sem rótulo — invisível.
        nome="0005_rotulo_de_publicacao",
        sql=[
            "ALTER TABLE fato_conta ADD COLUMN publicado_em_versao {INT}",
            "ALTER TABLE dim_empresa ADD COLUMN publicado_em_versao {INT}",
            """CREATE INDEX IF NOT EXISTS ix_fato_publicado
                 ON fato_conta (publicado_em_versao)""",
        ],
    ),
    Migracao(
        # Indicadores fundamentalistas como configuração, não como código.
        # A fórmula usa `c('1.01')` para referenciar conta contábil; o motor
        # expande para um pivô sobre gold_demonstracoes.
        nome="0006_metricas",
        sql=[
            "CREATE SEQUENCE IF NOT EXISTS seq_cfg_metrica START 1",
            """CREATE TABLE IF NOT EXISTS cfg_metrica (
                 id            {INT} PRIMARY KEY,
                 nome          {TEXTO} NOT NULL,
                 formula       {TEXTO} NOT NULL,
                 unidade       {TEXTO} NOT NULL DEFAULT 'razao',
                 descricao     {TEXTO},
                 ativo         {BOOL} NOT NULL DEFAULT TRUE,
               """ + _VERSAO + ")",
        ],
    ),
    Migracao(
        # A classe de informação é o que faltava acima do dataset. Enquanto a
        # tabela física nasce de um CREATE TABLE escrito à mão, cadastrar uma
        # classe nova pela interface exige deploy — o oposto do produto.
        #
        # Esta migração é aditiva de propósito: as tabelas entram vazias e o
        # motor continua lendo `tabela_destino`. A classe começa como espelho
        # verificado do que já existe; só depois assume.
        nome="0007_classe_de_informacao",
        sql=[
            "CREATE SEQUENCE IF NOT EXISTS seq_cfg_classe START 1",
            "CREATE SEQUENCE IF NOT EXISTS seq_cfg_atributo START 1",
            """CREATE TABLE IF NOT EXISTS cfg_classe (
                 id               {INT} PRIMARY KEY,
                 nome             {TEXTO} NOT NULL,
                 descricao        {TEXTO},
                 tabela           {TEXTO} NOT NULL,
                 chave_identidade {TEXTO} NOT NULL,
                 indices          {TEXTO},
                 sla_horas        {INT},
                 ativo            {BOOL} NOT NULL DEFAULT TRUE,
               """ + _VERSAO + ")",
            """CREATE TABLE IF NOT EXISTS cfg_atributo (
                 id           {INT} PRIMARY KEY,
                 classe_id    {INT} NOT NULL,
                 nome         {TEXTO} NOT NULL,
                 tipo         {TEXTO} NOT NULL DEFAULT 'texto',
                 origem       {TEXTO} NOT NULL DEFAULT 'fonte',
                 obrigatorio  {BOOL} NOT NULL DEFAULT FALSE,
                 guarda_texto {BOOL} NOT NULL DEFAULT FALSE,
                 unidade      {TEXTO},
                 descricao    {TEXTO},
                 ordem        {INT} NOT NULL DEFAULT 0,
                 CHECK (origem IN ('fonte','calculado'))
               )""",
            # Anulável: dataset antigo segue funcionando enquanto a classe é só
            # espelho. A obrigatoriedade chega na Etapa 3, com a virada.
            "ALTER TABLE cfg_dataset ADD COLUMN classe_chave {TEXTO}",
        ],
        so_postgres=[
            """ALTER TABLE cfg_atributo ADD CONSTRAINT fk_cfg_atributo_classe
                 FOREIGN KEY (classe_id) REFERENCES cfg_classe(id)""",
        ],
    ),
]

# Tabelas silver que participam do ciclo de publicação. A partir da Etapa 3
# quem responde é `publicacao.tabelas_publicaveis`, lendo `cfg_classe`; esta
# constante permanece como piso para banco ainda sem classe cadastrada.
TABELAS_SILVER = ("fato_conta", "dim_empresa")


def aplicar(sink: Sink, ate: str | None = None) -> list[str]:
    """Aplica as migrações pendentes. Idempotente: rodar de novo é no-op."""
    sink.executar(render(MIGRACOES[0].sql[0], sink.dialeto))
    aplicadas = {
        linha["nome"] for linha in sink.consultar("SELECT nome FROM schema_migracao")
    }
    novas: list[str] = []
    for mig in MIGRACOES:
        if mig.nome in aplicadas:
            continue
        for stmt in mig.sql:
            sink.executar(render(stmt, sink.dialeto))
        if sink.dialeto == "postgres":
            for stmt in mig.so_postgres:
                sink.executar(render(stmt, sink.dialeto))
        sink.executar("INSERT INTO schema_migracao (nome) VALUES (?)", (mig.nome,))
        novas.append(mig.nome)
        if ate and mig.nome == ate:
            break
    return novas
