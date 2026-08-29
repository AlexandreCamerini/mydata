# Boris+ entra no portal semente.id — Fase 4 do ADR-23, com a cauda do rename

## Diagnóstico

**Objetivo real:** o painel de administração do **Boris+** ganha "entrar com
semente.dev" ao lado do login atual, publica `GET /observabilidade` no contrato
do ADR-23, e a cauda do rename BolsIA→Boris+ entra como alvo declarado do
planejamento — em vez de o agente tropeçar no nome antigo pelo caminho.

**Medição antes de escrever (repo `~/dev/bolsia/b3-agente`, leitura):** o
rebranding **não é trabalho pendente — já foi decidido e executado em
10/08/2026**. `scripts/atualizar-identidade.sh` é idempotente e já rodou:
`capacitor.config.ts` tem `appName: "Boris+"`, o `<title>` é `Boris+`, o
manifest PWA é `Boris+`, e o domínio de produção é **`boris.semente.dev`**.
`bolsia.semente.dev` não aparece em lugar nenhum ativo do repositório. As 252
ocorrências restantes de "bolsia" em 139 arquivos concentram-se em
`.planning/` (62), `qa/` e `ESTADO-*` — **registro histórico que a decisão
manda preservar**, porque reescrever o nome da época falsificaria o que foi
decidido nela.

**O erro que esta versão corrige.** A versão anterior deste prompt
(`prompt-bolsia-fase4-relying-party-otimizado.md`, substituída por esta) dizia
que o BolsIA responde em `bolsia.semente.dev`. Está errado: é
`boris.semente.dev`. Como esse endereço vira a `redirect_uri` registrada no
portal OIDC — comparada por **igualdade exata**, sem prefixo nem wildcard — o
prompt antigo produziria um client que nunca autentica, com erro
`redirect_uri` do lado do portal e nenhuma pista óbvia da causa.

**A armadilha do rebranding, que precisa aparecer no prompt.** O bundle id
`com.alexandrecamerini.bolsia` é **mantido de propósito** e está documentado
como tal em `scripts/atualizar-identidade.sh:7-11`: trocá-lo publica *outro*
app na Apple, quebra todo Sign in with Apple (o `sub` é emitido por bundle id)
e deixa órfã cada instalação existente. `APNS_TOPIC` precisa ser exatamente
igual a ele, e o `aud` do SIWA também. Um agente com instrução genérica de
"renomear bolsia para Boris+" vai querer "limpar" esse identificador — e
seria a única mudança irreversível de todo o trabalho.

**Escopo do login, que não muda:** o portal `semente.id` é o plano do **dono
do portfólio**. O Boris+ é produto multi-usuário — clientes entram por
email+senha (PBKDF2) e social Apple/Google, com unificação por email
verificado (`server/app/auth.py:263-365`). O portal entra só na tela
administrativa (`web-admin/src/App.jsx`, `function Login`, ~linha 962), nunca
no login dos clientes.

---

## O prompt otimizado (colar numa sessão do Claude Code em `~/dev/bolsia/b3-agente`)

```
<contexto>
Este repositório é o Boris+ (codinome interno `b3-agente`, mantido de
propósito). Produto multi-usuário em https://boris.semente.dev.

Autenticação hoje:
- Clientes finais: email+senha PBKDF2 e social Apple/Google com validação
  OIDC própria — server/app/auth.py (verify_oauth_token:263,
  upsert_oauth_user:317, unificação por email verificado).
- Painel do dono: web-admin/src/App.jsx, `function Login` (~linha 962),
  autentica com api.login(email, password) e recusa conta sem
  `permissions` (ADR-013 deste repo).
- Rotas: POST /api/auth/login, /api/auth/oauth, /api/auth/me,
  /api/auth/logout (server/app/main.py:235-330).

Existe um portal de identidade do portfólio em produção:
https://id.semente.dev — emissor OIDC próprio (Authorization Code + PKCE
S256), federando Apple e Google, contas do dono por convite, unificação por
email VERIFICADO pelo provedor. É a Fase 1 do ADR-23, cuja fonte de verdade
é ~/dev/cvm-financas/docs/arquitetura.md (seção ADR-23) — leia antes de
desenhar.

A Fase 2 (MyData como relying party do mesmo portal) está em produção e é a
implementação de referência para copiar o padrão:
- ~/dev/cvm-financas/app/api/semente_id.py — cliente OIDC: PKCE, troca do
  code, validação do id_token (issuer, audience, nonce) contra o JWKS em
  https://id.semente.dev/jwks, e a trava SEMENTE_ID_EMAIL_DONO.
- ~/dev/cvm-financas/app/api/admin.py:713-728 — GET
  /admin/api/observabilidade, o formato do contrato mínimo.
- ~/dev/cvm-financas/tests/test_semente_id.py e
  tests/test_entrar_semente_id_http.py — o padrão de teste: id_token
  assinado com chave RSA gerada em memória, sem tocar rede real.

Sobre o nome: o produto se chama Boris+ desde 10/08/2026 e o rename já foi
executado por scripts/atualizar-identidade.sh (idempotente). O que ainda
carrega "BolsIA" é registro histórico em .planning/, qa/, ESTADO-* e
RELEASES.md — preservado de propósito, porque reescrever o nome da época
falsificaria o que foi decidido nela.

Cada repositório é editado na sessão dele: o que precisar do MyData ou do
portal vira pergunta para o Alex, não edição direta.
</contexto>

<objetivo>
Três alvos, nesta ordem de dependência:

1. IDENTIDADE — o painel administrativo do Boris+ ganha um segundo caminho
   de entrada pelo portal semente.id, ao lado do login por email+senha que
   já existe.
2. OBSERVABILIDADE — o backend publica GET /observabilidade no contrato
   mínimo do ADR-23, para o console admin.semente.dev agregar depois.
3. CAUDA DO RENAME — as superfícies que ainda dizem "BolsIA" e são vistas
   por alguém hoje (interface, documentação operacional viva, mensagens de
   erro, README) passam a dizer Boris+. Registro histórico permanece como
   está.
</objetivo>

<restricoes>
- O bundle id `com.alexandrecamerini.bolsia` permanece exatamente como
  está, e com ele APNS_TOPIC e o `aud` do Sign in with Apple. O raciocínio
  está em scripts/atualizar-identidade.sh:7-11: ele é a identidade do app
  na Apple, o usuário nunca o vê, e trocá-lo publicaria outro app. O mesmo
  vale para o codinome interno `b3-agente` (pastas, package.json, env vars
  B3_*, chaves de armazenamento b3-* que são dado de usuário).
- O login email+senha do painel continua funcionando idêntico ao de hoje —
  o portal soma um caminho. Se o portal cair, o dono entra pelo caminho de
  sempre (mesmo princípio do ADR-19 do MyData).
- O login dos clientes finais permanece como está. Este trabalho é só a
  superfície administrativa.
- redirect_uri do client OIDC usa https://boris.semente.dev — o portal
  compara por igualdade exata, sem prefixo nem wildcard.
- id_token validado por issuer (https://id.semente.dev), audience
  (client_id deste app) e nonce, contra o JWKS do portal.
- O portal é multiusuário (outros sistemas do portfólio o compartilham).
  Para o painel continuar sendo só do dono, replique a trava
  SEMENTE_ID_EMAIL_DONO do MyData — ou documente por que o RBAC deste repo
  já cobre o caso.
- GET /observabilidade segue o formato de app/api/admin.py:713-728 do
  MyData: {situacao: "ok"|"atencao"|"critico", alertas: [...],
  ultimas_execucoes: [...], proximas: [...]}, derivado de dado que já
  existe aqui.
- Credenciais do portal entram por variável de ambiente.
- Registrar o client no portal roda contra produção de outro repositório:
  `railway ssh --service semente-id "python -m app.cli client boris-web-admin
  --redirect https://boris.semente.dev/<caminho-do-callback>"`, projeto
  `mydata` no Railway. Confirme com o Alex antes de rodar; o client_secret
  devolvido aparece uma única vez e é segredo.
</restricoes>

<tarefa>
Leia o ADR-23 e os três arquivos de referência do MyData antes de desenhar.

Entregue os três alvos do objetivo. Para o alvo 3, generalize
scripts/atualizar-identidade.sh em vez de criar um script paralelo — duas
fontes de verdade para a mesma migração é o problema que ele já resolve — e
comece medindo o que ainda diz "BolsIA" fora dos registros históricos, para
o alvo ter tamanho conhecido antes de começar.

Se a implementação esbarrar no login dos clientes finais ou no bundle id,
pare e traga para decisão em vez de contornar.
</tarefa>

<criterio_de_aceite>
- Login por email+senha do painel continua idêntico ao de hoje.
- Login pelo portal abre o painel administrativo de ponta a ponta, com
  teste automatizado usando id_token assinado por chave gerada em memória
  (o portal de produção fica fora da suíte).
- GET /observabilidade responde as quatro chaves do contrato, com teste.
- `bash scripts/atualizar-identidade.sh --verificar` roda limpo, e o bundle
  id continua com.alexandrecamerini.bolsia.
- A suíte deste repositório passa inteira, sem regressão no login dos
  clientes finais.
- Nenhum client_secret em commit ou log.
</criterio_de_aceite>

Decida sozinho o rotineiro e entregue no escopo acima. Se discordar de
alguma restrição, diga em uma frase e siga.
```

---

## Rubrica de qualidade

| Critério | Nota | Justificativa |
|---|---|---|
| Clareza do objetivo | 5 | Três alvos numerados, em ordem de dependência, com o limite de escopo de cada um |
| Adequação ao alvo (Claude Code) | 5 | Caminhos e linhas reais dos dois repositórios, comando exato de registro do client, script existente apontado como espinha do rename |
| Autonomia / execução sem intervenção | 5 | Dois gatilhos de parada, ambos irreversíveis de verdade: produção cross-repo e bundle id / login de clientes |
| Verificabilidade | 5 | Aceite por comportamento observável, incluindo `--verificar` do script e a asserção do bundle id preservado |
| Calibração | 5 | Enquadramento positivo ("permanece exatamente como está" em vez de "não troque"); sem CoT, sem pedido de auto-verificação |
| Estrutura e ausência de redundância | 5 | Contexto/objetivo/restrições/tarefa/aceite, cada seção com informação nova |
| Robustez | 5 | Cobre as três armadilhas medidas: domínio errado, bundle id, registro histórico |
| Atualidade | 5 | OIDC code+PKCE; referência a implementação validada em produção nesta semana |

---

## Antes / depois

| Mudança | Efeito esperado |
|---|---|
| `bolsia.semente.dev` → **`boris.semente.dev`** | Corrige o erro que produziria um client OIDC que nunca autentica — a `redirect_uri` é comparada por igualdade exata |
| Rename tratado como "a fazer" → **medido como já feito, com a cauda isolada** | O agente parte de `scripts/atualizar-identidade.sh` em vez de reinventar a migração e criar segunda fonte de verdade |
| Rebranding sem ressalva → **bundle id declarado imutável, com o porquê** | Impede a única mudança irreversível do trabalho: trocar o bundle id publica outro app e quebra todo Sign in with Apple |
| Sem menção a registro histórico → **`.planning/`, `qa/`, `ESTADO-*` preservados** | Evita que 62 arquivos de decisão histórica sejam reescritos, falsificando o que se decidiu na época |
| "Renomear o projeto" → **alvo 3 com fronteira: superfície viva vs. registro** | Dá tamanho conhecido ao rename em vez de um `sed` global de 252 ocorrências |
| Ordem solta → **três alvos em ordem de dependência** | Identidade e observabilidade são o desbloqueio da Fase 3 do ADR-23; o rename é cauda, não pré-requisito |

---

## Modelo recomendado

**Perfil:** integração de autenticação cross-sistema numa superfície de
produção multi-usuário, somada a uma migração de identidade com um
identificador irreversível no caminho (bundle id da Apple). Há implementação
de referência pronta dos dois lados, o que reduz descoberta — mas a decisão de
onde a trava de confiança entra, e o discernimento entre "superfície viva" e
"registro histórico" no rename, exigem julgamento.

**Modelo:** `claude-opus-5`, com **effort `high`**. Não é o nó mais difícil do
portfólio — é o segundo relying party do mesmo protocolo, com exemplo
funcionando ao lado e um script de rename já escrito e idempotente. `xhigh`
não se paga aqui; o risco está concentrado em duas restrições explícitas, não
na dificuldade do raciocínio.
