# Consolidação em semente.dev: domínio, identidade e observabilidade

## Diagnóstico do pedido original

> "concentrar todos os app em semente.dev. Mesmo para o MSP [MCP] e para o
> Bolsia eu gostaria de centralizar os modulos de administração e
> observabilidade. A gestão de logins também deveria ser centralizada e
> atender a todas as aplicações. A única diferença é que gostaria de utilizar
> a mesma solução do boris [BolsIA], onde o email dos logins pela apple e
> google sejam mantidos como principal chave para todos."

**Objetivo real:** três consolidações distintas, com dependências entre si —
domínio (todos sob `semente.dev`), identidade (um login para tudo, email
como chave, Apple/Google como provedores) e operação (um console de
administração e observabilidade servindo os três sistemas).

**Premissas assumidas, não perguntadas** (correções de digitação e leitura
de contexto desta sessão): "MSP" é o **MCP**; "boris" é o **BolsIA**;
"centralizar módulos" significa **um console que consome API de cada
sistema**, não fundir os três repositórios — a regra de independência do
`CLAUDE.md` proíbe a segunda leitura.

**O conflito que o pedido cria, e que precisa aparecer no prompt.** Apple e
Google como provedores de login contradizem frontalmente o
[ADR-19](docs/arquitetura.md#adr-19--passkey-entra-ao-lado-do-token-não-no-lugar),
que rejeitou OIDC de terceiro com uma frase específica: *"o dono passa a
depender de terceiro para entrar"*. O conflito não é motivo para recusar o
pedido — é motivo para o prompt exigir **caminho de emergência preservado**:
se a conta Google do Alex for suspensa, ele não pode perder o acesso aos
próprios sistemas. `PORTAL_ACESSO_LEGADO=1` já existe no MyData e é o
molde. Sem isso explícito, um agente implementa o SSO e remove o caminho
antigo por "limpeza", produzindo um sistema onde um terceiro decide se o
dono entra.

**A pegadinha de segurança do "email como chave principal".** Unificar
contas por email só é seguro quando o provedor **verificou** aquele email —
senão é sequestro de conta trivial: alguém se cadastra num provedor frouxo
com o seu email e cai na sua conta. O BolsIA já faz certo (unificação por
email verificado, `auth.py:317-365`), e é justamente por isso que a
instrução "mesma solução do BolsIA" precisa citar a verificação como parte
da solução, não só o email como chave.

**A mudança de domínio tem consequência de contrato.** MyData responde hoje
em `mydata.acamerini.app`, e é esse endereço que o BolsIA e o Portal MCP
usam. Mover para `mydata.semente.dev` quebra os dois consumidores se o
endereço antigo simplesmente sumir. O prompt fixa período de convivência.

**Escopo real: EPIC, não uma sessão.** Três repositórios (MyData, BolsIA,
portal novo), mudança de DNS em produção e migração de identidade. Uma
sessão só produziria um desenho pela metade — daí a divisão em fases com
critério de aceite por fase, cada uma numa sessão do repositório dono.

---

## O prompt otimizado (colar numa sessão do Claude Code no repositório MyData)

```
<contexto>
Portfólio de três sistemas, cada um com repositório e ciclo próprios:

- MyData (~/dev/cvm-financas, este repo): hub de dados FastAPI + React no
  Railway. Responde em mydata.acamerini.app; o serviço já tem semente.dev
  como segundo domínio. Auth: PORTAL_ADMIN_TOKEN + passkey (ADR-19), e
  chaves de API por consumidor. Tem admin com Gestão (semáforo de alertas,
  próximas cargas), Execuções, Carga e custo, Qualidade.
- BolsIA (~/dev/bolsia/b3-agente, LER SOMENTE — outro repositório): produto
  multi-usuário em bolsia.semente.dev. Contas com email+senha (PBKDF2 240k)
  e login social Apple/Google com validação OIDC real; tabela `identities`
  unifica múltiplas identidades por conta usando email VERIFICADO como
  chave (server/app/auth.py:317-365); RBAC por grupos (rbac.py); app iOS
  com Sign in with Apple e requisito de revogação 5.1.1(v) (siwa.py);
  painel próprio em web-admin/.
- Portal MCP: servidor MCP, consumidor de máquina. Autentica por chave de
  API escopada (prefixo c8125eee, com fonte:b3). Não tem login humano.

Análise anterior desta sessão, com o que foi medido de cada lado:
docs/portal-identidade.md. Este pedido a REVISA em dois pontos — domínio
único e provedores Apple/Google — e a estende para observabilidade.

Regras do portfólio que continuam valendo:
- Cada repositório é editado na sessão dele. O que atravessa a fronteira
  vira item em docs/contrato-consumidor.md do MyData.
- Custo: dentro do plano Railway já contratado.
- Configuração de deploy é código: .railway/railway.ts, com
  `railway config plan` antes de todo apply.
</contexto>

<objetivo>
Consolidar o portfólio em três eixos, preservando as decisões de produto:

1. DOMÍNIO — todos os sistemas sob semente.dev:
   id.semente.dev (portal), mydata.semente.dev, bolsia.semente.dev,
   admin.semente.dev (console unificado).
2. IDENTIDADE — um login para todas as aplicações, com a solução que o
   BolsIA já usa: Apple e Google como provedores, e o email VERIFICADO
   pelo provedor como chave principal de identidade, unificando as contas
   de uma mesma pessoa entre provedores.
3. OPERAÇÃO — um console único de administração e observabilidade que
   sirva MyData, BolsIA e Portal MCP.
</objetivo>

<restricoes>
- O console central consome a API de cada sistema; ele não importa código
  nem acessa banco de outro sistema. Cada sistema publica o que expõe.
- O caminho de emergência do dono é preservado em cada sistema. Apple e
  Google passam a ser o login normal; PORTAL_ACESSO_LEGADO=1 (MyData) e
  equivalente nos demais continuam existindo, para o caso de a conta do
  provedor cair. Um terceiro não decide se o dono entra no próprio sistema.
- Unificação de conta acontece com email verificado pelo provedor. Email
  não verificado abre sequestro de conta e não serve como chave.
- Endereço antigo (mydata.acamerini.app) continua respondendo durante a
  transição; a troca de PORTAL_URL_PUBLICA e o aviso aos dois consumidores
  (BolsIA e Portal MCP) entram como item de contrato antes do corte.
- Sessão em cookie HttpOnly/Secure/SameSite. O fluxo entre sistemas é OIDC
  Authorization Code + PKCE, com lista fechada de redirect_uri por client —
  mesmo apex não é motivo para compartilhar cookie entre subdomínios.
- Passkey do MyData (ADR-19) permanece disponível como método adicional;
  esta mudança soma um caminho, não apaga o existente.
</restricoes>

<tarefa>
Comece pelo desenho, não pelo código. Produza, neste repositório:

1. Um ADR em docs/arquitetura.md que registre esta consolidação e sua
   relação com o ADR-19 — explicitamente: o que muda, o que continua, e
   como o risco de dependência de terceiro fica coberto.
2. Um plano de fases, uma por repositório, com dependência entre elas e o
   critério de aceite verificável de cada uma.
3. Os itens de docs/contrato-consumidor.md que a mudança gera para o
   BolsIA e para o Portal MCP (mudança de endereço, adoção do SSO, quais
   dados de observabilidade cada um passa a publicar para o console).

Sugestão de fases, para ajustar se a leitura do código apontar melhor:
  Fase 1 — portal de identidade (repositório novo): provedor OIDC,
    Apple/Google, unificação por email verificado, contas e sessão.
  Fase 2 — MyData vira relying party e muda de endereço.
  Fase 3 — console unificado: começa reaproveitando o admin do MyData,
    que já tem alertas, agenda e custo, e ganha as outras duas origens.
  Fase 4 — BolsIA (sessão do repositório de lá): web-admin como relying
    party e publicação da API de observabilidade dele.

O que cada sistema publica para o console é decisão de desenho da Fase 3:
proponha o contrato mínimo (saúde, últimas execuções, alertas ativos) a
partir do que o MyData já expõe em /admin/api/alertas e /admin/api/gestao.
</tarefa>

<criterio_de_aceite>
- ADR no padrão do arquivo (contexto, alternativas com trade-off, decisão,
  consequências), citando ADR-19 e portal-identidade.md.
- Nenhum arquivo do BolsIA alterado; o que ele precisa fazer aparece como
  item de contrato.
- Cada fase tem uma verificação executável descrita (ex.: "login pelo
  portal local abre o admin do MyData local de ponta a ponta").
- A suíte deste repositório continua passando: python -m pytest -q.
- O plano diz o que acontece se o portal ficar fora do ar, e o que
  acontece se a conta do provedor for perdida.
</criterio_de_aceite>

Decida sozinho o rotineiro e siga. Traga para decisão apenas o que for
irreversível na prática: corte definitivo do endereço antigo, remoção de um
caminho de acesso existente, ou qualquer mudança no BolsIA.
```

---

## Rubrica de qualidade

| Critério | Nota | Justificativa |
|---|---|---|
| Clareza do objetivo | 5 | Três eixos nomeados e separados, com os endereços concretos de cada sistema |
| Adequação ao alvo (Claude Code) | 5 | Caminhos reais, arquivo:linha do outro repo, comandos de verificação do próprio projeto |
| Autonomia / execução sem intervenção | 5 | Um único gatilho de parada, e ele é a fronteira certa: ação irreversível ou repositório alheio |
| Verificabilidade | 5 | Critério por fase, suíte nomeada, e as duas perguntas de falha (portal fora do ar, provedor perdido) |
| Calibração | 5 | Enquadramento positivo ("o endereço antigo continua respondendo" em vez de "não quebre os consumidores"); sem CoT nem pedido de auto-verificação |
| Estrutura e ausência de redundância | 5 | Contexto/objetivo/restrições/tarefa/aceite, sem repetir entre seções |
| Robustez | 5 | Cobre os dois modos de falha do desenho — dependência de terceiro e email não verificado — e a regra de fronteira entre repositórios |
| Atualidade | 5 | OIDC code+PKCE, sem implicit flow; nenhum parâmetro obsoleto |

---

## Antes / depois

| Mudança | Efeito esperado |
|---|---|
| "email como chave principal" → "email **verificado pelo provedor** como chave" | Fecha o sequestro de conta por email não verificado, que é o modo de falha clássico de unificação por email |
| Apple/Google sem ressalva → provedores + caminho de emergência preservado | Impede que o agente "limpe" o acesso legado e deixe um terceiro no caminho do dono entrar — a objeção literal do ADR-19 |
| "centralizar módulos" → console que consome API de cada sistema | Evita a leitura de fundir repositórios, que quebraria a regra de independência do portfólio |
| Mudança de domínio sem transição → convivência + item de contrato | Os dois consumidores (BolsIA, MCP) apontam para o endereço atual; corte seco os derrubaria |
| Pedido único → 4 fases, uma por repositório, com aceite próprio | Escopo é multi-sessão e multi-repo; sem fases, o resultado é desenho pela metade |
| Sem referência ao que já existe → aponta o admin atual como base da Fase 3 | O console já tem semáforo de alertas, agenda e custo construídos hoje; começar do zero descartaria isso |

---

## Modelo recomendado

**Perfil:** decisão arquitetural irreversível na prática (identidade e
domínio de todo o portfólio), atravessando três repositórios, com dois
modos de falha silenciosos — dependência de terceiro para o dono entrar, e
unificação de conta por email não verificado.

**Modelo:** `claude-opus-5` para o ADR e o plano de fases; `claude-sonnet-5`
para a implementação de cada fase depois que o desenho estiver aprovado. O
risco aqui não é escrever muito código — é escolher errado uma vez e
carregar a escolha em três sistemas.

**Effort:** `xhigh` na fase de desenho (é onde o trade-off entre
conveniência e dependência de terceiro se decide), `high` nas fases de
implementação. Sessão por fase, e sessão nova ao trocar de repositório.
