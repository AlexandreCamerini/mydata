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
| BolsIA (`b3-agente`) | origem pública para `PORTAL_ORIGENS` | a definir — depende de onde a web do BolsIA será servida |
| BolsIA (`b3-agente`) | quais classes a chave dele deve ler | provável `demonstracao_financeira` + `empresa`; confirmar |
| BolsIA (`b3-agente`) | volume esperado, para dimensionar quota | a definir |
