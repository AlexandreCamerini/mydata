-- =====================================================================
-- CVM — Demonstrações Financeiras (DFP + ITR)
-- Schema normalizado alvo para base própria (Postgres 13+).
-- Grão de fato_conta: 1 linha por conta contábil, por grupo de demonstração,
-- por empresa, por período, por versão de documento.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS cvm;

-- ---------------------------------------------------------------------
-- Dimensão de empresa (opcional; alimentada pelo cad_cia_aberta.csv).
-- Se não carregar o cadastro, denom_cia em fato_conta já resolve o básico.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm.dim_empresa (
    cd_cvm          INTEGER PRIMARY KEY,       -- código CVM (chave estável)
    cnpj            TEXT,
    denom_social    TEXT,
    denom_comercial TEXT,
    setor_atividade TEXT,
    situacao        TEXT,                       -- ATIVO / CANCELADA etc.
    controle_acionario TEXT,
    dt_ingest       TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Fato: contas contábeis (long/tidy — igual à CVM, porém tipado e enriquecido).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm.fato_conta (
    id              BIGSERIAL PRIMARY KEY,

    -- identificação da empresa/documento
    cd_cvm          INTEGER      NOT NULL,
    cnpj            TEXT,
    denom_cia       TEXT,

    -- tipo do documento e demonstração
    tipo_doc        TEXT         NOT NULL,      -- 'DFP' (anual) | 'ITR' (trimestral)
    grupo           TEXT         NOT NULL,      -- BPA|BPP|DRE|DFC_MI|DFC_MD|DVA|DMPL|DRA
    consolidado     BOOLEAN      NOT NULL,      -- TRUE = con | FALSE = ind (individual)

    -- períodos
    dt_refer        DATE         NOT NULL,      -- data de referência do documento
    dt_ini_exerc    DATE,                       -- nulo em BPA/BPP (contas de posição)
    dt_fim_exerc    DATE,
    ordem_exerc     TEXT         NOT NULL,      -- 'ÚLTIMO' | 'PENÚLTIMO'
    versao          INTEGER      NOT NULL,      -- versão do documento (reapresentação)

    -- conta
    cd_conta        TEXT         NOT NULL,      -- código hierárquico (1, 1.01, 3.01 ...)
    ds_conta        TEXT,
    st_conta_fixa   CHAR(1),                    -- 'S' = plano padronizado CVM | 'N' = custom
    moeda           TEXT,
    escala_moeda    TEXT,                       -- 'UNIDADE' | 'MIL'
    coluna_df       TEXT,

    -- valores
    vl_conta        NUMERIC,                    -- valor bruto como veio no arquivo
    vl_conta_norm   NUMERIC,                    -- normalizado p/ UNIDADE (aplica escala)

    -- metadados de ingestão / controle de reapresentação
    is_latest       BOOLEAN      NOT NULL DEFAULT TRUE,  -- maior versão p/ (cd_cvm, dt_refer, grupo, con/ind, tipo_doc)
    itr_acumulado   BOOLEAN      NOT NULL DEFAULT FALSE, -- TRUE p/ DRE/DFC de ITR (valor é YTD, não trimestre isolado)
    fonte_arquivo   TEXT,                        -- nome do zip/csv de origem
    dt_ingest       TIMESTAMPTZ  DEFAULT now(),

    -- chave natural única do fato (idempotência do load)
    CONSTRAINT uq_fato_conta UNIQUE
        (cd_cvm, tipo_doc, grupo, consolidado, dt_refer, versao, ordem_exerc, cd_conta, coluna_df)
);

-- Índices para os filtros mais frequentes (série temporal por empresa/conta)
CREATE INDEX IF NOT EXISTS ix_fato_cvm_refer   ON cvm.fato_conta (cd_cvm, dt_refer);
CREATE INDEX IF NOT EXISTS ix_fato_grupo       ON cvm.fato_conta (grupo, consolidado);
CREATE INDEX IF NOT EXISTS ix_fato_conta       ON cvm.fato_conta (cd_conta);
CREATE INDEX IF NOT EXISTS ix_fato_latest      ON cvm.fato_conta (is_latest) WHERE is_latest;

-- ---------------------------------------------------------------------
-- View de consumo: só o dado "correto" (última versão, período de referência,
-- consolidado). É daqui que a análise deve partir — nunca da fato crua.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW cvm.vw_conta_atual AS
SELECT *
FROM cvm.fato_conta
WHERE is_latest
  AND ordem_exerc = 'ÚLTIMO'
  AND consolidado = TRUE;

-- ---------------------------------------------------------------------
-- View: trimestre ISOLADO das contas de fluxo (DRE/DFC) do ITR.
-- O ITR publica valores ACUMULADOS no ano (YTD). Para obter o trimestre
-- isolado, subtrai-se o acumulado do período anterior do mesmo exercício.
-- Q1 isolado = Q1 acumulado. Demais = acumulado - acumulado_anterior.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW cvm.vw_itr_trimestre_isolado AS
WITH base AS (
    SELECT
        cd_cvm, cnpj, denom_cia, grupo, consolidado, cd_conta, ds_conta,
        dt_fim_exerc,
        EXTRACT(YEAR FROM dt_fim_exerc)::INT AS ano_exerc,
        vl_conta_norm
    FROM cvm.fato_conta
    WHERE tipo_doc = 'ITR'
      AND itr_acumulado                 -- só DRE/DFC (contas de fluxo)
      AND is_latest
      AND ordem_exerc = 'ÚLTIMO'
)
SELECT
    b.*,
    b.vl_conta_norm - COALESCE(
        LAG(b.vl_conta_norm) OVER (
            PARTITION BY b.cd_cvm, b.consolidado, b.cd_conta, b.ano_exerc
            ORDER BY b.dt_fim_exerc
        ), 0
    ) AS vl_trimestre_isolado
FROM base b;

-- ---------------------------------------------------------------------
-- Data quality checks mínimos (rode pós-load; devem retornar 0 linhas).
-- ---------------------------------------------------------------------
-- 1) Ativo total = Passivo+PL total (conta 1 vs conta 2/3) — tolerância p/ arredondamento
-- 2) Nenhum vl_conta_norm nulo com vl_conta preenchido
-- 3) is_latest único por chave de documento
