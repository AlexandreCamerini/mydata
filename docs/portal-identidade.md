# Portal único de identidade — análise e proposta (ADR proposto)

> **Revisado em 26/08/2026 pelo
> [ADR-23](arquitetura.md#adr-23--o-portfólio-consolida-em-sementedev-um-login-um-console-um-domínio):**
> o Alex decidiu Apple/Google como provedores federados (com email
> verificado como chave) e `semente.dev` como domínio de tudo. Deste
> documento continuam valendo a separação dono×clientes do BolsIA, o
> emissor próprio (alternativa b), a análise de segurança e as fases por
> repositório; o que mudou está registrado lá.

**Status: proposto, aguardando decisão do Alex.** Análise de 26/08/2026,
encomendada como "portal único de login para as 3 aplicações (MCP, b3-agente
e MyData), melhores práticas, usuário e senha, rodando somente na web".
Nenhuma linha de código foi alterada em nenhum dos três sistemas — este
documento e as pendências de negociação são o entregável.

## O que a medição mudou no pedido

A análise partiu de levantamento read-only dos dois lados (MyData:
`docs/arquitetura.md` ADR-19, `app/api/acesso.py`; BolsIA:
`server/app/auth.py`, `rbac.py`, `siwa.py`, `db.py`, `main.py`), e três
fatos derrubam a formulação original antes de qualquer alternativa:

1. **O Portal MCP não faz login interativo.** Servidor MCP autentica por
   credencial de máquina — e já autentica: chave de API escopada
   (`c8125eee`, com `fonte:b3`), emitida em 26/08. Colocá-lo num portal de
   *login* misturaria autenticação de humano com autenticação de máquina.
   Ele sai do escopo do portal e permanece no plano de chaves.

2. **O BolsIA não é um admin de dono único — é produto multi-usuário.**
   Contas com e-mail+senha (PBKDF2-HMAC-SHA256, 240k iterações,
   `auth.py:23-48`), login social Apple/Google com validação OIDC real
   (`auth.py:263-314`), múltiplas identidades por conta (`identities`,
   `db.py:95-146`), RBAC por grupos (`rbac.py:21-33`, ADR-013 de lá),
   planos free/pro, e Sign in with Apple com troca de `authorizationCode`
   por `refresh_token` para cumprir a exigência de revogação 5.1.1(v) da
   Apple (`siwa.py`) — o que revela um app iOS servido pelo mesmo backend.
   **Unificar o login "das 3 aplicações" portanto conflaria duas populações
   diferentes: o dono (você) e os clientes do BolsIA.**

3. **SSO por cookie compartilhado é impossível aqui.** MyData vive em
   `mydata.acamerini.app`; BolsIA em `bolsia.semente.dev` — ápices
   diferentes. Navegador não compartilha cookie entre eles. SSO de verdade
   exige protocolo de redirecionamento (OIDC Authorization Code + PKCE),
   não sessão compartilhada.

Reformulação honesta do pedido: **um portal web de identidade para o plano
do dono/operador** (o admin do MyData e o `web-admin` do BolsIA), com
passkey primeiro e senha como fallback — e uma decisão *separada e adiável*
sobre os clientes finais do BolsIA.

## Premissas declaradas

- Portal roda **somente na web** (restrição do Alex, 26/08). O app iOS do
  BolsIA, se um dia consumir o portal, o faz por fluxo web
  (`ASWebAuthenticationSession`), nunca por tela nativa do portal.
- Usuários do plano dono/operador: 1 hoje (Alex), poucos no futuro.
- Custo: nada além do plano Railway já contratado (regra do CLAUDE.md).
- Senha existe como **fallback** com Argon2id, nunca como método primário —
  coerente com o ADR-19, que eliminou o segredo digitado como caminho
  principal. Se senha primária for requisito duro, este ADR reabre.

## Alternativas

Filtro herdado do ADR-19, que continua valendo: nada que cobre por uso, e
nada que dependa de terceiro para o dono entrar no próprio sistema. A
rejeição de "OIDC de provedor" no ADR-19 era sobre *terceiro como emissor*;
um emissor próprio não cai nela.

| Alternativa | O que ganho | O que pago | Onde quebra |
|---|---|---|---|
| **(a) MyData vira o emissor OIDC** dos demais | Zero serviço novo; passkey e sessão já existem aqui | Acopla o hub de dados à identidade do portfólio: todo sistema futuro passa a depender do MyData para logar, invertendo a regra de que "o consumidor depende do MyData" só para dado. Deploy do hub derruba login de tudo | Quando o MyData precisar de manutenção longa, ninguém entra em nada; e o hub ganha superfície de ataque que não é dele |
| **(b) Portal de identidade próprio e mínimo** — serviço novo no mesmo projeto Railway, repositório próprio, FastAPI + Authlib como provedor OIDC, passkey (WebAuthn) primeiro + senha Argon2id fallback | Identidade vira sistema com fronteira própria, como manda a regra de independência; MyData e web-admin do BolsIA viram *relying parties* pequenas; o padrão (OIDC + PKCE) é o que qualquer app futuro já sabe consumir | Um serviço a mais rodando (custo de recurso dentro do plano, não de licença); implementar provedor OIDC correto não é trivial — é a peça mais sensível do portfólio e passa a ser código seu | Se mal implementado, é o ponto único de comprometimento de tudo. Mitigação: superfície mínima (2 fluxos, 2 clients), Authlib maduro, e a saída de emergência por app (abaixo) |
| **(c) Keycloak self-hosted** no Railway | Provedor completo e auditado, sem escrever código de OIDC | JVM sempre-ligada (~512MB+) pesa no plano por uso; operar Keycloak (upgrades, realm config, tema) é um segundo emprego para 1 usuário | Complexidade desproporcional: dezenas de features para um caso de 1-5 contas |
| **(d) IdP gerenciado** (Auth0/Clerk/etc.) | Zero operação | Fere as duas regras de uma vez: custo fora do plano e terceiro entre o dono e o próprio sistema (a rejeição literal do ADR-19) | Free tier é promessa de terceiro; o ADR-19 já disse o que acha disso |

**Proposta: (b)** — portal próprio mínimo. O (a) é tentador pelo esforço,
mas cobra no lugar errado: transforma o hub de dados em dependência de
login de todo o portfólio, e "barato agora, caro para sempre" é exatamente
o padrão que o ADR-19 rejeitou no free tier de terceiro.

## O desenho proposto (para a fase de implementação detalhar)

- **Serviço**: `id.acamerini.app` (subdomínio próprio, mesmo projeto
  Railway), repositório novo e independente. FastAPI + Authlib (provedor
  OIDC Authorization Code + PKCE, sem implicit flow), `py_webauthn` para
  passkey — as duas dependências já são conhecidas do portfólio.
- **Métodos, nesta ordem**: passkey (primário); senha como fallback com
  **Argon2id** (não PBKDF2 — é a recomendação corrente; o BolsIA usa
  PBKDF2 240k nos clientes dele e isso continua sendo problema *de lá*),
  com rate limit e teto de tamanho como o BolsIA já faz (`auth.py:165-219`
  é referência boa).
- **Sessão no portal**: cookie `HttpOnly` `SameSite=Lax` `Secure`, como o
  MyData já faz — nunca token em `localStorage` (o Bearer em
  `localStorage` do BolsIA é exposição a XSS conhecida; o portal não a
  herda).
- **Relying parties da fase 1**: MyData admin e `web-admin` do BolsIA.
  Cada uma troca sua tela de login por redirect ao portal e mantém a
  própria sessão local após o retorno — o que muda é quem emite a
  identidade, não o que a sessão é (mesmo princípio do ADR-19).
- **Saída de emergência por app, preservada**: `PORTAL_ACESSO_LEGADO=1` do
  MyData continua existindo e ganhando equivalente no web-admin — se o
  portal cair, o dono entra em cada sistema pelo caminho antigo. Portal
  fora do ar não pode significar portfólio trancado.
- **Fora do escopo, explicitamente**: clientes finais do BolsIA continuam
  no login atual (e-mail+senha+social). Migrá-los ao portal é decisão
  futura com peso próprio — envolve as contas existentes, o vínculo
  multi-identidade (`identities`) e o requisito SIWA do app iOS — e nada
  na fase 1 a bloqueia nem a antecipa.

## Revisão de segurança do desenho

Ameaças consideradas e resposta de desenho (a implementação será cobrada
contra esta lista):

| Ameaça | Resposta no desenho |
|---|---|
| Redirect URI aberto (open redirect no fluxo OIDC) | Lista fechada de `redirect_uri` por client, comparação exata — sem prefixo, sem wildcard |
| Interceptação de código de autorização | PKCE obrigatório (S256) para todo client, mesmo confidencial; `state` obrigatório contra CSRF do fluxo |
| XSS roubando sessão | Cookie `HttpOnly` no portal e nas RPs; nada de token de sessão em `localStorage` no plano do dono |
| Força bruta na senha fallback | Argon2id + rate limit por (ip, conta) e por conta, teto de tamanho de senha |
| Comprometimento do portal = comprometimento de tudo | Superfície mínima (2 fluxos, 2 clients, sem API de dados); segredos de client únicos por RP; rotação documentada; e a saída de emergência por app limita o raio |
| Dono trancado fora (autenticador perdido) | Herda as três saídas do ADR-19: múltiplos autenticadores, acesso legado por variável, nada de recuperação por e-mail |
| Sessão eterna | TTL curto no cookie do portal; a RP decide o TTL da própria sessão local |

## Fases (uma por repositório, cada uma em sessão própria)

1. **Portal** (repo novo): provedor OIDC + passkey + senha fallback +
   telas web. Critério: MyData local autentica via portal local de ponta a
   ponta.
2. **MyData** (este repo): vira relying party; `/entrar` oferece "entrar
   com o portal"; token e passkey locais permanecem até o Alex mandar
   remover (reversibilidade do ADR-19).
3. **BolsIA** (repo de lá, sessão de lá): `web-admin` vira relying party.
   O levantamento mediu acoplamento **médio, não alto** — a auth está
   concentrada em 3 arquivos e as dependências FastAPI
   (`require_user`/`require_permission`) são o único ponto que resolve
   identidade.
4. **Decisão futura separada**: clientes finais do BolsIA.

## O que este ADR não decide

O esquema de contas do portal (recovery codes? e-mail de aviso sem ser de
recuperação?), o TTL exato das sessões, e a migração dos clientes do
BolsIA. Cada um se decide na construção da fase respectiva, contra o
sistema real — como o ADR-20 e o ADR-22 fizeram.
