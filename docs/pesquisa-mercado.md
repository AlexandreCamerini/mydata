# Pesquisa de mercado

Sete questões, pesquisadas na web com fonte citada, para fechar decisões do
plano de implantação. Cada seção termina em **Decisão:**.

Realizada em 2026-08-02 por quatro agentes em paralelo. Onde a pesquisa não
fechou, está escrito que não fechou — estimativa disfarçada de fato é o que
esta pesquisa existe para evitar.

## O que mudou o plano

Três achados alteram decisões já tomadas:

1. **A B3 veda redistribuição.** O COTAHIST não pode virar classe pública. A
   etapa 5 troca de fonte: entra o Banco Central, que é dado aberto de verdade.
   Ver Q4.
2. **A CVM pode ser republicada**, citando a fonte, sem vedação comercial que a
   pesquisa tenha encontrado. O núcleo do MyData está liberado. Ver Q3.
3. **Nenhum concorrente, pago ou grátis, entrega proveniência por número.** O
   diferencial não é hipótese — é lacuna medida em onze provedores. Ver Q1 e Q2.

E um alerta que atinge a etapa 8: a classe `empresa` já tem atributos vindos da
B3 (`ticker`, `segmento_listagem`). Uso interno está amparado; publicá-los numa
API pública, não. Precisa de decisão antes de abrir.

---

## Q1 — Provedores pagos

| Provedor | O que entrega | Preço público | Proveniência auditável? |
|---|---|---|---|
| **Economatica** | ~5.000 empresas, 27.000+ fundos, dados da CVM e internacionais; sem API pública documentada | não publicado; relato de fórum de 2019 menciona ~R$2.450/mês — não confirmado | não confirmado |
| **Comdinheiro** | 100.000+ séries diárias, 300+ indicadores, API documentada em PDF | Basic+ R$249,90/mês, ou R$199,90 no anual | não confirmado |
| **Quantum Axis** | 1.700+ empresas, demonstrações, indicadores, API institucional | sob consulta | não confirmado |
| **TradeMap Pro** | 40+ indicadores, histórico 10+ anos; plataforma de varejo, sem API | Free R$0 · Prime R$54,20/mês · Pro R$349,90/mês | não confirmado |
| **StatusInvest** | fundamentos, DRE, fluxo de caixa; sem API oficial, só scraping de terceiro | plano pago, valor não coletado | não confirmado |

Todos afirmam usar "fontes oficiais" em nível de marketing. Nenhum documento
consultado — site, FAQ ou PDF de API — descreve rastreamento
número → documento → versão. Nenhum entrega o equivalente a *"este valor veio
da DFP protocolo X, versão Y, capturada em Z"*.

Fontes: [forum.penserico.com](https://forum.penserico.com/t/economatica-vale-a-pena/2642),
[comdinheiro.com.br](http://www.comdinheiro.com.br/?lang=pt&pag=comdinheiro-light),
[DocumentacaoAPI.pdf](https://www.comdinheiro.com.br/Download/DocumentacaoAPI.pdf),
[quantumfinance.com.br](https://quantumfinance.com.br/solucao/quantum-axis/),
[trademap.com.br/planos](https://trademap.com.br/planos).

**Decisão:** manter bronze imutável com SHA-256 e proveniência por atributo como
está. Nenhum provedor pago pesquisado oferece equivalente, então não há
arquitetura de concorrente a copiar aqui.

## Q2 — Gratuitos e freemium

| Provedor | Limite grátis | Cobertura | Token? | Proveniência por documento? |
|---|---|---|---|---|
| **brapi.dev** | 15.000 req/mês (402 ao exceder); 4 tickers livres sem token | grátis: cotação com ~30min de atraso, histórico ~3 meses. Pago (R$99,99–116,66/mês): 15+ anos, fundamentos desde 2009 | sim, exceto os 4 | cita CVM/BCB/Tesouro como fontes gerais; **não** por número |
| **Dados de Mercado** | token obrigatório; limite grátis não publicado | preços, fundamentos, risco, fundos, títulos, macro | sim | nomeia CVM, BCB, Anbima, B3 — o mais transparente do grupo, ainda assim só em nível de sistema |
| **Fundamentus** | sem token, sem limite publicado | indicadores, séries de preço ajustado desde 1998, balanços em Excel | não | fonte não declarada |
| **StatusInvest** | sem cadastro para o básico; sem API oficial | fundamentos, DRE, fluxo, balanço | não | não confirmado |
| **yfinance (.SA)** | sem limite oficial — scraping não-oficial do Yahoo, sujeito a bloqueio | preço histórico amplo; fundamentos BR inconsistentes | não | não — passa pelo Yahoo, sem ligação à CVM |
| **Fintz** | não confirmado | anunciada como market data BR | não confirmado | não confirmado |

Mesmo o mais transparente declara a fonte em nível de sistema, nunca de dado.
Nenhum expõe *"este número veio do arquivo X, hash Y, capturado em Z, versão
retificadora W"*.

Fontes: [brapi.dev/faq/tem-algum-limite](https://brapi.dev/faq/tem-algum-limite),
[brapi.dev/pricing](https://brapi.dev/pricing),
[dadosdemercado.com.br/api/docs](https://www.dadosdemercado.com.br/api/docs),
[fundamentus.com.br](https://www.fundamentus.com.br/).

**Decisão:** usar brapi (15k/mês) e Dados de Mercado como referência de quota e
de onboarding ao desenhar o tier grátis, e tratar `fonte`, `dt_captura`,
`versao_documento` e `publicacao` na resposta como o diferencial declarado —
ausência confirmada em todos os cinco.

## Q3 — CVM Dados Abertos: redistribuição

O portal se apresenta sob a Lei 12.527/2011 e o Decreto 8.777/2016, que define
dado aberto como disponibilizado "sob licença aberta que permita sua livre
utilização, consumo ou cruzamento, limitando-se a creditar a autoria ou a
fonte" ([Decreto 8.777/2016, Art. 2º, III](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2016/decreto/d8777.htm)).

O metadado do dataset de DFP declara licença **ODbL** (Open Data Commons)
([dados.cvm.gov.br/dataset/cia_aberta-doc-dfp](https://dados.cvm.gov.br/dataset/cia_aberta-doc-dfp)).

O termo de uso do portal exige atribuição:

> O usuário, ao utilizar de qualquer forma a informação obtida (uso secundário)
> deverá citar a fonte dos dados obtidos, declarando que eles foram acessados
> pelo Portal de Dados Abertos da CVM
> — [dados.cvm.gov.br/about](https://dados.cvm.gov.br/about)

E isenta a CVM de garantia de continuidade e tempestividade. Nenhuma vedação a
uso comercial foi encontrada, nem no termo nem no decreto.

**Decisão:** republicar dado da CVM está amparado, condicionado a **citar a
fonte em toda resposta e na página pública** — o que a proveniência já faz. Fica
uma pendência real antes de abrir ao público: ler o texto integral da ODbL para
saber se a cláusula de *share-alike* alcança a API derivada, e qual licença
declarar para ela. Isso é leitura de licença, não parecer jurídico.

## Q4 — B3, séries históricas: redistribuição

Os Termos de Uso do site da B3 são restritivos, e a página de download do
COTAHIST não traz regime próprio — submete-se a eles:

> Os visitantes deste website podem utilizar os dados disponíveis nessas páginas
> para uso exclusivamente pessoal

> É vedada a utilização dos dados contidos neste website para fins comerciais
> salvo mediante autorização prévia e por escrito da B3

> É vedada a distribuição, redistribuição, transferência, transmissão,
> retransmissão, licença, sublicença, locação, empréstimo, venda, revenda,
> recirculação, reformatação, publicação [...] a terceiros

— [b3.com.br/termos-de-uso](https://www.b3.com.br/pt_br/termos-de-uso-e-protecao-de-dados/termos-de-uso/)

Há uma exceção, mas dentro do ecossistema contratual de distribuidores: dados de
fim de dia e históricos a partir de D-1 obtidos pelas Plataformas de Market Data
"podem ser distribuídos sem custo pelos distribuidores ou redistribuidores sem a
necessidade de autorização prévia"
([FAQ de distribuidores](https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/distribuidores/perguntas-frequentes/)).
Não foi confirmado se isso alcança quem apenas baixa o arquivo público.

Nas três situações pedidas:

| Situação | Leitura |
|---|---|
| (a) baixar e usar internamente | amparado por "uso exclusivamente pessoal" |
| (b) publicar derivado ou agregado | sem cláusula que autorize; "reformatação" e "publicação" estão na vedação |
| (c) republicar o dado bruto | vedado sem autorização prévia e escrita |

**Decisão: o COTAHIST não entra como classe pública.** A etapa 5 troca de fonte
— entra o Banco Central, que é dado aberto. Preço fica pendente de decisão do
Alex: falar com a B3, ou aceitar uso interno apenas. Isto é leitura dos termos,
não parecer jurídico.

## Q5 — Proteção de custo em API pública gratuita

O padrão dominante são dois degraus: um nível anônimo minúsculo que serve para
provar que funciona, e uma chave grátis por auto-serviço com limite 15 a 80
vezes maior, sem humano no meio.

| API | Anônimo | Com chave | Emissão |
|---|---|---|---|
| GitHub REST | 60 req/hora por IP | 5.000/hora | OAuth/PAT, exige conta |
| NASA / api.data.gov | `DEMO_KEY`: 30/hora, 50/dia por IP | 1.000/hora | formulário → chave por e-mail, sem aprovação |
| OpenWeatherMap | — | 60/min, ~1.000/dia | cadastro de e-mail |
| Nominatim/OSM | 1 req/s, política em vez de quota | — | não emite chave; identifica por IP + User-Agent |
| Portal da Transparência | exige token | 400/min (06h–24h), 700/min (00h–06h); excesso suspende 8h | login gov.br com 2FA |

Fontes: [GitHub rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api),
[api.data.gov developer manual](https://api.data.gov/docs/developer-manual/),
[Portal da Transparência](https://portaldatransparencia.gov.br/api-de-dados),
[política do Nominatim](https://operations.osmfoundation.org/policies/nominatim/).

**Cabeçalhos.** Dois padrões coexistem: o de facto (`X-RateLimit-Limit`,
`-Remaining`, `-Reset`) e o do IETF (`RateLimit`, `RateLimit-Policy`). O draft
`draft-ietf-httpapi-ratelimit-headers` está na **versão -11, de 23/05/2026, e
ainda é Internet-Draft — não é RFC**
([datatracker](https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/)).
`Retry-After` é o único dos três com padrão fechado (RFC 9110).

**IP atrás de proxy.** `X-Forwarded-For` é forjável pelo cliente. Só vale o
header que a borda de confiança escreve. Qual header o edge do Railway popula
não foi confirmado — precisa de verificação em produção.

**Cache.** Para dado de cadência diária, `Cache-Control` evita a chamada, e a
requisição condicional que sobra devolve `304` com corpo vazio: um recurso de
50 KB vira ~200 bytes, cerca de 99,6% menos banda. Não reduz a contagem de
requisições, mas elimina query e serialização.

**Degradação.** Dois níveis, complementares: o Railway tem *Usage Limits* com
teto rígido configurável (mínimo US$10/ciclo) que **desliga tudo** ao atingir,
com alertas em 75/90/100%
([docs.railway.com/pricing/cost-control](https://docs.railway.com/pricing/cost-control));
e o teto de aplicação, que devolve 429/503 antes de chegar lá — o princípio é
que um 503 em 5 ms vale mais que um 200 em 30 s.

**Decisão** — o desenho para a etapa 8:

| Item | Valor |
|---|---|
| Anônimo | 60 req/hora por IP, como o GitHub |
| Chave grátis | 1.000 req/**dia** — o dado muda uma vez por dia, e não há motivo legítimo para poll mais denso |
| Emissão | auto-serviço com e-mail verificado, sem aprovação manual; hash em repouso, escopo por classe, como o CLI já faz |
| Cabeçalhos | `RateLimit-*` do draft **e** `Retry-After` em todo 429/503 |
| Cache | `Cache-Control: public, max-age=3600, stale-while-revalidate=86400` e `ETag` a partir da digital de gold que `app.cli verificar` já produz |
| Degradação | limitador global devolvendo 503 com `Retry-After` antes do teto do Railway |
| Rede final | Usage Limit no Railway com alerta em 75% — decisão de valor é do Alex |

## Q6 — Contrato de dado publicado

**ODCS** (Bitol / Linux Foundation) é um YAML com `schema` (propriedades com
`logicalType` agnóstico e `physicalType` do motor), `quality`, `slas`,
`servers`, `team` e `support`. Separa `apiVersion` — versão do padrão — de
`version` — versão semver do próprio contrato
([bitol-io/open-data-contract-standard](https://github.com/bitol-io/open-data-contract-standard/blob/main/docs/README.md),
[v3.1.0](https://bitol-io.github.io/open-data-contract-standard/v3.1.0/)).

**dbt `contracts`** é bem mais estreito: só schema, com `name` + `data_type` e
`constraints`. Não carrega qualidade, SLA nem proveniência. Versionamento é
recurso à parte (`versions:`), e quebra de contrato força versão nova em vez de
edição silenciosa
([contract config](https://docs.getdbt.com/reference/resource-configs/contract),
[versions](https://docs.getdbt.com/reference/resource-properties/versions)).

**Decisão:** `/v1/meta/contrato` como **subconjunto do ODCS**, montado de
`cfg_*` em vez de gravado à parte — contrato guardado seria segunda declaração
do mesmo fato, livre para divergir da configuração que roda. Campos ODCS onde
mapeiam; `customProperties` para o que nenhum dos dois padrões cobre: duas
fontes disputando o mesmo atributo. Nem ODCS nem dbt têm conceito para isso.

Lacuna assumida: `version` é o inteiro monotônico da configuração, não semver —
ele sobe em qualquer mudança, quebrando ou não. Distinguir quebra exigiria
comparar schemas entre versões, e não há caso concreto que pague isso hoje.

## Q7 — Correlação declarada entre entidades

**Cube** declara junção explícita, com condição SQL e `relationship`
(`one_to_many`, `many_to_one`, `one_to_one`). Exige `primary_key` em cada cubo
para não duplicar no fan-out, e monta um grafo: sem caminho declarado, a API
recusa com *"Can't find join path"*; com caminhos múltiplos, exige `join_path`
explícito. Nunca infere junção não modelada
([Cube — joins](https://cube.dev/docs/product/data-modeling/reference/joins)).
Acesso por cubo usa `securityContext` com `public` calculado em tempo de
compilação — quem não tem o claim não enxerga o cubo
([access control](https://docs.cube.dev/docs/data-modeling/access-control/context)).

**MetricFlow (dbt)** faz o oposto: junção implícita por `entities` tipadas.
Casa entidades de mesmo nome e decide pelo tipo — `primary↔primary`,
`primary↔unique` e `unique↔unique` passam; `primary↔foreign` e
`foreign↔foreign` são recusados por gerarem fan-out ou chasm join, e a
validação roda em compilação, então correlação sem sentido nunca vira SQL
([join logic](https://docs.getdbt.com/docs/build/join-logic)).

**Decisão:** explícita, como o Cube — as classes já têm chave de identidade
declarada, e a proveniência multi-fonte já exige explicitação em vez de
inferência. Nova `cfg_correlacao` com classe de origem e destino, atributos de
ligação e tipo de relacionamento; o motor recusa junção sem linha
correspondente. Do MetricFlow, tomar a validação por tipo de chave, para
recusar na configuração a combinação que produziria fan-out. O escopo da chave
de API se aplica à travessia como no Cube: chave sem escopo na classe de destino
recebe negativa, nunca colunas incluídas em silêncio.
