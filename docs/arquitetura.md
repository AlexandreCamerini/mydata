# Portal de Dados — definição do sistema e arquitetura proposta

**Status:** implementado (fases 1–5, etapas 0–7) · **Versão:** 2.0 · **Data:** 2026-07-30
**Escopo deste documento:** o que o sistema é, que garantias oferece, como é
construído e por quê. Decisões com alternativa descartada estão registradas em
[Decisões arquiteturais](#11-decisões-arquiteturais); o que ainda não foi
decidido está em [Questões em aberto](#14-questões-em-aberto). O plano de
execução por fases vive em
[prompt-portal-dados-otimizado.md](../prompt-portal-dados-otimizado.md).

---

## 1. Definição do sistema

### 1.1 Problema

Análise fundamentalista de empresas da B3 depende do dado oficial que a CVM
publica. Esse dado é distribuído como ZIPs anuais de CSVs — não há API — e é
**padronizado, não normalizado**: chega consistente em formato e ambíguo em
semântica. Sete armadilhas (§ [Apêndice A](#apêndice-a--as-sete-armadilhas-do-dado-da-cvm))
fazem com que uma soma ingênua produza número errado sem nenhum erro visível.

Existem APIs de terceiros (brapi, dadosdemercado) que resolvem a ergonomia, mas
nenhuma delas é o dado auditado. E todas cobram, ou limitam, ou somem.

### 1.2 O que o sistema é

Um **portal de API de dados de mercado** com plano de controle próprio: a
recepção, o tratamento e a carga de cada fonte são configurados por interface,
não por código. Novas fontes entram como configuração; a CVM é apenas a
primeira delas.

Duas metades, deliberadamente separadas:

| | Plano de controle | Plano de dados |
|---|---|---|
| Responde | "como esse dado deve ser recebido e tratado?" | "que dado eu tenho e o que ele vale?" |
| Escrito por | operador, pela UI | motor de ingestão |
| Tabelas | `cfg_*`, `log_execucao` | `bronze_captura`, silver, gold |
| Muda | raramente, e sempre versionado | a cada execução |

### 1.3 Consumidores

| Consumidor | Como acessa | O que precisa |
|---|---|---|
| BOLSIA (análise fundamentalista) | `GET /v1/**` com chave de API | série histórica por empresa/conta, indicadores derivados, proveniência |
| Operador do portal | UI `/admin` | configurar fontes, campos calculados, regras e agendamento; ver execuções |
| Auditoria (o próprio Alex, depois) | consulta direta ao banco | reconstruir qualquer número até o arquivo oficial que o originou |

### 1.4 Princípios

1. **O dado oficial é intocável; o derivado é descartável.** Só o arquivo que a
   CVM publicou não pode ser reconstruído. Tudo o mais se recomputa.
2. **Configuração, não código.** Adicionar uma fonte, uma coluna ou um
   indicador não deve exigir deploy.
3. **Todo número tem endereço.** Qualquer valor devolvido pela API aponta para
   a captura que o originou e para a versão de configuração que o produziu.
4. **Custo zero por padrão.** Nada além do que o plano do Railway já inclui.
   Isso é restrição de arquitetura, não meta de gestão.
5. **Errado não publica.** Regra de qualidade bloqueante impede a promoção;
   o consumidor continua vendo a última versão boa.

### 1.5 Fora de escopo

Cotação intradiária e dados de pregão · terceiros como fonte de verdade (cabem
como atalho validado contra a CVM) · camada dbt · faturamento · execução do
deploy.

---

## 2. Visão de arquitetura

```mermaid
flowchart TB
    subgraph externo[Fontes externas]
        CVM[(CVM Dados Abertos<br/>ZIP/CSV latin-1)]
    end

    subgraph railway[Railway — projeto único]
        subgraph web[Serviço web · FastAPI]
            API[API pública /v1]
            ADMIN[UI /admin<br/>build estático]
            META[API de configuração /admin/api]
        end
        CRON[Cron job<br/>cvm-ingest]
        subgraph db[(Postgres — plano incluído)]
            CFG[Plano de controle<br/>cfg_*, log_execucao]
            BRONZE[bronze_captura<br/>imutável]
            SILVER[silver<br/>fato_conta, dim_empresa]
            GOLD[gold<br/>views publicadas]
        end
    end

    BOLSIA[BOLSIA] -->|chave de API| API
    OP[Operador] --> ADMIN
    ADMIN --> META --> CFG
    CRON -->|lê config| CFG
    CVM -->|download| CRON
    CRON -->|grava intacto| BRONZE
    BRONZE -->|parse + tipagem| SILVER
    SILVER -->|campos calculados| GOLD
    CRON -->|registra| LOG[log_execucao]
    API --> GOLD
```

**Um serviço web, um cron job, um banco.** Essa é a topologia inteira, e é uma
consequência direta do princípio 4: cada serviço adicional no Railway consome
recurso do plano. O front não tem servidor próprio — é build estático servido
pelo FastAPI. A ingestão não é thread dentro da API — é processo curto disparado
por cron, que sobe, trabalha e morre.

### 2.1 Camadas do dado

```mermaid
flowchart LR
    A[Arquivo oficial CVM] -->|SHA-256 + URL + timestamp| B[BRONZE<br/>imutável]
    B -->|parse, tipagem, encoding| S[SILVER<br/>1 linha = 1 registro da fonte]
    S -->|catálogo declarativo| C[CALCULADOS<br/>com linhagem]
    S --> G[GOLD<br/>views publicadas]
    C --> G
    G -->|API| Consumidor
    B -.->|recomputar| S
```

| Camada | Conteúdo | Mutabilidade | Reconstrutível? |
|---|---|---|---|
| **Bronze** | o ZIP/CSV como a CVM publicou, byte a byte, com hash, URL e `capturado_em` | **imutável** — nova captura é registro novo, nunca sobrescrita | ❌ **não** — é a única cópia |
| **Silver** | uma linha por registro da fonte, colunas originais tipadas | reconstruída a cada carga | ✅ do bronze |
| **Calculados** | derivados declarados em catálogo, com colunas de origem | recomputados sob demanda | ✅ do silver |
| **Gold** | views de consumo, já filtradas e corretas | republicadas por swap de versão | ✅ do silver + calculados |

**Tipagem não é transformação.** `"1.234,50"` → `1234.50` muda representação,
não valor, e a string original permanece acessível na mesma linha. A distinção
importa porque é ela que reconcilia "nenhum dado será transformado" com
"teremos campos calculados": o dado oficial não muda; o que o portal deriva
mora ao lado, identificado como derivado.

**Recomputar do bronze é rotina, não emergência.** É a forma padrão de corrigir
carga errada, mudança de regra ou bug de parsing. Corolário verificável: se
recomputar tudo não reproduzir o estado do banco, existe um bug — alguma coisa
entrou por fora do pipeline. Esse é um teste de aceite, não uma frase de
efeito.

---

## 3. Plano de controle — modelo de configuração

Toda tabela `cfg_*` é **append-only e versionada**: uma alteração insere uma
nova linha com `versao + 1` e marca a anterior como `vigente = false`. O motivo
não é auditoria genérica — é que uma reingestão de 2019 precisa saber sob qual
configuração o dado de 2019 foi carregado, sob pena de produzir um resultado
diferente do que a API já serviu.

### 3.1 `cfg_fonte` — de onde vem

| Coluna | Tipo | Nota |
|---|---|---|
| `id`, `versao`, `vigente` | — | chave lógica + versionamento |
| `nome` | text | `cvm_dados_abertos` |
| `tipo_transporte` | enum | `http_zip`, `http_csv`, `http_json` |
| `url_template` | text | `.../{DFP\|ITR}/DADOS/{tipo}_cia_aberta_{ano}.zip` |
| `encoding` | text | `latin-1` — errar aqui quebra `DENOM_CIA` e `DS_CONTA` |
| `separador` | char | `;` |
| `credencial_ref` | text | nome da variável de ambiente, nunca o segredo |

### 3.2 `cfg_dataset` — o que extrair de dentro

| Coluna | Nota |
|---|---|
| `fonte_id` | FK |
| `padrao_arquivo` | regex sobre o nome do CSV dentro do ZIP |
| `tabela_destino` | tabela silver |
| `chave_natural` | array de colunas — **base da idempotência** |
| `politica_versao` | `max_versao` (CVM), `append`, `upsert` |
| `particao` | `ano`, para janelar carga e recomputação |

### 3.3 `cfg_coluna` — contrato de schema

`nome_origem` → `nome_destino`, `tipo`, `formato` (`decimal_ptbr`, `date_iso`),
`obrigatoria`. É também o detector de mudança de layout: coluna obrigatória
ausente na captura falha a carga em vez de gravar nulo silencioso.

### 3.4 `cfg_campo_calculado` — o catálogo de derivadas

| Coluna | Nota |
|---|---|
| `nome` | `vl_conta_norm`, `is_latest`, `liquidez_corrente` |
| `classe` | `escalar` (linha a linha) ou `janela` (precisa de partição/ordenação) |
| `expressao` | SQL restrito (§ [4.3](#43-linguagem-de-expressão)) |
| `colunas_origem` | array — **validado contra `cfg_coluna`**; sem isso não salva |
| `particao_por` / `ordena_por` | só para `classe = janela` |
| `materializacao` | `coluna` (persistida em silver) ou `view` (calculada na leitura) |

A separação `escalar` / `janela` não é decorativa: `vl_conta_norm` é
`vl_conta * fator(escala_moeda)` — escalar. `is_latest` é
`versao = max(versao) over (partition by cd_cvm, tipo_doc, dt_refer)` — janela,
e **de partição global**, o que tem consequência operacional descrita em
§ [4.4](#44-recomputação).

### 3.5 `cfg_regra_qualidade`, `cfg_agendamento`, `cfg_chave_api`, `log_execucao`

| Tabela | Campos que importam |
|---|---|
| `cfg_regra_qualidade` | `expressao_sql` (deve retornar 0 linhas), `severidade` ∈ {`informa`, `alerta`, `bloqueia`}, `tolerancia` |
| `cfg_agendamento` | `cron`, `timezone` (`America/Sao_Paulo`), `janela_padrao` |
| `cfg_chave_api` | `consumidor`, `hash_chave`, `prefixo`, `quota_minuto`, `quota_dia`, `revogada_em` |
| `log_execucao` | `janela`, `status`, `trigger` (`cron`/`manual`/`replay`), `cfg_snapshot` (JSONB com as versões de config usadas), contagens e delta de linhas, `erro` |

`cfg_snapshot` é o que torna uma execução reproduzível meses depois: a config
mudou, mas o log sabe qual estava vigente.

---

## 4. Motor de ingestão

### 4.1 Ciclo

```mermaid
stateDiagram-v2
    [*] --> pendente
    pendente --> baixando: cron / manual / replay
    baixando --> capturado: grava bronze (hash, URL, timestamp)
    baixando --> falha: rede indisponível
    capturado --> carregando: parse + tipagem por cfg_coluna
    carregando --> falha: coluna obrigatória ausente
    carregando --> recomputando: silver carregado (idempotente)
    recomputando --> validando: campos calculados aplicados
    validando --> bloqueada: regra severidade=bloqueia falhou
    validando --> publicado: swap da versão gold
    bloqueada --> [*]: versão anterior segue no ar
    publicado --> [*]
    falha --> [*]
```

O passo `capturado` é o ponto de não-retorno do dado oficial: dali em diante,
qualquer erro é recuperável sem rede.

### 4.2 Idempotência

Carga por chave natural declarada em `cfg_dataset`. Para a CVM:
`(cd_cvm, tipo_doc, dt_refer, grupo, consolidado, cd_conta, ordem_exerc, versao)`.
Reexecutar a mesma janela substitui as linhas dessa chave; não acumula. Isso é
o que permite `replay` de um ano inteiro como operação segura de rotina.

### 4.3 Linguagem de expressão

Campos calculados e regras de qualidade são **SQL restrito**, avaliado pelo
banco: expressões escalares, funções de janela, agregações, `CASE`. Sem
subconsulta a tabela não declarada, sem DDL, sem função definida pelo usuário.

Três razões: recomputabilidade (o mesmo texto roda de novo e dá o mesmo
resultado), portabilidade entre Postgres e DuckDB, e superfície de ataque —
o campo é editável pela UI, então executar Python arbitrário ali seria RCE com
formulário.

### 4.4 Recomputação

`recomputar(janela)` dropa silver, calculados e gold da janela e reconstrói do
bronze, sem rede.

**Armadilha conhecida:** `is_latest` é de partição global por
`(cd_cvm, tipo_doc, dt_refer)`. Reingerir 2019 pode conter uma reapresentação
que rebaixa um documento já marcado como vigente. Recomputar só a janela deixa
o flag errado em ano que não foi tocado. Portanto: **campo calculado de classe
`janela` com partição que cruza janelas dispara recomputação global do campo**,
não da janela. O catálogo precisa saber disso, e é por isso que
`particao_por` é coluna e não comentário.

### 4.5 Publicação em gold

Duas metades, e a implementação mostrou que **só a segunda não basta**.

1. **Rótulo por linha.** Linha carregada nasce sem `publicado_em_versao`; gold
   só enxerga linha rotulada. Publicar rotula as pendentes.
2. **Ponteiro versionado.** Cada publicação cria `*_v{n}` e move o alias que a
   API lê. Reverter é mover o ponteiro de volta.

O ponteiro sozinho versiona a *definição* da view, não o dado que ela lê — com
gold sendo view sobre silver, uma carga reprovada apareceria para o consumidor
no mesmo instante em que fosse carregada. O rótulo é o que faz o gate valer;
o teste `test_versao_anterior_continua_no_ar_apos_bloqueio` existe para isso.
Bloqueio também descarta de silver as linhas sem rótulo da execução — dado já
publicado não é tocado.

Consequências:

- Regra bloqueante barra a promoção; o consumidor continua na versão íntegra.
- Rollback é mover o ponteiro de volta.
- `versao_publicacao` vira `ETag` na API (§ [6.4](#64-cache-e-custo)).

**Limite conhecido:** linha já publicada sobrescrita por upsert com valor
diferente muda em gold sem passar pelo gate — só ocorreria se a CVM
republicasse a mesma chave natural com outro valor. E `recomputar` de uma
janela cuja carga seja depois reprovada deixa a janela sem dado publicado até
a correção, porque as linhas antigas já foram removidas. A solução completa
para os dois é área de staging antes do merge — registrada como backlog.

---

## 5. Modelo de dados físico

```mermaid
erDiagram
    bronze_captura ||--o{ fato_conta : origina
    dim_empresa ||--o{ fato_conta : identifica
    cfg_dataset ||--o{ log_execucao : executa
    cfg_dataset ||--o{ cfg_coluna : declara
    cfg_dataset ||--o{ cfg_campo_calculado : deriva
    cfg_fonte ||--o{ cfg_dataset : contem
```

| Tabela | Grão | Origem |
|---|---|---|
| `bronze_captura` | 1 arquivo baixado | download — [ADR-10](#adr-10--bronze-em-tabela-não-em-volume) |
| `fato_conta` | 1 conta contábil, por grupo, empresa, período e versão de documento | já existe em [schema_postgres.sql](../src/cvm_financas/sql/schema_postgres.sql) |
| `dim_empresa` | 1 companhia aberta | `cad_cia_aberta.csv` — **hoje fora do loop** |
| `gold.demonstracoes` | view: `is_latest` ∧ `ordem_exerc = 'ÚLTIMO'` ∧ `consolidado` fixo | derivada |
| `gold.itr_trimestre_isolado` | view: acumulado − acumulado anterior do mesmo exercício | derivada |

`fato_conta` carrega, lado a lado: `vl_conta` (oficial), `vl_conta_norm`
(calculado), `escala_moeda`, `versao`, `ordem_exerc`, `st_conta_fixa`,
`is_latest`, `itr_acumulado`, `fonte_arquivo`. Nada do oficial é substituído
pelo derivado.

### 5.1 `bronze_captura`

```sql
CREATE TABLE bronze_captura (
  id            bigserial PRIMARY KEY,
  dataset_id    bigint NOT NULL REFERENCES cfg_dataset(id),
  url           text   NOT NULL,
  nome_arquivo  text   NOT NULL,
  sha256        char(64) NOT NULL,
  tamanho_bytes bigint NOT NULL,
  capturado_em  timestamptz NOT NULL DEFAULT now(),
  payload       bytea  NOT NULL,
  UNIQUE (dataset_id, sha256)          -- recaptura idêntica não duplica
);

-- ZIP já vem comprimido: poupa o Postgres de tentar comprimir de novo.
ALTER TABLE bronze_captura ALTER COLUMN payload SET STORAGE EXTERNAL;

-- Imutabilidade deixa de ser promessa e vira constraint.
CREATE FUNCTION bronze_imutavel() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'bronze_captura é imutável: % em captura %', TG_OP, OLD.id;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_bronze_imutavel
  BEFORE UPDATE OR DELETE ON bronze_captura
  FOR EACH ROW EXECUTE FUNCTION bronze_imutavel();
```

O `UNIQUE (dataset_id, sha256)` faz recaptura de conteúdo idêntico ser no-op —
necessário porque o cron rebaixa o mesmo ano com frequência e só algumas
capturas trazem reapresentação nova.

**Por que guardar o binário, e não só o hash e a URL:** a URL da CVM não é
arquivo, é endereço mutável. `dfp_cia_aberta_2023.zip` é regerado quando uma
empresa reapresenta, então rebaixar amanhã não reproduz a captura de hoje. É
isso que torna o bronze irreconstituível.

**Retenção:** todas as capturas dos últimos 24 meses, mais a última de cada
`(dataset, ano)` para o histórico. A purga exige `ALTER TABLE ... DISABLE
TRIGGER` explícito — apagar bronze é ato deliberado, nunca `DELETE` distraído.

---

## 6. API pública

### 6.1 Contrato

```
GET /v1/empresas?q=&setor=&cursor=
GET /v1/empresas/{cd_cvm}
GET /v1/empresas/{cd_cvm}/demonstracoes?tipo=DFP|ITR&grupo=&de=&ate=&consolidado=
GET /v1/empresas/{cd_cvm}/metricas?nomes=liquidez_corrente,margem_liquida
GET /v1/meta/datasets
GET /v1/meta/campos-calculados
GET /health
```

Versionamento no path. `/v1` só sofre adição de campo; remoção ou mudança de
semântica abre `/v2`.

### 6.2 Proveniência

Toda resposta de dado carrega `fonte`, `dt_captura`, `versao_documento` e
`calculado_em`. Não é metadado opcional: é o que separa este portal de um
scraper, e o que permite ao consumidor saber que um número mudou porque a
empresa reapresentou, não porque o portal errou.

### 6.3 Autenticação e quota

Chave de alta entropia (32 bytes), formato `pd_{prefixo}_{segredo}`. Armazena-se
`sha256(segredo)` e o `prefixo` em claro, para lookup em índice. **Não** se usa
bcrypt/argon2 aqui: são desenhados para segredos de baixa entropia escolhidos
por humanos; para chave aleatória de 256 bits, SHA-256 é seguro e não custa
dezenas de milissegundos por request — o que, num serviço com CPU limitada,
seria a maior fatia do tempo de resposta.

Quota por minuto e por dia, contadas por chave. Estouro → `429` com
`Retry-After`.

### 6.4 Cache e custo

Gold só muda quando uma publicação acontece. Logo: `ETag` derivado de
`versao_publicacao` + parâmetros da query, `Cache-Control` longo,
`304 Not Modified` no revalidate. É a alavanca de custo mais barata do sistema —
o BOLSIA repetindo a mesma consulta não gasta CPU.

### 6.5 Erros

Shape único: `{ "erro": { "codigo", "mensagem", "detalhe" } }`. Códigos
estáveis (`chave_invalida`, `quota_excedida`, `empresa_nao_encontrada`,
`parametro_invalido`), porque cliente que faz parsing de mensagem quebra
quando o texto melhora.

---

## 7. Plano de controle — interface

Sete telas, servidas em `/admin`: **Fontes**, **Datasets**, **Campos
calculados**, **Qualidade**, **Execuções**, **Chaves de API**, **Catálogo**.

Padrões que valem como critério de aceite, não como intenção: navegação por
teclado em todos os formulários; foco visível; rótulo associado a cada campo;
erro descrito em texto ao lado do campo que o causou; estado de carregamento e
estado vazio em cada listagem; ação destrutiva com confirmação que nomeia o
objeto; contraste mínimo AA.

Duas telas carregam responsabilidade de correção, não só de cadastro:

- **Campos calculados** valida contra `cfg_coluna` no momento de salvar e
  mostra preview sobre amostra real. Campo que referencia coluna inexistente é
  rejeitado com mensagem que nomeia a coluna.
- **Execuções** oferece replay de janela — a interface da operação de correção
  padrão do sistema.

---

## 8. Infraestrutura — Railway

| Componente | Forma |
|---|---|
| Serviço web | FastAPI (uvicorn), bind em `0.0.0.0:$PORT`, serve API + estático |
| Cron | comando da CLI, processo curto, mesma imagem |
| Banco | Postgres do Railway, via `DATABASE_URL` injetada |
| Config | `railway.json` + `.env.example` versionados |
| Healthcheck | `GET /health`, responde sem tocar no banco |

**O filesystem do container é efêmero.** Gravar bronze em disco local do
serviço web perde o dado oficial no primeiro redeploy — exatamente o único dado
que não se reconstrói. Por isso o bronze mora em tabela, não em volume nem em
disco: ver [ADR-10](#adr-10--bronze-em-tabela-não-em-volume). Nenhum serviço
depende de estado em disco; o container pode ser destruído a qualquer momento.

**Sobre o custo:** o Railway não tem um tier de banco gratuito separado — o
Postgres é serviço cobrado por uso, coberto pelos créditos que o plano já
inclui. Na prática, sem gasto adicional; na prática também, não ilimitado. Daí
o serviço único, o cache agressivo e a política de retenção de bronze.

Em desenvolvimento local, sem `DATABASE_URL`, o sink é DuckDB em arquivo —
zero setup, mesma modelagem, mesmos testes.

---

## 9. Segurança

| Superfície | Tratamento |
|---|---|
| Chaves de API | hash em repouso, prefixo indexado, revogação imediata |
| Expressões editáveis pela UI | SQL restrito, sem DDL, sem UDF, sem tabela não declarada — o campo é entrada de usuário |
| Credenciais de fonte | só o nome da variável de ambiente vai para o banco |
| Dado oficial | hook `PreToolUse` bloqueia escrita em `bronze/` e DDL contra tabelas de captura, inclusive durante desenvolvimento assistido |
| `/admin` | autenticado; separado da API pública |
| LGPD | dado de companhia aberta é público; não há dado pessoal de terceiros no escopo atual. Se um dataset futuro trouxer administradores nomeados, reavaliar |

---

## 10. Observabilidade

`log_execucao` é a fonte primária: status, duração, contagens por camada, delta
de linhas contra a execução anterior, snapshot de configuração, erro.

Três sinais que valem alerta desde o começo, porque são as falhas silenciosas
do domínio:

1. **Delta de volume anômalo** — carga que traz 3% das linhas da anterior
   geralmente é layout mudado, não empresa fechando.
2. **Regra bloqueante disparada** — Ativo ≠ Passivo + PL fora da tolerância.
3. **Captura sem publicação** — dado baixado que não chegou em gold: pipeline
   parado no meio.

---

## 11. Decisões arquiteturais

| # | Decisão | Alternativa descartada | Por quê |
|---|---|---|---|
| 1 | Configuração em banco, versionada | YAML versionado no repo | as telas precisam editar em runtime; YAML daria auditoria melhor e UX pior, e o produto **é** o plano de controle |
| 2 | Bronze imutável + recomputação | correção in-place em silver | correção in-place torna o histórico não reproduzível e o bug indetectável |
| 3 | Postgres do Railway em prod; DuckDB só em dev | DuckDB em produção com volume | volume é estado a operar; o Postgres já vem no plano e o pacote suporta os dois sinks |
| 4 | Serviço único (API + estático) | front em serviço/host separado | dois serviços consomem o dobro de recurso do plano para servir arquivo estático |
| 5 | SQL restrito para campos calculados | plugin Python por campo | recomputabilidade, portabilidade entre sinks, e não abrir RCE via formulário |
| 6 | Publicação por swap de versão | escrita direta na view de consumo | é o que permite "errado não publica" sem janela de dado quebrado |
| 7 | Sem dbt | camada gold em dbt | dbt duplicaria o catálogo de campos calculados, que é o produto; e adiciona runtime a operar |
| 8 | Cron do Railway | Celery/Redis, ou GitHub Actions | fila é serviço a mais; runner externo tira a ingestão de onde o banco está |
| 9 | CVM como fonte canônica | brapi/dadosdemercado | só a CVM é o dado auditado; terceiro entra como atalho validado contra ela |
| 10 | Bronze como `bytea` em tabela Postgres | volume do Railway | ver ADR-10 abaixo |
| 11 | Classe de informação acima do dataset; tabela gerada da configuração | `CREATE TABLE` por migração escrita à mão | enquanto o DDL estiver no código, criar classe pela interface exige deploy — o oposto do produto |
| 12 | Multi-fonte por derivação, com `origem_dataset` na identidade física | upsert com a última carga vencendo | sobrescrever apaga a divergência antes de alguém poder decidir; derivar mantém as duas e torna a escolha reversível |
| 13 | Precedência declarada por atributo | precedência por fonte inteira | o cadastro da CVM é a melhor fonte para a razão social e não diz nada sobre o resto |
| 14 | Escopo de chave de API em classe de informação | escopo por rota ou por vista | rota é detalhe de implementação; a classe é o que o consumidor entende, e app novo vira chave nova |
| 15 | Carga por staging sem índice + upsert em uma instrução | upsert linha a linha | 300 linhas/s tornava o recomputo do bronze — o plano de volta de toda migração — lento demais para alguém acionar |
| 16 | Postgres do Railway, confirmado por medição | DuckDB em volume, um serviço só | o custo marginal é zero dentro do plano já contratado; ver ADR-16 abaixo |

### ADR-11 — a tabela como consequência da classe

**Contexto.** Até a etapa 3, `fato_conta` e `dim_empresa` eram `CREATE TABLE`
escritos na migração `0004`, e as vistas de gold eram um dicionário em Python.
`cfg_dataset.tabela_destino` apontava para tabela que já tinha de existir.

**Decisão.** `cfg_classe` e `cfg_atributo` passam a ser a origem do DDL.
`motor.ddl` gera tabela, índice de identidade e ALTERs; `cfg_vista` guarda o
corpo das vistas de gold. A migração `0004` fica só com `publicacao`, que é do
sistema e não de classe nenhuma.

**Consequência.** Criar uma classe de informação nova é um POST em
`/admin/api/classes` — a tabela nasce na mesma chamada. O DDL histórico
permanece em `migracoes.DDL_HISTORICO_SILVER` como referência de regressão: é
contra ele, e não contra o próprio gerador, que o teste compara.

**O que a decisão custa.** A configuração passa a poder quebrar o banco. Três
guardas: nome de tabela validado antes de entrar em DDL, `ALTER ADD COLUMN`
mas nunca `DROP COLUMN` (coluna órfã vira divergência para alguém decidir, não
perda de dado), e um digest em `cfg_seed` que evita refazer índice a cada boot.

### ADR-12 — resolução multi-fonte é derivação, não sobrescrita

**Contexto.** Duas fontes descrevem a mesma empresa e discordam: o cadastro da
CVM traz `DENOM_SOCIAL`, o arquivo de DFP traz `DENOM_CIA`.

**Decisão.** `origem_dataset` entra na identidade física da tabela. As duas
linhas coexistem; a linha publicada sai de uma vista gerada que escolhe, por
atributo, o valor da fonte de maior precedência.

**Consequência.** Inverter precedência é republicar, não recarregar. Desligar
uma fonte não apaga o que ela trouxe. Só atributo realmente disputado ganha
coluna de origem, e ela chega ao consumidor dentro de `proveniencia.por_atributo`.

**Limite.** A vista resolvida agrupa por identidade. Numa classe de fonte
única isso seria um `GROUP BY` sobre centenas de milhares de linhas para não
decidir nada — por isso ela só é gerada para classe com `resolucao =
'precedencia'`.

### ADR-10 — bronze em tabela, não em volume

**Contexto.** O filesystem do container é efêmero, então o arquivo oficial
precisa de destino durável. Duas opções dentro do plano: volume do Railway, ou
coluna `bytea` em tabela. Volume de 16 anos de DFP+ITR estimado em 0,6–1,4 GB,
crescendo ~50–90 MB/ano mais recapturas.

**Decisão.** Tabela `bronze_captura`, com payload em `bytea`.

**Por quê.** Três razões, em ordem de peso:

1. **Volume monta em um serviço só.** A ingestão roda como cron (processo
   curto) e a API como serviço web. Com volume, só um dos dois enxerga o
   bronze — e as telas de Execuções e Catálogo, que precisam servir "o arquivo
   que originou este número", ficariam sem fonte, porque o processo com o mount
   não está no ar quando a requisição chega. Contornar isso exigiria fundir
   ingestão e API num serviço, contrariando a decisão 8.
2. **Imutabilidade deixa de ser convenção.** Volume é filesystem gravável;
   a garantia seria só disciplina. Em tabela, `REVOKE UPDATE, DELETE` mais
   trigger que levanta exceção tornam o princípio 1 executável pelo banco.
3. **Um caminho de backup.** O único dado irreconstituível do sistema passa a
   estar no mesmo backup que já existe, em vez de depender de política
   separada de volume.

**Custo empata**, o que foi o resultado inesperado da análise: o Postgres do
Railway persiste num volume, então as duas opções consomem o mesmo recurso do
plano. O delta é WAL e índice — real, mas não é a diferença entre caber e não
caber no crédito. Removido o custo da conta, a decisão vira operacional.

**Custo aceito.** Escrita de 40 MB gera ~40 MB de WAL, inflando backup e tempo
de restore; leitura de `bytea` carrega o payload inteiro em memória durante a
recomputação.

**Gatilho de revisão.** Bronze acima de ~5 GB, ou restore do banco acima de 10
minutos: migrar o payload para object storage (Cloudflare R2 tem 10 GB grátis
sem taxa de egress), mantendo metadado e hash na tabela. É serviço de terceiro
e cai na regra de aprovação; a migração custa uma coluna `payload_ref`.

---

### ADR-16 — Postgres, confirmado com número

**Contexto.** A pergunta voltou em 31/07/2026: "o Postgres não tem custo
adicional? dá para evitar?". O ADR-3 já respondia, mas por argumento, não por
medição — e argumento sem número é o que faz a pergunta voltar.

**O que foi medido.**

| Item | Valor |
|---|---|
| API + base real de 364 MB | **114 MB de RSS** — o DuckDB não carrega o arquivo na memória |
| Bronze de 1 ano (DFP + ITR + cadastro) | 28,6 MB |
| Silver de 1 ano | 817.600 linhas |
| Arquivo do banco, 1 ano | 364 MB |
| Projeção para 15 anos | ~12,3 milhões de linhas, ~5,5 GB |

**Taxas do Railway** (jul/2026, por mês): vCPU $20,01 · RAM $10,00/GB ·
volume $0,156/GB.

**A decisão.** O plano contratado é o **Pro**: $20/mês com $20 de uso
incluído, 24 GB de RAM, 24 vCPU e **100 GB de disco**. O consumo corrente é
$3,60 de compute. O MyData inteiro — API mais Postgres — soma cerca de $4/mês.

Ou seja: **o custo marginal do Postgres é zero** até o uso total ultrapassar os
$20 já pagos, e a projeção de 15 anos ocupa 5% do disco incluído.

**O que quase foi decidido errado.** A primeira análise assumiu o plano Hobby,
onde o teto de volume é 5 GB. Sob essa premissa o histórico de 15 anos
estouraria o disco antes de o custo importar, e a recomendação foi DuckDB em
volume com serviço único. Estava errada na premissa, e a premissa era tudo.

**O que a alternativa custaria, e por isso foi descartada.** DuckDB em volume
economiza ~$2/mês e cobra em arquitetura: volume monta em um serviço só, então
a ingestão teria de rodar dentro da API — contrariando o ADR-8 e o desenho do
CLI como processo curto; e DuckDB tem escritor único, então cada carga
degradaria as respostas da API por alguns minutos. Trocar duas propriedades de
projeto por $2/mês dentro de um orçamento ocioso é mau negócio.

**Gatilho de revisão.** Uso total passando de $20/mês, ou disco passando de
50 GB. Nos dois casos a saída já está desenhada: bronze para object storage
([ADR-10](#adr-10--bronze-em-tabela-não-em-volume)) e silver só dos anos
recentes, já que recomputar um ano antigo do bronze leva 3 minutos.

---

## 12. Atributos de qualidade

| Atributo | Como é obtido | Como é verificado |
|---|---|---|
| Corretude | filtros obrigatórios em gold; regras bloqueantes | Ativo = Passivo + PL como gate; testes das 7 armadilhas |
| Reprodutibilidade | bronze imutável + `cfg_snapshot` | teste que recomputa do bronze e compara com a carga original |
| Idempotência | chave natural declarada | teste que roda a mesma janela duas vezes e confere contagem |
| Custo | serviço único, cache por `ETag`, cron curto | ausência de serviço pago no `railway.json` |
| Evolutibilidade | fonte nova = configuração | cadastrar uma segunda fonte pela UI, sem deploy |
| Acessibilidade | 6 comportamentos como aceite | `axe` sem violação crítica ou séria |

---

## 13. Riscos

| Risco | Impacto | Mitigação |
|---|---|---|
| CVM muda layout do CSV | carga silenciosamente errada | `cfg_coluna` com obrigatoriedade + alerta de delta de volume |
| Bronze cresce além do plano | custo, restore lento | retenção de 24 meses + último por `(dataset, ano)`; `UNIQUE (dataset_id, sha256)` evita recaptura idêntica; gatilho de migração para object storage em ~5 GB ([ADR-10](#adr-10--bronze-em-tabela-não-em-volume)) |
| Recomputação global fica cara | janela de indisponibilidade | recomputação por janela como padrão; global só para campos de partição cruzada |
| Reapresentação retroativa | número muda sem aviso ao consumidor | `versao_documento` na resposta; `is_latest` global recomputado |
| Não há ticker na CVM | `/v1` por ticker depende de fonte não-oficial | mapa `ticker → cd_cvm` isolado, marcado como dado de terceiro, nunca misturado ao oficial |
| Créditos do Railway esgotam | serviço para | cache, serviço único, retenção; monitorar consumo |

---

## 14. Questões em aberto

1. **Origem do mapa ticker → `cd_cvm`** — a CVM não publica ticker. A B3
   publica, mas não como dado aberto estável. Qualquer escolha aqui é a
   primeira dependência de terceiro do sistema, e precisa ficar isolada.
2. **Multi-tenant** — o escopo por classe (etapa 7) resolve *quais* classes um
   app lê. Não resolve isolamento de dado dentro da classe: se um dia dois
   consumidores precisarem ver linhas diferentes da mesma classe, o modelo não
   suporta e a decisão é nova.
3. **Gate de publicação sobre linha já publicada** — um upsert que altere linha
   já rotulada muda gold sem passar pelo gate. Uma área de staging fecharia o
   buraco; a Etapa 3 reescreveu as tabelas e seria o momento certo, mas o custo
   não se justificou sem um caso concreto.
4. **Bronze duplicado entre mapeamentos** — a captura é por dataset, então dois
   mapeamentos sobre o mesmo arquivo guardam duas cópias. Medido na carga real
   de 2023: o ZIP de 13 MB da DFP está duas vezes em `bronze_captura`, uma para
   `cvm_dfp` e outra para `cvm_dfp_empresa`. Deduplicar por `sha256` entre
   datasets economizaria o espaço, ao custo de a captura deixar de pertencer a
   um mapeamento só — o que complica descartar carga reprovada de um deles.
5. **Mapeamento lê mais do que precisa** — `cvm_dfp_empresa` parseia 1.276.157
   linhas para extrair 732. O `padrao_arquivo` já filtra quais membros do ZIP
   entram; falta poder declarar que um mapeamento só quer alguns deles. Hoje é
   trabalho jogado fora, não erro.

---

## Apêndice A — as sete armadilhas do dado da CVM

| # | Armadilha | Efeito se ignorada | Tratamento |
|---|---|---|---|
| 1 | Reapresentação (`VERSAO`) | valores dobram | `is_latest` = maior versão por `(cd_cvm, tipo_doc, dt_refer)` |
| 2 | `ORDEM_EXERC` | valores dobram | filtrar `ÚLTIMO` |
| 3 | `ESCALA_MOEDA` | mistura unidade, mil e milhão | `vl_conta_norm`, preservando `vl_conta` |
| 4 | Individual vs consolidado | empresa contada duas vezes | flag `consolidado`, um escopo por consulta |
| 5 | ITR é acumulado (YTD) | "trimestre" que na verdade é o ano até ali | flag `itr_acumulado` + view de trimestre isolado |
| 6 | Contas custom (`ST_CONTA_FIXA='N'`) | comparação entre empresas sem sentido | comparar só `'S'` |
| 7 | Encoding `latin-1` | acentuação corrompida | ler como `latin-1` |

Regra de consulta, sempre: `WHERE is_latest AND ordem_exerc = 'ÚLTIMO' AND
consolidado = <um único valor>`. Contas de posição (BPA, BPP, DMPL) não
acumulam — a armadilha 5 não se aplica a elas.

## Apêndice B — layout da fonte

```
https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{DFP|ITR}/DADOS/{dfp|itr}_cia_aberta_{ano}.zip
  └── {dfp|itr}_cia_aberta_{BPA|BPP|DRE|DFC_MI|DFC_MD|DVA|DRA|DMPL}_{con|ind}_{ano}.csv
```

Encoding `latin-1`, separador `;`. Colunas-chave: `CD_CVM`, `DT_REFER`,
`VERSAO`, `ORDEM_EXERC`, `CD_CONTA`, `ST_CONTA_FIXA`, `ESCALA_MOEDA`,
`VL_CONTA`. Cadastro de empresas é dataset separado: `cad_cia_aberta.csv`.
`tipo_doc` é derivado do nome do arquivo, não do parâmetro de chamada.
