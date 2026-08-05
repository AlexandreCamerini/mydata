# Redesign da camada de apresentação e configuração do MyData

Você coordena o redesenho das duas superfícies visuais do MyData — a
apresentação (`/`) e a configuração (`/admin/`) — e da camada de autenticação
que as protege. O trabalho tem três fases, cada uma com entrega própria: uma
**auditoria** que estabelece o estado real, uma **direção** que decide o que o
produto vira, e uma **construção** que a executa.

O sistema está em produção e serve dado real. A ambição é de produto, não de
maquiagem: o hub tem observabilidade, linhagem, proveniência e catálogo que
hoje quase não aparecem na tela.

---

## O que existe hoje

Leia antes de opinar. O sistema já responde a boa parte do que um redesenho
costuma inventar do zero.

| Camada | Estado |
|---|---|
| Front | React 19 + Vite + TypeScript + Tailwind, build estático servido pelo FastAPI. Um serviço só no Railway |
| Telas de configuração | Gestão, Classes, Fontes, Mapeamentos, Campos calculados, Qualidade, Execuções, Carga e custo, Chaves de API, Catálogo |
| Apresentação | `/` com build próprio (`apresentacao.html`), lê `/v1` sob a sessão do dono |
| Autenticação | `PORTAL_ADMIN_TOKEN` — segredo único, digitado num formulário, cookie `HttpOnly` `SameSite=Lax` por 30 dias; cabeçalho `X-Admin-Token` para script |
| API de consumo | `/v1` com chave por consumidor, escopo por classe, quota por minuto e por dia, `ETag`, cursor |
| Classes de informação | `empresa`, `demonstracao_financeira`, `indicador_macro`, `negociacao_b3` |
| Volume real | 384.875 linhas de negociação em 25 pregões, 2,11 GB de banco, 11,9 MB de bronze |
| Observabilidade | `/v1/meta/frescor`, `/v1/meta/linhagem`, `/v1/meta/carga`, `/admin/api/execucoes/{id}/fases`, `relatorio_carga`, `log_fase` |
| Testes | 418, rodando em DuckDB e opcionalmente Postgres |

Documentos que restringem o desenho: `CLAUDE.md` (stack decidida, classe como
conceito central, engine único, regra de custo), `docs/arquitetura.md` (ADRs
10 a 18), `docs/contrato-consumidor.md`, `docs/deploy-railway.md`.

---

## Restrições que não estão em negociação

- **Nada além do que o plano do Railway já inclui.** Serviço gerenciado de
  terceiro, add-on ou tier pago precisa de aprovação explícita do Alex antes de
  entrar no código. Isso vale para autenticação, CDN, observabilidade,
  storage e qualquer biblioteca que cobre por uso.
- **Um serviço só.** O front continua sendo build estático servido pelo
  FastAPI. Separar em dois serviços é decisão de infraestrutura, não de design.
- **Classe de informação continua o conceito central.** A interface expõe
  classe, atributo, mapeamento e vista; não inventa um vocabulário paralelo.
- **Proveniência acompanha todo dado exibido.** Fonte, `sha256`, data de
  captura e publicação estão na resposta e precisam estar alcançáveis na tela.
- **A suíte fica verde.** 418 testes hoje; o número sobe, não desce.
- **Dado oficial não se toca.** O hook `PreToolUse` bloqueia escrita em bronze
  e DDL contra tabelas de captura.

---

## Fase 1 — Auditoria

Estabeleça o estado real das duas superfícies. Cobre cinco frentes, cada uma
com achados específicos e localizados no arquivo:

1. **Design e direção de arte** — sistema de cor, tipografia, espaçamento,
   densidade, hierarquia. O que é sistema e o que é improviso.
2. **UX e processo** — os fluxos que o operador realmente percorre: cadastrar
   uma fonte, diagnosticar uma carga que falhou, emitir chave, entender por
   que um número está errado. Onde cada um trava.
3. **Integração** — o que a API oferece e a tela não mostra. Comece por
   `/v1/meta/linhagem`, `/v1/meta/frescor`, `/v1/meta/carga`, `cfg_correlacao`
   e a proveniência por atributo: há capacidade construída e invisível.
4. **Acessibilidade** — contraste, foco, navegação por teclado, semântica,
   leitor de tela. Meça, não estime.
5. **Segurança da camada de acesso** — o modelo atual, suas propriedades reais
   e onde ele falha para o usuário final.

Entregue em `docs/auditoria-apresentacao.md`. Cada achado carrega: onde está
(arquivo e linha), qual é o efeito para quem usa, severidade, e esforço
estimado. Achado sem localização é opinião — não entra.

**Critério de aceite:** um leitor que não conhece o código consegue reproduzir
cada achado a partir do que está escrito.

---

## Fase 2 — Direção

Decida o que o produto vira, com as alternativas comparadas e a escolha
justificada.

### 2.1 Referências de mercado

Estude o que sistemas desta categoria fazem bem e diga o que se aproveita de
cada um — não uma lista de nomes, e sim o mecanismo que vale copiar:

- **Plataformas de dado** (catálogo, linhagem, saúde de entidade)
- **Observabilidade** (linha do tempo de execução, séries, alerta)
- **Grids de dado denso** (virtualização, coluna congelada, filtro, exportação)
- **Consoles de infraestrutura** (chave de API, escopo, quota, auditoria)

Para cada mecanismo adotado, escreva por que ele cabe *neste* produto. O que
serve a uma plataforma com mil usuários frequentemente não serve a um hub de
um dono e poucos consumidores máquina.

### 2.2 Direção de arte

O tema já é uma camada de tokens: `web/src/index.css` usa Tailwind v4 com
`@theme` e oito variáveis semânticas (`--color-tinta`, `--color-papel`,
`--color-acento`, `--color-borda`, `--color-alerta`, `--color-erro`,
`--color-ok`, `--color-tinta-suave`). Trocar direção visual é editar oito
linhas. Isso muda o processo: **não pare para perguntar.**

Defina **quatro direções distintas**, cada uma como um conjunto de tokens
nomeado. Escolha uma pelos critérios que você declarar, construa sobre ela, e
ao fim da fase 3 apresente as quatro como **capturas da interface real** — a
mesma tela, quatro paletas. O Alex escolhe olhando o produto, não uma
descrição, e trocar depois é reverter um arquivo.

Mantenha semântica no nome do token, nunca cor: `--color-alerta`, não
`--color-ambar`. Um token com nome de cor trava a paleta no código.

Evite estética genérica de IA: fontes de sistema batidas, gradiente roxo,
layout previsível. O produto tem caráter — dado financeiro auditável, com
proveniência — e a arte pode dizer isso.

### 2.3 Objetos gráficos

Especifique as classes de objeto que a interface precisa, com estado, variação
e comportamento:

- **Grid de dado** — virtualizado, coluna congelada, ordenação, filtro,
  densidade ajustável, exportação, e célula que revela proveniência
- **Painel de saúde de entidade** — por classe: frescor contra SLA, volume,
  retido no gate, última publicação, última falha
- **Mapa de integração** — como fonte, mapeamento, classe e vista se ligam, e
  onde o dado parou quando parou
- **Linha do tempo de execução** — fase a fase, com duração e o que cada uma
  produziu
- **Séries de observabilidade** — crescimento, custo, latência de carga
- **Revelação de proveniência** — o caminho de um número até o arquivo
  original, alcançável de qualquer célula

Para cada um: o dado que ele consome (endpoint existente ou endpoint novo),
os estados (vazio, carregando, erro, parcial) e o comportamento responsivo.

### 2.4 Camada de acesso

O token único é o problema declarado: é um segredo longo, digitado à mão,
igual para a apresentação e para a configuração, sem identidade, sem
expiração útil e sem revogação individual.

Compare as alternativas contra este contexto — dono único, consumidores
máquina, orçamento zero para serviço de terceiro:

| Alternativa | Avaliar |
|---|---|
| **Passkey / WebAuthn** | Nativo do navegador, resistente a phishing, sem segredo digitado, sem serviço externo. Custo: implementar registro e recuperação |
| **OIDC de provedor** | Identidade real e conhecida. Custo: dependência de terceiro, ainda que gratuita |
| **Link mágico por e-mail** | Sem segredo memorizado. Custo: precisa de serviço de envio |
| **Token melhorado** | Menor mudança. Avalie se resolve de fato o problema declarado |

**Recomendação pré-comprometida: passkey/WebAuthn.** É o único candidato que
elimina o segredo digitado sem dependência de terceiro, o que respeita a regra
de custo sem precisar de discussão. Escreva o ADR mesmo assim, com as
alternativas comparadas — se a comparação apontar outra direção, siga a
comparação e diga por quê.

**O mecanismo novo entra ao lado do token, nunca no lugar.** O token continua
funcionando até o Alex verificar o caminho novo num navegador limpo e mandar
remover. É isso que torna a decisão reversível e permite construir sem
esperar: uma escolha que se desfaz sozinha não precisa de portão.

Duas coisas obrigatórias, porque o risco desta fase é trancar o dono fora do
próprio sistema:

- **Saída de emergência:** `PORTAL_ACESSO_LEGADO=1` reabilita o caminho do
  token, documentada em `docs/deploy-railway.md`. A diferença entre reversível
  no papel e reversível às onze da noite pelo painel do Railway.
- **Recuperação:** o ADR registra o que fazer quando o autenticador se perde.

Decida com ADR novo em `docs/arquitetura.md`, no formato dos existentes:
contexto, decisão, consequência, e o que fica registrado como limite
conhecido. Trate explicitamente sessão e duração, revogação, CSRF nas rotas de
escrita, e o caminho de `curl` e script — que não tem navegador e portanto não
tem passkey.

A chave de API por consumidor em `/v1` é outra coisa e continua existindo —
diga como as duas convivem.

Entregue em `docs/direcao-apresentacao.md`, com o ADR no arquivo de
arquitetura.

**Critério de aceite:** cada decisão tem alternativa considerada e motivo
registrado. Uma decisão sem alternativa é preferência, e preferência se
declara como tal.

---

## Continuidade entre sessões

**Antes de qualquer outra coisa, leia `docs/redesign-estado.md`.** Se existir,
retome de onde ele diz; se não, crie-o na primeira etapa concluída.

Reescreva-o ao fim de cada etapa, com quatro coisas e nada mais: o que ficou
pronto, o que está em voo, o que foi decidido e por quê, e qual é a próxima
ação. Uma sessão perdida no meio da construção custa a releitura do repositório
inteiro para descobrir onde parou — e as decisões, sem esse arquivo, só existem
no histórico da conversa.

---

## Mínimo entregável

Cada fase declara, antes de começar, o que precisa estar de pé para a entrega
valer mesmo se for interrompida no meio. Trabalho parcial que não chega ao
mínimo é trabalho que o Alex não pode usar.

| Fase | Mínimo |
|---|---|
| 1 | As cinco frentes cobertas, ainda que rasas nas menos críticas. Uma frente funda e quatro vazias não serve |
| 2 | ADR da camada de acesso escrito e os quatro conjuntos de token definidos. O resto da direção pode ficar em esboço |
| 3 | Sistema de design aplicado e uma capacidade hoje invisível trazida para a tela, com teste e captura. Meia tela nova não vale |

---

## Fase 3 — Construção

Implemente a direção aprovada, em etapas com commit por etapa concluída.

Ordem sugerida, ajustável pelo que a auditoria achar: sistema de design →
objetos gráficos base → telas de configuração → apresentação → camada de
acesso. A camada de acesso vai por último de propósito: ela é a que pode
trancar o Alex fora do próprio sistema, e merece a base estável embaixo.

**Cada etapa entrega:** código, teste, e evidência de execução real — não a
afirmação de que funciona.

- Teste de front no que tem lógica (estado, formatação, condição de borda)
- Teste de API para rota nova ou mudada
- Verificação no navegador pelo painel de preview: captura de tela da mudança,
  console sem erro, e a rede confirmando o que a tela afirma
- `pytest -q` verde e `npm run build` sem erro
- `npm run a11y` sem violação séria ou crítica, **nas duas superfícies** — hoje
  o script só aponta para `/admin/`; estenda-o para `/` também

A verificação pelo navegador é obrigatória porque já pegou defeito aqui que
teste nenhum pegaria: caixa de seleção React que ignora clique sintético, e
uma nota de rodapé que atribuía a causa errada à ausência de um número.

---

## Como decidir sozinho, e quando não

Decida por conta própria: nome de componente, estrutura de arquivo, escolha
entre bibliotecas equivalentes já no `package.json`, ordem das etapas dentro
de uma fase, como testar.

Não pare para perguntar nada disso: as duas decisões que antes eram portão —
direção visual e mecanismo de acesso — foram desenhadas para se desfazerem
sozinhas. A primeira é um arquivo de tokens; a segunda entra ao lado do
caminho antigo, que continua funcionando. Decida, construa, e apresente o
resultado para revisão.

Pare de verdade em três casos: dependência nova que cobre por uso, qualquer
coisa que contrarie `CLAUDE.md` ou um ADR vigente — isso vira ADR novo antes
de virar código —, e a remoção do caminho antigo de autenticação, que só
acontece depois de o Alex verificar o novo num navegador limpo.

Entregue no escopo pedido. Se você concluir que o pedido está errado ou que
há caminho melhor, diga em uma ou duas frases e siga com o que foi pedido —
não estreite, não amplie, não transforme em silêncio. Termine a fase inteira,
não a parte fácil dela; se algo ficar bloqueado, complete o resto e diga
explicitamente o que faltou e por quê.

---

## Escalonamento de modelo

O pedido é usar capacidade máxima onde a decisão é cara e o necessário onde o
trabalho é mecânico. Traduzido em prática:

| Trabalho | Modelo | Effort |
|---|---|---|
| Auditoria, direção, ADR da camada de acesso, arquitetura de componente | `claude-opus-5` | `xhigh` |
| Implementação de tela, componente, teste, migração de estilo | `claude-sonnet-5` | `high` |
| Renomeação em massa, formatação, extração mecânica | `claude-haiku-4-5` | `low` |

Subagente com `model` no frontmatter é o mecanismo. **Delegue com parcimônia:**
subagente multiplica custo e tempo — cada um reestabelece contexto, explora de
novo e reporta, e você relê o relatório. Delegue quando o trabalho é
genuinamente independente e paralelizável, como auditar cinco frentes ao mesmo
tempo. Não delegue o que você termina em algumas chamadas de ferramenta, e não
delegue verificação — ela pertence ao laço principal. Máximo de seis
subagentes simultâneos.

---

## Comunicação

O Alex lê suas mensagens entre as chamadas de ferramenta; ele não vê seu
raciocínio nem o resultado bruto. Comece pelo desfecho — a primeira frase
depois de terminar responde "o que aconteceu" ou "o que você achou". Detalhe
e justificativa vêm depois.

Ser legível e ser breve são coisas diferentes, e legível importa mais. O jeito
de encurtar é escolher o que incluir, não comprimir a escrita em fragmentos,
setas ou jargão. Escreva em frases completas, com os termos por extenso.

Documento que você escrever tem o tamanho que o assunto pede: cubra a
substância, sem seção de enchimento, sumário redundante nem preâmbulo.
