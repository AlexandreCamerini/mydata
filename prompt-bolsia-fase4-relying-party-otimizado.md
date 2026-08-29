# BolsIA vira relying party do semente.id — Fase 4 do ADR-23

## Diagnóstico do pedido

**Objetivo real:** o `web-admin` do BolsIA (a superfície do dono, não o app
dos clientes) ganha "entrar com semente.dev" ao lado do login atual, e o
backend publica o contrato mínimo de observabilidade que o console
`admin.semente.dev` vai agregar.

**O que já existe do outro lado, medido nesta sessão (MyData,
`~/dev/cvm-financas`), e serve de implementação de referência:**

- Portal em produção: `https://id.semente.dev` — Authorization Code + PKCE,
  federação Apple/Google, unificação por email verificado.
  `app/api/semente_id.py` do MyData é o cliente OIDC de referência: PKCE
  S256, validação de issuer/audience/nonce contra o JWKS do portal.
- `GET /admin/api/observabilidade` do MyData
  (`app/api/admin.py:713-728`) é a implementação de referência do
  contrato: `{situacao, alertas[], ultimas_execucoes[], proximas[]}`, com
  teste cobrando as quatro chaves (`tests/test_sessao_admin.py::test_observabilidade_cumpre_o_contrato_do_adr_23`).
- Registrar um client novo no portal: `python -m app.cli client <nome>
  --redirect <uri-exata>` (rodado via `railway ssh --service semente-id`,
  projeto `mydata` no Railway) devolve `client_id`/`client_secret` — só
  aparece uma vez.

**Por que só o `web-admin`, não o login dos clientes do BolsIA.** O BolsIA
é produto multi-usuário: conta com email+senha (PBKDF2, `server/app/auth.py`)
e social Apple/Google com validação OIDC própria
(`server/app/auth.py:263-317`, `upsert_oauth_user` em `auth.py:317`). O
portal `semente.id` é o plano do **dono do portfólio**, não uma segunda
opção de login para cada cliente do BolsIA — misturar as duas populações
foi a leitura que a análise anterior (`docs/portal-identidade.md` do
MyData) já descartou. `web-admin/src/App.jsx:962-985` (`function Login`)
é onde o dono entra hoje, com `api.login(email, password)` e checagem de
`r.user.permissions` (ADR-013 de lá) — é essa tela, e só ela, que ganha o
caminho novo.

**O que preservar, sem exceção.** O login email+senha do `web-admin` atual
continua existindo — mesmo princípio do ADR-19 do MyData: o portal soma um
caminho, nunca substitui o único que já existe. Se o portal cair, o dono
entra pelo caminho de sempre.

---

## O prompt otimizado (colar numa sessão do Claude Code no repositório BolsIA)

```
<contexto>
Este repositório (`b3-agente`) é o BolsIA: produto multi-usuário em
bolsia.semente.dev. `server/app/auth.py` tem email+senha (PBKDF2) e social
Apple/Google (verify_oauth_token em auth.py:263, upsert_oauth_user em
auth.py:317, unificação por email verificado). `web-admin/src/App.jsx` é o
painel do dono — `function Login` (linha ~962) autentica com
`api.login(email, password)` e recusa contas sem `permissions` (ADR-013).
Rotas do backend: POST /api/auth/login, /api/auth/oauth, /api/auth/me,
/api/auth/logout (server/app/main.py:235-330).

Existe agora um portal de identidade do portfólio, em produção:
https://id.semente.dev — emissor OIDC próprio (Authorization Code + PKCE
S256), federando Apple e Google, com contas do dono por convite e
unificação por email VERIFICADO pelo provedor. Ele é a Fase 1 do ADR-23,
documentado em ~/dev/cvm-financas/docs/arquitetura.md (seção ADR-23) — leia
esse ADR antes de desenhar qualquer coisa aqui, ele é a fonte de verdade do
contrato e das decisões já tomadas (portal federando Apple/Google com
email verificado, caminho de emergência sempre preservado, console
agregador só por API).

A Fase 2 (MyData vira relying party do mesmo portal) está pronta e é a
implementação de referência:
- ~/dev/cvm-financas/app/api/semente_id.py — cliente OIDC: PKCE, troca do
  code, validação do id_token (issuer, audience, nonce) contra o JWKS do
  portal em https://id.semente.dev/jwks.
- ~/dev/cvm-financas/app/api/admin.py:713-728 — GET /admin/api/observabilidade,
  a implementação de referência do contrato mínimo que o console
  admin.semente.dev vai consumir: {situacao, alertas[], ultimas_execucoes[],
  proximas[]}.
- ~/dev/cvm-financas/tests/test_semente_id.py e
  tests/test_entrar_semente_id_http.py — o padrão de teste: id_token
  assinado de verdade (chave RSA gerada em memória), sem tocar rede real.

Regras do portfólio que continuam valendo:
- Cada repositório é editado na sessão dele. O que precisar do MyData ou do
  portal semente-id vira pergunta para o Alex, não edição direta.
- Registrar o client deste app no portal roda via
  `railway ssh --service semente-id "python -m app.cli client bolsia-web-admin
  --redirect <redirect_uri_exata>"` — projeto `mydata` no Railway. Isso
  toca um serviço de produção fora deste repositório: confirme com o Alex
  antes de rodar, e trate o client_secret devolvido como segredo (nunca em
  commit, nunca no chat).
</contexto>

<objetivo>
O web-admin do BolsIA (a superfície do dono) ganha um segundo caminho de
entrada, o portal semente.id, ao lado do login por email+senha que já
existe. O backend passa a publicar GET /observabilidade no contrato mínimo
do ADR-23, para o console admin.semente.dev agregar mais tarde.

Isto NÃO é sobre o login dos clientes do BolsIA (email+senha+social já
existentes para eles) — é só sobre a tela de administração.
</objetivo>

<restricoes>
- O login email+senha do web-admin continua funcionando sem nenhuma
  mudança — o portal soma, não substitui (mesmo princípio do ADR-19 do
  MyData: nunca trancar o dono fora se o portal cair).
- O login dos clientes finais do BolsIA (o app, não o web-admin) não muda
  em nada. Este trabalho é só a superfície administrativa.
- Authorization Code + PKCE S256 contra o portal, igual ao MyData:
  id_token validado por issuer (https://id.semente.dev), audience
  (client_id deste app) e nonce, contra o JWKS do portal. Nunca aceitar
  id_token sem essa validação.
- O portal é multiusuário por natureza (outros sistemas do portfólio o
  compartilham). Se o web-admin do BolsIA deve continuar sendo só do
  dono, replique a trava que o MyData usa (SEMENTE_ID_EMAIL_DONO em
  app/api/semente_id.py do MyData) — ou decida e documente por que este
  app não precisa da mesma trava, se ele já tem RBAC por permissão que
  cobre o caso.
- GET /observabilidade segue exatamente o formato de
  app/api/admin.py:713-728 do MyData: {situacao: "ok"|"atencao"|"critico",
  alertas: [...], ultimas_execucoes: [...], proximas: [...]}. Derive de
  dado que já existe (log de execução, alertas do BolsIA), não invente
  campo novo sem necessidade.
- Client_secret e qualquer credencial do portal entram por variável de
  ambiente, nunca em código nem em commit.
</restricoes>

<tarefa>
1. Leia o ADR-23 (~/dev/cvm-financas/docs/arquitetura.md) e a implementação
   de referência do MyData (os três arquivos citados no contexto) antes de
   desenhar.
2. Registre o client deste app no portal (confirme com o Alex antes de
   rodar o comando do contexto), guarde client_id/client_secret como
   variável de ambiente do web-admin/backend.
3. Implemente o backend: rota de início do fluxo (redirect ao
   /authorize do portal com PKCE) e de callback (troca o code, valida o
   id_token, abre a sessão administrativa existente — a mesma que
   /api/auth/login abre hoje, só com origem diferente).
4. Ajuste web-admin/src/App.jsx (função Login) para oferecer "entrar com
   semente.dev" ao lado do formulário atual.
5. Implemente GET /observabilidade no formato do contrato, com teste
   comparando as quatro chaves (espelhe
   tests/test_sessao_admin.py::test_observabilidade_cumpre_o_contrato_do_adr_23
   do MyData).
6. Atualize docs/contrato-consumidor.md do MyData (~/dev/cvm-financas) só
   se o Alex pedir explicitamente — não é deste repositório.
</tarefa>

<criterio_de_aceite>
- Login por email+senha do web-admin continua idêntico ao de hoje.
- Login pelo portal abre o web-admin de ponta a ponta, localmente: o
  fluxo completo (authorize → callback → sessão administrativa) funciona
  contra o portal real ou um id_token de teste assinado com chave gerada
  em memória (padrão dos testes do MyData, não peça ao portal de produção
  em teste automatizado).
- GET /observabilidade responde as quatro chaves do contrato, com teste.
- Suíte deste repositório passa inteira, sem regressão no login dos
  clientes finais.
- Nenhum client_secret em commit, log ou saída de terminal persistida.
</criterio_de_aceite>

Decida sozinho o rotineiro e siga. Traga para decisão apenas o que for
irreversível na prática: registrar o client em produção (toca serviço de
outro repositório) e qualquer mudança no login dos clientes finais do
BolsIA — que não deveria acontecer aqui, mas se a implementação esbarrar
nisso, pare e pergunte.
```

---

## Rubrica de qualidade

| Critério | Nota | Justificativa |
|---|---|---|
| Clareza do objetivo | 5 | Um eixo só (web-admin), com o limite explícito do que NÃO é escopo (login de cliente) |
| Adequação ao alvo (Claude Code) | 5 | Caminhos e linhas reais dos dois repositórios, comando exato de registro de client |
| Autonomia / execução sem intervenção | 5 | Um gatilho de parada: ação de produção fora do repo, ou risco ao login de clientes |
| Verificabilidade | 5 | Aceite por comportamento (login velho intacto, login novo de ponta a ponta, contrato testado) |
| Calibração | 5 | Enquadramento positivo ("continua funcionando" em vez de "não quebre"); sem CoT nem auto-verificação redundante |
| Estrutura e ausência de redundância | 5 | Contexto/objetivo/restrições/tarefa/aceite, cada um com informação nova |
| Robustez | 5 | Cobre o risco real (misturar população de clientes com plano do dono) com a mesma trava por email do MyData como alternativa pronta |
| Atualidade | 5 | OIDC code+PKCE, sem padrão obsoleto; aponta implementação de referência já validada em produção |

---

## Modelo recomendado

**Perfil:** integração de autenticação cross-sistema numa superfície de
produção multi-usuário, com risco real de confundir duas populações de
login (dono vs. clientes) se mal desenhado.

**Modelo:** `claude-opus-5`. Há implementação de referência pronta
(reduz o quanto precisa ser descoberto), mas a decisão de onde a trava de
confiança entra (email do dono, ou RBAC existente) exige julgamento, não
só cópia.

**Effort:** `high`. Não é o nó mais difícil do portfólio — é o segundo
relying party do mesmo protocolo, com exemplo funcionando ao lado.
