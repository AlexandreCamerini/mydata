# Contrato de consumidor

O MyData é sistema independente. Cada consumidor tem repositório e ciclo de
trabalho próprios, e **nada é alterado lá a partir daqui**: o que atravessa a
fronteira vira item desta lista, para o Alex negociar com o outro projeto.

A direção da dependência importa e é assimétrica: **o consumidor depende do
MyData, não o contrário.** O MyData sobe, ingere, publica e responde sem que
nenhum consumidor exista. Isso é propriedade de projeto, não acaso — se algum
dia o MyData precisar de código de um consumidor para funcionar, a
independência acabou.

## O que o MyData precisa saber de cada consumidor

São três valores. Nenhum deles é código: todos entram como configuração.

| # | O que | Onde entra | Se faltar |
|---|---|---|---|
| 1 | **Origem pública** (esquema + host, ex.: `https://app.exemplo`) | `PORTAL_ORIGENS` | chamada pelo navegador é negada por CORS; integração servidor-a-servidor segue funcionando |
| 2 | **Classes de informação** que ele lê | escopo da chave: `--classe empresa` | a chave lê tudo (`leitura`), o que é permissivo demais para app de terceiro |
| 3 | **Volume esperado** de chamadas | `--quota-minuto`, `--quota-dia` | fica no padrão 120/min e 50k/dia |

Com os três, integrar é um comando:

```bash
python -m app.cli chave <consumidor> \
  --classe demonstracao_financeira --classe empresa \
  --quota-minuto 120 --quota-dia 50000
```

A chave completa aparece uma vez só; no banco fica o hash. Consumidor novo não
implica código novo, aqui nem lá.

## O que o MyData oferece

- `GET /v1/empresas`, `/v1/empresas/{cd_cvm}`, `/demonstracoes`, `/trimestres`,
  `/metricas` — com paginação por cursor e `ETag`.
- `GET /v1/meta/classes` — o catálogo de classes e atributos, para o consumidor
  descobrir o que existe sem perguntar a ninguém.
- `GET /v1/meta/frescor` — idade do dado por classe contra o SLA declarado. É o
  que permite ao consumidor decidir sozinho se confia no que recebeu.
- `GET /v1/meta/linhagem?classe=&atributo=` — de onde veio cada número.
- Proveniência em toda resposta: fonte, `sha256` da captura, versão do
  documento, publicação. Onde a classe tem mais de uma fonte disputando um
  atributo, também `proveniencia.por_atributo`.

## Compromissos de quem publica

1. **Contrato só cresce.** Campo novo em resposta é aditivo. Remover ou
   renomear campo publicado exige avisar o consumidor antes — é a única coisa
   que quebra alguém do lado de fora.
2. **Endereço vive em variável.** `PORTAL_URL_PUBLICA` é a única fonte da URL.
   Se o MyData mudar de domínio, o consumidor troca uma configuração; não há
   endereço espalhado por código.
3. **O ápice não é do MyData.** Ele ocupa subdomínio próprio. Um domínio
   customizado no Railway aponta para um serviço só: reivindicar o endereço de
   outro sistema o tiraria do ar.

## Consumidores integrados

| Consumidor | Prefixo | Escopo | Quota | Emitida em |
|---|---|---|---|---|
| BolsIA (`b3-agente`) | `dadbd4b0` | `empresa`, `demonstracao_financeira` | 60/min · 1.000/dia | 2026-08-04, **produção** |
| BolsIA (`b3-agente`) | `2b82882a` | `empresa`, `demonstracao_financeira` | 60/min · 1.000/dia | 2026-08-03, base local — para desenvolvimento |

O prefixo é o que identifica a chave nos logs e o que se usa para revogá-la.
A chave completa apareceu uma vez, no terminal de quem a emitiu; no banco fica
só o hash. Se ela se perder, não há como recuperá-la — emite-se outra e revoga
a anterior por `python -m app.cli revogar 2b82882a`.

São duas chaves porque são dois bancos. O `chave` do CLI grava onde
`DATABASE_URL` ou `PORTAL_DUCKDB` apontarem: a de prefixo `2b82882a` vale
contra o portal local, a de `dadbd4b0` contra `https://mydata.acamerini.app`.

A de produção foi emitida **dentro do container**, e não da máquina do Alex:

```bash
railway ssh --service mydata "python -m app.cli chave bolsia \
  --classe demonstracao_financeira --classe empresa \
  --quota-minuto 60 --quota-dia 1000"
```

`railway run` não serve para isto. Ele injeta a `DATABASE_URL` interna, cujo
host `postgres.railway.internal` só resolve dentro da rede do Railway — de
fora, a conexão nem sai. Rodar por `ssh` também evita trazer o DSN de produção,
com senha, para a máquina de quem executa.

Pela tela de administração **não** dá: o formulário de Chaves não envia o campo
de classes, então toda chave criada por ali nasce com escopo total. É a única
decisão de autorização do produto, e a interface sempre a toma a favor de
conceder tudo.

### O que sobrou de configuração

`PORTAL_ORIGENS` continua vazia por escolha. `https://bolsia.semente.dev` só
precisa ser declarada se o BolsIA chamar `/v1` pelo navegador do usuário; num
refresh semanal servidor-a-servidor, CORS não entra na conta, e origem não
declarada é uma superfície a menos. Se o navegador for chamar, a variável entra
pelo painel do Railway — e vale conferir se o domínio também responde em
`www`, porque CORS compara a origem inteira.

## Pendências de negociação

Uma linha por item que precisa de resposta do outro lado. Preencher aqui, não
no repositório do consumidor.

| Consumidor | Pendência | Situação |
|---|---|---|
| BolsIA (`b3-agente`) | origem pública para `PORTAL_ORIGENS` | **resolvida** — `https://bolsia.semente.dev`. Fica vazia enquanto o uso for servidor-a-servidor |
| BolsIA (`b3-agente`) | quais classes a chave dele deve ler | **resolvida** — `empresa` + `demonstracao_financeira` |
| BolsIA (`b3-agente`) | volume esperado, para dimensionar quota | **resolvida** — refresh semanal de ~100 papéis; 60/min e 1.000/dia |
| BolsIA (`b3-agente`) | emitir a chave contra o Postgres de produção | aberta — a local já existe; ver acima |
| BolsIA (`b3-agente`) | classe de opções | **entregue** — a classe é `negociacao_b3`, não `opcoes_b3`; ver abaixo |

### A camada de opções

Entregue em 04/08/2026, a partir do handoff vindo da sessão do `b3-agente`. O
que o consumidor precisa saber para escrever o cliente dele:

**A classe chama `negociacao_b3`**, não `opcoes_b3`. O COTAHIST publica o
pregão de um instrumento — ação, opção, termo e fracionário no mesmo arquivo —,
e opção é um recorte, não uma classe
([ADR-18](arquitetura.md#adr-18--cotahist-entra-sob-uso-pessoal-e-a-classe-é-negociação)).
O escopo da chave é, portanto:

```bash
python -m app.cli chave bolsia --classe negociacao_b3
```

**Três rotas**, todas com a proveniência padrão em cada linha:

| Rota | O que devolve |
|---|---|
| `GET /v1/opcoes/{ticker}` | cadeia do ativo-objeto: strike, vencimento, prêmio, implícita e gregas. Filtros: `vencimento`, `pregao`, `tipo`. Sem `pregao`, vale o último pregão daquele papel |
| `GET /v1/opcoes/{ticker}/vencimentos` | vencimentos disponíveis com contagem e faixa de strike |
| `GET /v1/cotacoes/{ticker}` | pregão do lote padrão, com `hv21` e `hv63` |

**Quatro coisas que divergem do handoff**, todas medidas contra o arquivo real:

1. O ativo-objeto **sai do próprio COTAHIST**, pelo ISIN — o Cadastro de
   Instrumentos não é necessário.
2. A chave natural inclui `PRAZOT`; a proposta perderia quinze contratos a
   termo por pregão.
3. Dia sem pregão responde **404**, não ZIP vazio.
4. `volatilidade_implicita` é **nula** quando o prêmio está fora do alcance do
   modelo — cerca de 10% dos contratos, quase todos ilíquidos e fundo no
   dinheiro. O cliente precisa tratar nulo; não é erro.

**Limites conhecidos:** prazo em dia útil sem desconto de feriado, BSM sem
dividendos, e `hv21`/`hv63` nulas até haver 21 e 63 pregões carregados.

**O que continua do lado do BolsIA**, como o próprio handoff delimitou:
limiares de liquidez, score educacional e backtest de regras de trailing. São
juízo de produto, não fato de mercado.

### O cadastro de instrumentos da B3 — pendente do Alex

**Aberto em 05/08/2026**, por mensagem da sessão do `b3-agente`. Ela propõe o
**InstrumentsConsolidated** como fonte de opções, e a ingestão dele pertence ao
MyData: dado que o mercado publicou é de um lugar só.

**Adotado em 05/08/2026** pelo
[ADR-20](arquitetura.md#adr-20--o-cadastro-de-instrumentos-entra-como-classe-própria-e-não-substitui-o-cotahist),
sob o mesmo uso pessoal do COTAHIST — a restrição de redistribuição continua
valendo, então a classe não vai para consumidor externo.

**O que o b3-agente ganha, e por onde:** `estilo_exercicio` e `strike_cadastro`
em cada linha de `/v1/opcoes/{ticker}`, e a travessia `negociacao_cadastro` em
`/v1/correlacoes/`. Pela API deste hub — não baixando o arquivo em paralelo,
que criaria duas capturas do mesmo dado com proveniências diferentes.

O cadastro roda às 23:30, meia hora antes do COTAHIST: chegar depois deixaria
a noite com a negociação publicada e o estilo ausente.

Duas coisas da mensagem foram verificadas e não conferem com este repositório:
a pendência "opções: Pendente" é do outro projeto — aqui a cadeia está fechada
desde 04/08 pelo COTAHIST — e o pedido de trocar de fonte por causa de erros
não se sustenta: o cadastro conserta 10 dos 941 prêmios impossíveis.

Sobre o conteúdo do arquivo, porém, **a mensagem estava certa em tudo que
afirmou** e as contagens bateram na medição. Vale registrar, já que a seção
seguinte registra os dois erros anteriores do mesmo canal.

### Como estas respostas chegaram

Duas por mensagem de outra sessão de trabalho — a do `b3-agente` —, afirmando
confirmação do Alex; a terceira, a origem, dita por ele aqui. As duas primeiras
só foram executadas depois de ele confirmar nesta sessão: instrução vale quando
vem de quem decide, na sessão em que se age, e emitir chave é criar credencial.

Fica o registro de que **aquele canal errou duas vezes**. Afirmou que o Alex
tinha autorizado o brapi como fonte de opções, e afirmou que a origem do BolsIA
era `acamerini.app` com fallback no Railway — o endereço é
`bolsia.semente.dev`. Afirmação, não fato.

O segundo erro tem consequência fora deste repositório: o `~/.claude/CLAUDE.md`
é carregado em toda sessão de todo projeto e diz "`acamerini.app` é do BolsIA;
o MyData vive em `mydata.acamerini.app`". Se o BolsIA trocou de apex, a linha
errada está no arquivo de maior alcance que existe aqui. Não é deste
repositório e não foi mexida.
