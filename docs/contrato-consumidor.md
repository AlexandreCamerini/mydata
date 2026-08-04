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
| BolsIA (`b3-agente`) | `2b82882a` | `empresa`, `demonstracao_financeira` | 60/min · 1.000/dia | 2026-08-03, base local |

O prefixo é o que identifica a chave nos logs e o que se usa para revogá-la.
A chave completa apareceu uma vez, no terminal de quem a emitiu; no banco fica
só o hash. Se ela se perder, não há como recuperá-la — emite-se outra e revoga
a anterior por `python -m app.cli revogar 2b82882a`.

**Esta chave vale na base local.** O `chave` do CLI grava onde `DATABASE_URL`
ou `PORTAL_DUCKDB` apontarem, e daqui só se alcança a base de desenvolvimento.
A chave que o BolsIA vai usar contra `https://mydata.acamerini.app` precisa ser
emitida contra o Postgres de produção:

```bash
railway run python -m app.cli chave bolsia \
  --classe demonstracao_financeira --classe empresa \
  --quota-minuto 60 --quota-dia 1000
```

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
