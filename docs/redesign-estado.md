# Estado do redesenho

Leia este arquivo antes de qualquer outra coisa. Reescreva-o ao fim de cada
etapa concluída.

**Atualizado:** 02/09/2026 — retomado o redesenho Airbyte/Digibee que tinha
ficado só no artefato: vocabulário, direção A, direção C e direção B.

## Pronto

- **Prompt corrigido** (`b3726c3`) — as cinco mudanças da proposta.
- **Fase 1 — auditoria** (`docs/auditoria-apresentacao.md`, `bfc6e17`). Onze
  achados localizados, cinco frentes, acessibilidade medida.
- **Fase 2 — direção e ADR-19** (`docs/direcao-apresentacao.md`, `f6047ba`).
- **Etapa 1** (`b3b8356`) — acento vivo, `temas.css`, `a11y` nas duas telas.
- **Etapa 2** (`c583ae7`) — erro de API humanizado, com guarda contra o laço.
- **Etapa 3** (`270d42a`) — a tela de `negociacao_b3`, grid virtualizado.
- **Runner de teste** (`7df22e4`) — `vitest`, e os dois defeitos virados
  regressão.
- **Etapa 5** (`536ffeb`) — `SaudeClasse`, `Linhagem`, `LinhaDoTempo` e
  `Serie`; achados 2.1, 2.2, 3.2 e 2.4 fechados.
- **Etapa 6** — a camada de acesso do ADR-19. Passkey ao lado do token.

## Em voo

Nada. As seis etapas da ordem em `docs/direcao-apresentacao.md` estão feitas.

## Decidido, e por quê

- **Sem deploy em produção durante a execução.** Tudo commitado no branch e
  verificado localmente. O Alex sobe depois de olhar.
- **Objeto recebe dado por prop; quem busca é a tela.** Há dois módulos `api`
  neste front, um por bundle.
- **Linhagem e correlações ganharam espelho em `/admin/api`.** Tentei antes
  presumir sessão de dono sem `PORTAL_ADMIN_TOKEN`, e um teste mostrou que
  aquilo abriria `/v1` em qualquer instalação sem token de admin.
- **A sessão deixou de ser o token e virou identificador opaco**, com linha em
  `sessao_admin`. É o que dá as três coisas que faltavam ao §5.2: identidade,
  revogação individual e expiração real. O cookie no formato antigo continua
  aceito — um cookie já emitido não pode parar de valer no deploy.
- **O desafio do WebAuthn mora no servidor**, em tabela. Em cookie, quem ataca
  escolheria o valor e a proteção contra repetição cairia junto.
- **Registrar exige sessão; entrar não.** Sem isso qualquer visitante
  registraria o próprio autenticador e viraria dono — é o papel que o token
  conserva.
- **`X-Admin-Token` nunca passa pelo portão da tela.** Vale sempre. É por ele
  que se revoga o autenticador perdido.

## Verificado nesta etapa

- Ciclo inteiro do passkey, com um autenticador de software escrito em
  `tests/autenticador.py` — chave ECDSA P-256, `authenticatorData` montado
  byte a byte. Sem ele, a parte que decide quem entra iria para produção sem
  nunca ter rodado, porque o gesto não acontece fora do navegador.
- Os quatro casos negativos passam pelo motivo certo: assinatura de outra
  chave, assertiva repetida, origem trocada, credencial revogada.
- Pelas rotas HTTP do servidor no ar: registro, entrada, sessão com origem
  `passkey:notebook de verificação`, contador subindo.
- Na tela: sem passkey, só o formulário de token; com passkey, só o botão;
  com `PORTAL_ACESSO_LEGADO=1`, os dois. O clique sem autenticador diz
  "Autenticação cancelada" e não "erro" — `NotAllowedError` é o gesto
  cancelado, não falha do portal.
- 457 testes Python, 35 no front, `tsc` limpo, `axe` com zero violação em
  sete superfícies, incluindo os dois estados da tela de entrada.
- O que a verificação registrou no banco de demonstração foi apagado.

## O backlog da auditoria, fechado

**05/08/2026 — os onze achados estão fechados.** Os três últimos:

- **1.3** — a chave de identidade era uma corrida de oito atributos separados
  por vírgula. Virou lista ordenada de partes; `<ol>` e não conjunto, porque a
  ordem é a do índice único.
- **3.4** — `/v1/meta/contrato` existia desde a etapa 7 e nenhuma tela o lia.
  Ganhou leitor na tela de Classes, mostrando a regra de qualidade pela
  **consequência** e não pela severidade nominal.
- **1.2** — a escala tipográfica. Medido antes de mexer: 175 `text-xs`, 89
  `text-sm`, 11 em tudo o mais, e `h2` a 16 px porque nenhum componente lhe dava
  tamanho. Declarada em `@theme`, com entrelinha e `tracking` por degrau, em vez
  de reescrever 264 classes.

## O redesenho Airbyte/Digibee, retomado

**02/09/2026 — o artefato "segunda rodada" (vocabulário + três direções
inspiradas em Airbyte/Digibee) nunca tinha virado código.** Achado ao
comparar o branch com um artefato que o Alex mandou depois — grep no
histórico inteiro não achava "Airbyte", "Digibee" nem "Conexões" em lugar
nenhum. Mapeamento de viabilidade contra o backend real corrigiu a ordem que
o próprio artefato sugeria: vocabulário não é grátis (`atributo`, `janela`,
`precedencia`, `bronze/silver/gold` são nome de campo no JSON de `/v1` e
`/admin/api`, não só rótulo de tela), então virou tradução só na
apresentação, sem tocar contrato. As quatro peças:

- **Vocabulário** — "Classes"→"O que você guarda", "Mapeamentos"→"Conexões",
  "atributo"→"campo", "precedência"→"quem manda".
- **Direção A (cards de conexão)** — `Datasets.tsx` virou grade de cards com
  os 5 estados fixos (No ar/Falhou/Atualizando/Pausada/Nunca rodou), linhas e
  idade — tudo sobre `GET /execucoes?dataset=X&limite=6`, que já existia.
- **Direção C (precedência arrastável)** — em `ClasseForm.tsx`, texto livre
  virou lista com setas, restrita às conexões que de fato alimentam o campo.
  É a correção do defeito real que a auditoria já tinha citado (fonte
  inexistente digitada por engano).
- **Direção B (assistente de conexão nova)** — a única que exigia backend
  novo. `previa_arquivo()` em `app/motor/ingestao.py` baixa a fonte agora
  (reaproveitando `_urls_da_janela`/`_com_credencial`/`membros_do_zip`, sem
  duplicar o pipeline de carga real) e `parsing.previa_csv()` lê cabeçalho +
  amostra sem mapeamento — o que faltava para mostrar o arquivo real antes
  de ligar um campo. Cobre `http_csv` e `http_zip`; `http_json`/`http_token`
  a tela pula a etapa e volta ao mapeamento digitado. Testado contra o
  servidor real da CVM (`dados.cvm.gov.br`, DFP 2023) — colunas e amostra
  batendo com dado de produção.

Verificado: 513 testes Python (7 novos, incluindo o endpoint HTTP), `tsc`
limpo, 38 testes de front, `npm run a11y` — 21 páginas + o passo mais
arriscado do assistente (inputs crus de ligação de campo) verificado à parte
com `axe-core` injetado — 0 violação em tudo.

## Achados 12 e 13, fora dos onze da auditoria

**02/09/2026 — dois gaps achados numa revisão de aderência aos 66 commits
que vieram depois do achado 8.** Drift mínimo: quase tudo se auto-corrigiu
(`ui.tsx` e `COR_METODO` de `Api.tsx` trocaram classe Tailwind crua por
token em `510f612`/`bd0574f`). Sobraram dois.

- **12 — `Api.tsx` deixava erro de rede cru vazar.** Os dois `catch` da tela
  (carregar `/openapi.json`, executar uma rota) jogavam
  `(e as Error).message` direto no componente `<Erro>` — um
  `TypeError: Failed to fetch` apareceria em inglês, cru do motor JS, onde
  toda outra tela do portal passa por `pedir()` em `api.ts` e mostra erro em
  português. A tela usa `fetch` cru de propósito, para exibir a resposta
  HTTP real — isso não muda. O que muda é a falha *antes* de existir
  resposta: `mensagemDeFalha()` intercepta só `TypeError` e devolve "Não foi
  possível alcançar a rota — confira a conexão."; qualquer outro erro
  mantém a mensagem original.
- **13 — o portão de `a11y` ficou para trás.** Aberto desde 05/08 ("a
  apresentação passa, mas passa sem estar no portão", achado 4 acima) e
  cresceu: a aba nova `#/api` e as rotas de apresentação nunca tinham
  entrado no script. De 6 URLs (4 abas de admin) para 21 — as 12 abas de
  admin inteiras mais 7 rotas de apresentação (`empresa`, `ficha`,
  `demonstracoes`, `indicadores`, `arquivos`, `negociacao`, `operador`),
  usando `cd_cvm 9512` (Petrobras — o mesmo que os fixtures de teste já
  usam) e `PETR4`. Rodado contra o servidor real (`scripts/servidor.py
  subir`, build atual): **21 páginas, 0 violações.**

## O que continua faltando

- **Testar num aparelho de verdade.** O autenticador de software cobre o que o
  servidor confere; não cobre biometria, presença de usuário real nem atestado
  de fabricante. É o passo do Alex, e é o que o ADR-19 chama de "verificar num
  navegador limpo" antes de mandar remover o token.
- **Qual das quatro direções visuais fica.** `web/src/temas.css`, oito linhas.
- **Subir.** O branch está à frente de `origin/main`.
