# Relatório da noite — 2026-08-02/03

Execução autônoma do plano de implantação, atualizada ao fim de cada etapa.

## Resultado

Sete das nove etapas fechadas. **263 testes verdes**, de 217 no início.
Dez commits. Nada foi para o GitHub.

| Etapa | Situação |
|---|---|
| 0 — Produção com dado | **bloqueada** — o cron nunca foi agendado |
| 1 — Fechar o merge do scrap | **pronta** |
| 2 — Pesquisa que fecha decisão | **pronta** — 7 questões com fonte |
| 3 — A lei | **pronta** — `docs/fundacao-de-dados.md` + ponteiro global |
| 4 — Contrato e normalização visíveis | **pronta** — verificação de tela pendente |
| 5 — Fonte nova pelo fluxo declarativo | **pronta** — BCB no lugar da B3 |
| 6 — Correlação declarada | **pronta** |
| 7 — Gestão consolidada | **pronta** — verificação de tela pendente |
| 8 — Acesso público gratuito | **não iniciada, de propósito** — você a adiou para decidir custo primeiro |

## Atualização — 2026-08-16

Verificação de todo o "Precisa de você" contra o estado real (painel Railway,
suíte local nos dois dialetos, mapeamento de base via agentes GSD/codex).
Nada abaixo é suposição — cada linha foi checada nesta sessão.

| # | Item de 02-03/08 | Estado agora |
|---|---|---|
| 1 | Cron do `mydata-cron` nunca agendado | **Resolvido** — `cronSchedule: "0 6 * * *"` no painel, próxima execução 2026-08-17T06:00:00Z. Banco de produção **não está vazio**: volume Postgres com 4.69GB usados |
| 2 | Processo órfão na porta 8420 (PID 19468) | **Obsoleto** — porta livre, nada a derrubar. O processo não existe mais nesta máquina |
| 3 | Preço: falar com a B3, ou desistir | **Resolvido, e a pergunta era a errada** — ver "Etapa 8b" abaixo |
| 4 | `ticker`/`segmento_listagem` na API pública | **Verificado, já protegido**: o escopo por classe (`empresa`/`negociacao_b3`) já bloqueava essas rotas; faltava só o teste de regressão, adicionado em `tests/test_api_opcoes.py` (commit `aca7b89`). A decisão de negócio sobre publicar isso na etapa 8 continua aberta |
| 5 | Ler a ODbL na íntegra | **Resolvido**, mais tarde no mesmo dia — ver "Etapa 8a" abaixo |
| 6 | Suíte no dialeto Postgres nunca rodou | **Rodada hoje**: 481 passed / 2 skipped / 3 failed nos dois dialetos (DuckDB e Postgres, resultado idêntico). As 3 falhas são só `web/dist` ausente neste checkout, não bug. Achado: faltava `pytz` (dependência transitiva do DuckDB) declarada — sem ela a suíte inteira falhava com `_duckdb.InvalidInputException` |
| 7 | Nada foi para o GitHub | **Resolvido** — a branch de handoff já está mergeada (diff zero contra `main`), e o deploy ativo em produção roda no commit mais recente da `main` |
| 8 | Teto de gasto no Railway | **Resolvido**, mais tarde no mesmo dia — ver "Etapa 8a" abaixo |
| 9 | `BRAPI_TOKEN` | **Sem mudança** — pendente, se o mapa ticker→empresa for adiante |
| 10 | Renomear `seed_cvm.py` | **Resolvido** — `app/seed_fontes.py`, rename 100% + 28 referências ajustadas, sem mudança de comportamento (commit `452085b`) |

**Achados novos**, do mapeamento de base (`.planning/codebase/CONCERNS.md`,
commit `225d834`), fora do escopo de 02-03/08:

- O pipeline CVM legado foi removido nesta limpeza; `app/motor` declarativo é o único caminho de ingestão.
- Sem estratégia de retenção/backup para o bronze, que cresce sem parar — decisão operacional antes de aumentar frequência de carga.
- Sem CI no repositório — meu review levantou isso como "candidato óbvio", mas o próprio `CONCERNS.md` e a regra de custo de infraestrutura pedem para pausar até você alinhar custo/ambiente. Não implementado, de propósito.

**Ações executadas nesta sessão** (orquestração Claude + codex, GSD via
`~/.codex`):

- Guarda de produção contra `PORTAL_API_ABERTA` ativa ou `PORTAL_ADMIN_TOKEN` ausente, em `tests/test_deploy.py` — commit `aca7b89`, com push.
- `PORTAL_ADMIN_TOKEN` **rotacionado em produção**: o valor antigo apareceu na tela desta sessão durante um diagnóstico (`railway variables --kv`); o valor novo foi setado via stdin, sem exposição, e o serviço `mydata` já redeployou com ele (`8b4c79b7`, `SUCCESS`).
- Mapeamento completo da base via 4 agentes GSD (rodando dentro do codex) em `.planning/codebase/` — commit `225d834`, com push.
- `app/seed_cvm.py` renomeado para `app/seed_fontes.py`, com as 28 referências no repositório (código, testes, docs) ajustadas — commit `452085b`, com push.
- Registro desta atualização em `RELATORIO-NOITE.md` — commit `ff39b20`, com push.

## Fechamento — 2026-08-16

Cinco commits, todos com push (`225d834` → `452085b`), zero force-push, zero
revert. Todo o "Precisa de você" de 02-03/08 saiu de aberto para resolvido,
obsoleto ou "decisão sua sem mudança" — nada ficou em estado desconhecido.

**Suíte, de ponta a ponta:** `npm run build` e `npm test` (38/38) no front;
com `web/dist` presente, `pytest -q` fecha em **488 passed, 0 failed, 0
skipped** — as 3 falhas e os 2 skips que apareciam antes eram todos
condicionados à ausência do build do front, não bug.

**O que ficou pronto hoje**, sem nenhuma decisão sua pendente:

- Cron, banco de produção, handoff e suíte Postgres — verificados, não havia mais o que fazer.
- Guarda de produção contra `PORTAL_API_ABERTA`/`PORTAL_ADMIN_TOKEN` ausente.
- Regressão explícita do escopo B3 em `ticker`/`segmento_listagem`.
- `PORTAL_ADMIN_TOKEN` rotacionado em produção.
- `seed_cvm.py` → `seed_fontes.py`.
- Mapa de base completo em `.planning/codebase/`.

**O que só você decide, sem mudança hoje:**

| Decisão | Onde está documentada |
|---|---|
| `BRAPI_TOKEN`, se o mapa ticker→empresa avançar | item 9 |
| CI (pausado por regra de custo/ambiente) | `.planning/codebase/CONCERNS.md` |

ODbL, teto de gasto Railway, etapa 8a, o pipeline CVM legado e a retenção
do bronze saíram desta lista — fechados no mesmo dia, ver abaixo.

## Etapa 8a — acesso público gratuito (CVM + BCB), fechada em 2026-08-16

A etapa 8 original tratava "acesso público" como uma peça só, bloqueada por
duas decisões de negócio (preço B3, teto de custo). Ela foi dividida:

- **8a — CVM + BCB**, republicáveis (Decreto 8.777/2016; BCB é dado aberto): sem bloqueio legal. Implementada e no ar.
- **8b — B3** (`negociacao_b3`, `instrumento_b3`): continua fora do público. ADR-18/ADR-20 são explícitos — abrir isso a terceiros reabre a decisão, não herda o uso pessoal já aprovado. Sem mudança.

**ODbL, lida na íntegra (opendatacommons.org/licenses/odbl/1-0/):** o
share-alike (seção 4.4) só se aplica a *Derivative Database*. Seção 4.5.b,
texto literal: *"Using this Database... to create a Produced Work does not
create a Derivative Database for purposes of Section 4.4."* Uma resposta de
API sobre uma consulta pontual é *Produced Work*, que só exige atribuição
(seção 4.3.a) — e o MyData já atribui em toda resposta (`proveniencia.fonte`,
`sha256`, `versao_documento`). Não bloqueava a 8a; não precisava de nenhuma
licença share-alike declarada.

**Teto de gasto Railway:** `hardLimit: $20`, `softLimit: $15` (alerta em
75%), definido no workspace inteiro. Uso do período (14/08–14/09) na hora do
ajuste: $2,76 realizado, ~$14,99 projetado.

**O achado que quase passou:** a classe `empresa` mistura CVM e B3 no nível
de *atributo*, não de classe — `ticker`, `nome_pregao`, `setor_b3`,
`segmento_listagem`, `dt_listagem` são exclusivos da B3, e pior, `cnpj` **não
tem precedência própria**: usa a precedência default da classe
(`["cvm_cadastro", "b3_listadas", "cvm_dfp_empresa"]"`), então pode vir da B3
silenciosamente sempre que o cadastro CVM não tiver o valor. Uma lista fixa
de "campos B3" filtraria os 5 óbvios e deixaria o `cnpj` passar em algumas
linhas e não em outras. O codex parou a primeira tentativa de implementação
exatamente por isso, em vez de inventar uma correção incompleta.

**A correção**: filtro por proveniência real, não lista fixa.
`app/api/proveniencia.py::decorar()` usa `datasets_por_atributo` (o mapa
declarativo de `cfg_atributo.precedencia`) para classificar cada atributo —
só-B3 é removido sempre; disputado é removido linha a linha pelo vencedor
real (`por_atributo`, a mesma proveniência que já aparece em toda resposta).
Cobre qualquer atributo cuja precedência inclua B3, presente ou futuro, não
só os 5 nomes óbvios. Escopo novo `fonte:b3`, opt-in explícito; `leitura`
(chave antiga) continua vendo tudo. O download do arquivo bronze bruto de
captura B3 também passou a exigir `fonte:b3` — sem isso o filtro de campo
seria inútil.

`POST /v1/chaves`: emissão pública sem sessão, escopo travado no servidor
(`classe:empresa,demonstracao_financeira,indicador_macro`, nunca aceita
`classes`/`escopos` do cliente), quota fixa 30/min e 2000/dia, 5 emissões
por IP por dia (migração `0018`, tabela `uso_ip_emissao_chave`).

Commit `693512e`, com push. Deploy `4e1ecd2c`, `SUCCESS`, migração aplicada
no boot. Testado em produção de ponta a ponta (`POST /v1/chaves` real,
depois revogada — nenhuma chave de teste ficou no banco). Suíte: 490
passed, 0 failed.

**Nota operacional, não bloqueio:** se uma chave for emitida manualmente
pelo admin com `classe:negociacao_b3`/`classe:instrumento_b3` sem também
somar `fonte:b3`, o resultado não é 403 — é a classe respondendo com os
campos B3 vazios. Não vaza nada, só confunde. Lembre de somar os dois ao
emitir chave B3 pelo admin.

## Etapa 8b — B3, resolvida sem contato com a B3

A pergunta "falar com a B3, ou desistir" partia de uma premissa que não é
mais a do projeto: redistribuição *comercial* ou pública a terceiros
externos. Antes de escrever qualquer contato, li a Política Comercial de
Market Data da B3 na íntegra (v3.0.4, 15/10/2024) para checar se dado de
fim de dia/D-1 teria isenção de autorização — tem (seção 7.9/7.10), mas só
para quem já assinou o Contrato de Distribuição como `DISTRIBUIDOR` ou
`REDISTRIBUIDOR`, e a definição desses termos (seção 3) é sobre captura via
acesso direto/indireto à infraestrutura de negociação — feed contratado, não
o arquivo público que o MyData baixa do site. Uma minuta de e-mail para
`produtos-marketdata@b3.com.br` (o canal que a própria política indica para
caso não coberto) ficou pronta, mas não foi enviada.

**Não precisou.** O uso é pessoal — um datalake para consumo próprio, não
uma API pública para terceiros externos. É exatamente o cenário que o
ADR-18 e o ADR-20 já autorizam hoje: uso pessoal, consumo servidor-a-servidor
entre sistemas do Alex, sem redistribuição. Nada muda no código: 8b
continua fora do público (a 8a já cobre CVM/BCB), e permanece assim
enquanto o uso for pessoal — não é uma decisão pendente aguardando resposta
da B3, é a decisão já tomada e válida.

## Pipeline CVM legado e retenção/backup do bronze, fechados em 2026-08-16

**Pipeline legado:** não havia dois caminhos coexistindo para consolidar —
`src/cvm_financas/` era código morto (não copiado no Dockerfile, não
instalado em produção, não importado por `app/`). Removido, não migrado.
Commit `edbe034`.

**Retenção do bronze:** medido em produção, não estimado. `bronze_captura`
tem **78 MB, 73 linhas**, capturando desde 2026-07-31 (16 dias) — banco
inteiro em **2.377 MB**, contra 50 GB provisionados no volume. Taxa real:
**~4,9 MB/dia**. Nesse ritmo, mesmo triplicando a ingestão, o volume
provisionado dura décadas. A preocupação do `CONCERNS.md` era especulativa
("cresce sem parar"), sem número por trás; com número, não há ação a tomar.
ADR-21 (compressão TOAST, aplicada antes desta sessão) já faz o trabalho.

**Backup — o achado real:** `railway postgres pitr status` mostrou
`enabled: false`. Hoje não existe backup contínuo do Postgres de produção,
e o bronze é "a única cópia que não dá para reconstruir" segundo o próprio
`CLAUDE.md`. Railway não cobra taxa fixa de PITR — cobra storage do bucket
de WAL comprimido (zstd) + egress do upload, proporcional ao volume de
escrita, não ao tamanho total. Dado ~4,9 MB/dia, custo estimado é baixo
(centenas de KB comprimidos/dia).

**Decisão do Alex:** não habilitar PITR agora. Risco de perda total do
bronze em caso de falha do volume aceito consciente, não por omissão — a
pergunta foi feita com os números na mesa. Reabrir quando a taxa de escrita
mudar de ordem de grandeza (nova fonte de alto volume, aumento de
frequência) ou se o apetite a risco mudar.

## O achado da noite

**A B3 veda redistribuição.** Os Termos de Uso proíbem "distribuição,
redistribuição […] reformatação, publicação a terceiros" e uso comercial sem
autorização prévia e por escrito. A página do COTAHIST não tem regime próprio
que a dispense. Três consequências:

1. **A etapa 5 trocou de fonte** — saiu a B3, entrou o SGS do Banco Central,
   que é dado aberto de verdade e prova o mesmo: fonte nova é configuração.
2. **Preço virou decisão sua** — falar com a B3, ou aceitar uso interno.
3. **`empresa` já tem `ticker` e `segmento_listagem` vindos da B3.** Uso
   interno está amparado; publicá-los numa API pública, não. Isso precisa de
   decisão **antes** da etapa 8.

Em contrapartida, a **CVM é republicável**: o Decreto 8.777/2016 e o termo do
portal exigem citar a fonte e nada além. O núcleo do MyData está liberado, e a
proveniência que já emitimos é exatamente a citação exigida.

E onze provedores depois — cinco pagos, seis gratuitos — **nenhum entrega
proveniência por número**. O diferencial deixou de ser hipótese.

## O que o merge do scrap virou

O `scrap` não era um scraper: era um cliente HTTP do brapi.dev. Quatro comandos
de shell, antes de qualquer planejamento, mostraram que o transporte dele
(retry, backoff, 429, mapeamento de erro) já existia no motor — e lá com bronze
imutável e proveniência, que o cliente não tem.

O que era insubstituível era conhecimento: o catálogo de endpoints e a tabela
de qual feed vem de qual fonte primária, com que atraso. Virou
`docs/fontes-terceiros.md`. Os quatro commits do `scrap` são história do MyData
agora, por merge de subtree — nada foi copiado, nada foi perdido.

## Decisões que tomei sozinho

| # | Decisão | Por quê | Como reverter |
|---|---|---|---|
| 1 | Merge do `scrap` por subtree, não cópia | os quatro commits viram história do MyData; cópia perderia autoria e data | `git revert 233093e` |
| 2 | `src/brapi_client/` achatado; pyproject, README e .gitignore do scrap removidos | `packages.find` já procura em `src/`; segundo pyproject não é lido por ninguém | `git revert 93c95b5` |
| 3 | O `CLAUDE.md` do scrap virou `docs/fontes-terceiros.md` | era o conteúdo mais valioso dele, e um `CLAUDE.md` aninhado seria carregado como instrução naquele diretório | mesmo commit |
| 4 | brapi não será fonte de preço nem de fundamentos | preço é a B3 atrasada e sem arquivo original; fundamentos são a CVM, que já ingerimos na origem | `docs/fontes-terceiros.md` |
| 5 | Quinto caso no teste de decisão: dado que um terceiro pede e nenhum app seu usa | o MyData passou a ter consumidor fora de casa; sem esse caso a lei não responde à pergunta que a etapa 8 cria | `docs/fundacao-de-dados.md` § 2 |
| 6 | Ponteiro para a lei em `~/.claude/CLAUDE.md` | é o que faz "obrigatório" ser mecânico em vez de aspiracional. **Arquivo global, fora deste repositório** | remover a seção "Onde cada dado mora" |
| 7 | Contrato montado da configuração, nunca gravado | contrato à parte é segunda declaração do mesmo fato, livre para divergir do que roda | — |
| 8 | Forma do contrato: subconjunto do ODCS | o `contracts` do dbt só carrega schema; o ODCS carrega qualidade, SLA e versão | `app/motor/contrato.py` |
| 9 | `version` do contrato é o inteiro da configuração, não semver | distinguir mudança que quebra exigiria comparar schemas entre versões, e não há caso que pague isso hoje | lacuna em `docs/pesquisa-mercado.md` § Q6 |
| 10 | `physicalType` fora do contrato | depende do dialeto do sink; prometer tipo que muda entre DuckDB e Postgres é promessa não cumprida | — |
| 11 | Etapa 5 troca B3 por Banco Central | ver "O achado da noite" | — |
| 12 | **Três consertos genéricos em `app/motor/`**, contrariando o aceite "zero diff" | ver abaixo | `git revert a0488f4` |
| 13 | Correlação explícita (Cube) com validação por tipo de chave (MetricFlow) | as classes já declaram identidade, e a proveniência multi-fonte já exige explicitação em vez de inferência | `docs/pesquisa-mercado.md` § Q7 |
| 14 | Travessia fora de escopo devolve 403 inteiro, não resultado parcial | servir a origem com as colunas do destino omitidas daria a impressão de que o dado não existe | `app/api/main.py` |
| 15 | Não derrubei o processo na porta 8420 | o diretório de trabalho dele é o checkout principal; `servidor.py status` o classifica como "DE OUTRO" | ver "Precisa de você" nº 2 |
| 16 | Não iniciei a etapa 8 | você a adiou explicitamente para decidir custo antes; construí-la seria ignorar isso | — |

### Sobre a decisão 12 — o aceite que não foi cumprido

O critério da etapa 5 era `git diff --stat` zerado em `app/motor/`. Não foi
cumprido, e tentar cumpri-lo é o que teve valor: revelou três coisas que o
motor não sabia fazer **genericamente**, e que nenhuma linha de configuração
resolveria.

1. **Uma API sem lugar para o número da página era buscada 500 vezes.** A URL
   não mudava, a resposta não vinha vazia, e o "para quando esvaziar" nunca
   disparava. O bronze terminaria com 500 cópias idênticas.
2. **A janela da execução não chegava ao endereço de uma fonte JSON.** A B3
   não notou porque captura um retrato inteiro; uma série histórica recorta por
   ano no próprio endereço, e sem isso toda janela capturaria a mesma resposta
   — que o `sha256` idêntico transformaria em no-op. Dado faltando, sem erro.
3. **As pseudo-colunas `$` liam de um contexto que, para JSON, era vazio.** Numa
   fonte de arquivo o contexto vem do nome; numa API vem dos parâmetros
   declarados no mapeamento.

Os três são de transporte, não de fonte. `test_nada_em_app_sabe_o_que_e_o_bcb`
varre o pacote atrás de "bcb", "sgs", "selic" e "ipca" e falha se algum vazar.

## Precisa de você

| # | O quê | Como desbloqueia |
|---|---|---|
| 1 | **Cron Schedule do `mydata-cron` nunca foi definido** — a primeira carga não rodou e o banco de produção provavelmente está vazio. É a etapa 0, e as outras assumem dado lá | painel do Railway, ou disparar pela tela de Execuções. Sugerido `0 11 * * *`: a CVM republica de manhã |
| 2 | **Processo órfão na porta 8420** — PID 19468, `cwd=/Users/acamerini/dev/cvm-financas`, subido com `uvicorn` direto. O checkout principal está em `8a57cc3`, então ele serve código anterior a toda a camada de apresentação | conferir e derrubar. É o caso que o `CLAUDE.md` descreve: pior que estar fora do ar, porque parece no ar. Bloqueou a verificação de tela e a auditoria `axe` das etapas 4b e 7 |
| 3 | **Preço: falar com a B3, ou desistir** | sem autorização escrita, preço só existe como uso interno |
| 4 | **`ticker` e `segmento_listagem` na API pública** | vieram da B3. Antes da etapa 8: tirar do escopo público, ou obter autorização |
| 5 | **Ler a ODbL na íntegra** | é a licença dos datasets da CVM; falta saber se o *share-alike* alcança a API derivada e qual licença declarar para ela |
| 6 | **Suíte no dialeto Postgres não rodou** — não há Postgres local no ar, e subir um seria servidor solto pelo Bash | `PORTAL_TESTE_POSTGRES=<dsn> pytest -q`. Importa: os dois últimos deploys quebraram por defeito só de Postgres, e a noite acrescentou a migração `0011_correlacao` e a vista `gold_indicadores`. Conferi estaticamente que a migração renderiza e que nada novo agrega booleano, mas não é o mesmo que executar |
| 7 | **Nada foi para o GitHub** | `git push origin claude/mydata-handoff-3b2cc1:main` — dispara deploy |
| 8 | Teto de gasto no Railway (*Usage Limits*), alerta em 75% | é a rede de segurança final da etapa 8; o valor é seu |
| 9 | `BRAPI_TOKEN`, se o mapa ticker→empresa for adiante | plano gratuito; quatro tickers respondem sem token |
| 10 | `seed_cvm.py` guarda CVM, B3 e agora BCB | o nome ficou menor que o conteúdo. Renomear é mecânico; não fiz para não misturar com o trabalho da noite |

## Evidência

### Suíte

```
$ .venv/bin/python -m pytest -q
263 passed in 35.25s
```

217 no início da noite. Os 25 do brapi entraram na suíte, mais 21 novos:
contrato (3), fonte BCB (7), correlação e gestão (9), e ajustes de forma do
seed.

### Etapa 2 — a pesquisa

`docs/pesquisa-mercado.md`, sete questões, cada uma terminando em **Decisão:**
com a fonte. Quatro agentes em paralelo, ~1,5 min cada.

### Etapa 3 — o teste de decisão

| Caso | Onde mora |
|---|---|
| P/L da Petrobras — indicador calculado | **MyData**, campo calculado |
| Score de qualidade do BolsIA | **App** — os pesos são juízo dele |
| Calendário de dividendos, só o BolsIA usa | **MyData** — nº de consumidores não entra na conta |
| Cópia local de `empresa` | **Cache** com validade, nunca fonte |
| CNPJ de registro cancelado, pedido por terceiro | **MyData** — o critério é a origem, não a demanda |

### Etapa 5 — fonte nova, e a promessa verificada

Quatro séries do SGS (Selic, IPCA, câmbio, CDI) na classe `indicador_macro`,
declaradas em `SERIES_BCB`. Uma série nova é uma linha naquela lista.

```
$ .venv/bin/python -m pytest -q tests/test_fonte_bcb.py
7 passed in 0.80s
```

### Etapa 6 — a travessia, sobre dado real

```
GET /v1/correlacoes/empresa_demonstracoes?onde=cd_conta:1,grupo:BPA
```
```json
{
  "correlacao": {
    "origem":  {"classe": "empresa", "vista": "gold_empresa", "atributo": "cd_cvm"},
    "destino": {"classe": "demonstracao_financeira", "vista": "gold_demonstracoes",
                "atributo": "cd_cvm"},
    "relacionamento": "um_para_muitos"
  },
  "dados": [{
    "cd_cvm": 9512, "denom_social": "EMPRESA TESTE S.A.", "uf": "RJ",
    "destino_dt_refer": "2023-12-31", "destino_cd_conta": "1",
    "destino_ds_conta": "Ativo Total", "destino_vl_conta_norm": 1100000.0,
    "proveniencia": {
      "fonte": "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv",
      "arquivo": "cad_cia_aberta.csv",
      "sha256": "8ade55aac95b7095228aebbc3ad014f16dbb6287016cce04c645fe7bb4d4db34",
      "dt_captura": "2026-07-31T15:05:50.196157-03:00",
      "publicacao": 3,
      "por_atributo": {"cnpj": "cvm_cadastro", "denom_social": "cvm_cadastro"}
    }
  }]
}
```

Uma coisa que só apareceu ao rodar contra dado real: a rota devolvia
`captura_id` e `publicado_em_versao` crus, enquanto todas as outras devolvem
proveniência decorada. Corrigido no mesmo commit.

A outra metade do aceite — chave com escopo `classe:empresa` na mesma
consulta — devolve 403 nomeando a classe que falta, e o catálogo esconde a
correlação que ela não alcança.

### Build do front

```
$ npm run build
dist/assets/apresentacao-D2T_pIa3.js   31.35 kB │ gzip:  9.17 kB
dist/assets/admin-DielUjqU.js          63.32 kB │ gzip: 15.64 kB
✓ built in 506ms
```

Verificação de tela e auditoria `axe` das etapas 4b e 7 ficaram pendentes —
ver "Precisa de você" nº 2.
