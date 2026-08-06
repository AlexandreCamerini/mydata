# Estado do redesenho

Leia este arquivo antes de qualquer outra coisa. Reescreva-o ao fim de cada
etapa concluída.

**Atualizado:** 05/08/2026 — fim da fase 3. Todas as etapas construídas.

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

## O que continua faltando

- **Testar num aparelho de verdade.** O autenticador de software cobre o que o
  servidor confere; não cobre biometria, presença de usuário real nem atestado
  de fabricante. É o passo do Alex, e é o que o ADR-19 chama de "verificar num
  navegador limpo" antes de mandar remover o token.
- **Qual das quatro direções visuais fica.** `web/src/temas.css`, oito linhas.
- **Subir.** O branch está à frente de `origin/main`.
