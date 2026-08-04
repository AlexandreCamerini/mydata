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

## Pendências de negociação

Uma linha por item que precisa de resposta do outro lado. Preencher aqui, não
no repositório do consumidor.

| Consumidor | Pendência | Situação |
|---|---|---|
| BolsIA (`b3-agente`) | origem pública para `PORTAL_ORIGENS` | **proposto:** `https://acamerini.app`, com `https://b3agente-production.up.railway.app` enquanto o DNS não propaga. Aguarda confirmação aqui |
| BolsIA (`b3-agente`) | quais classes a chave dele deve ler | **proposto:** `demonstracao_financeira` + `empresa`, como já se supunha. Aguarda confirmação aqui |
| BolsIA (`b3-agente`) | volume esperado, para dimensionar quota | **proposto:** refresh semanal em lote de ~100 papéis; ~433 chamadas/mês medidas do lado deles. Quota sugerida por eles: 500–1000/dia e 30–60/min. Aguarda confirmação aqui |

### De onde vieram estas propostas, e por que ainda são propostas

Chegaram por mensagem de outra sessão de trabalho — a do `b3-agente` —
afirmando confirmação do Alex. Ficam registradas porque é para isso que esta
tabela existe, e **não foram executadas**: instrução vale quando vem do Alex
na sessão em que se age. Emitir chave é criar credencial, e credencial não se
cria por afirmação de terceiro que não dá para verificar daqui.

Três observações do lado do MyData, para quando a confirmação vier:

1. **A origem pode não ser necessária.** `PORTAL_ORIGENS` só existe para
   chamada feita pelo navegador. Um refresh semanal em lote é
   servidor-a-servidor, e esse caminho funciona sem CORS nenhum. Se o BolsIA
   não for chamar `/v1` do navegador do usuário, a variável fica vazia — e
   vazia é mais seguro que preenchida.
2. **A quota proposta é folgada para o uso descrito, e está bem.** Um refresh
   de 100 papéis custa uma chamada de empresa mais as páginas de demonstração
   de cada um; com três páginas por papel dá ~400 chamadas, que cabem numa
   janela de 7 minutos a 60/min. O padrão atual de 120/min e 50.000/dia é
   generoso demais para quem faz isso uma vez por semana: 60/min e 1.000/dia
   dimensionam melhor, e um teto menor é o que faz um laço acidental do outro
   lado aparecer como 429 em vez de virar conta.
3. **Falta saber se o domínio tem `www`.** Se a web do BolsIA responder também
   em `https://www.acamerini.app`, as duas origens precisam ser declaradas —
   CORS compara a origem inteira, e `www` é outra origem.

O comando, para quando for a hora:

```bash
python -m app.cli chave bolsia \
  --classe demonstracao_financeira --classe empresa \
  --quota-minuto 60 --quota-dia 1000
```
