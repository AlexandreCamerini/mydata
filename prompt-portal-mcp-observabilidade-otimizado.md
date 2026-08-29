# Portal MCP publica observabilidade e corrige o endereço — pendência da Fase 3 do ADR-23

## Diagnóstico

**Objetivo real:** o repositório `~/dev/MCP` ("Aprendendo MCP na prática") tem
duas pendências abertas no ADR-23 (`docs/contrato-consumidor.md` deste repo,
seção "Pendências de negociação", linhas 134-135): trocar o endereço-base
hardcoded de `mydata.acamerini.app` para `mydata.semente.dev`, e publicar
`GET /observabilidade` no contrato mínimo que o console `admin.semente.dev`
vai agregar.

**Medição antes de escrever (repo `~/dev/MCP`, leitura).** Este não é um
sistema como o Boris+ ou o próprio MyData: é uma trilha de aprendizado de MCP
— um servidor MCP (`servers/mydata/`) mais um portal FastAPI pessoal
(`portal/app.py`) que executa esse servidor como processo filho por stdio,
protegido por senha única e sessão de um visitante por vez
(`E.sessao_unica`). Não tem cron, não tem agendamento, não tem múltiplos
usuários. Isso muda a forma como o contrato de observabilidade se aplica —
ver restrição abaixo.

**O que está medido:**

- `https://mydata.acamerini.app` é o default hardcoded em três pontos:
  `servers/mydata/fonte.py:296`, `servers/mydata/gravar_fixtures.py:126` e
  `:158` (mensagem de log). O valor real de produção nunca vem daqui — chega
  por `MYDATA_URL`, variável de ambiente escrita direto no serviço do
  Railway pelo assistente `scripts/ligar-mydata.sh` (nunca em arquivo). O
  hardcoded só importa como fallback de quem roda sem a variável.
- A chave de produção deste consumidor já existe e não muda:
  `c8125eee` (`docs/contrato-consumidor.md:70` deste repo), escopo `empresa`,
  `demonstracao_financeira`, `negociacao_b3`, `provento_b3` + `fonte:b3`,
  quota 120/min · 5.000/dia. A tarefa é só o endereço.
- O deploy público no Railway fixa `MYDATA_MODO=fixture` no `Dockerfile`, **de
  propósito**: os Termos de Uso da B3 vedam redistribuir dado real de mercado,
  e um deploy público em modo `http` faria exatamente isso
  (`docs/rubrica-mcp.md`, comentário no próprio Dockerfile). `MYDATA_MODO=http`
  só entra quando alguém roda o wizard de propósito, contra um serviço
  específico. Corrigir o endereço não é licença para ligar dado real no
  deploy público.
- `railway.json` já aponta `healthcheckPath: /health`, e `portal/app.py:717`
  já responde `{"ok": E.sessao is not None, "tools": len(E.tools_api)}`. É o
  healthcheck do Railway — não pode mudar de contrato. `/observabilidade` é
  rota nova, aditiva.
- Não existe hoje nenhuma rota `/observabilidade` nem equivalente.
- O estado que este portal realmente tem para reportar: `E.sessao` (sessão
  MCP viva ou não), `E.modo_fonte` (`fixture`/`meta`/`http`),
  `E.fonte_rebaixada` (degradou para fixture depois de tentar a fonte real —
  sinal de alerta genuíno), `E.gasto_usd` / `E.gasto_global_usd` contra
  `TETO_USD_POR_SESSAO` / `TETO_USD_GLOBAL` (orçamento). Não existe execução
  agendada nem histórico de cargas — os campos `ultimas_execucoes` e
  `proximas` do contrato do MyData pressupõem um pipeline com cron, que este
  sistema não tem.
- A entrada do portal é por senha única (`SENHA`) mais cookie de sessão por
  visitante — não há hoje um "machine key" separado do jeito que o MyData usa
  `X-API-Key` para consumidores automatizados. Quem vai chamar
  `/observabilidade` (o console do ADR-23) precisa de alguma forma de
  autenticar que não é a senha de uso interativo.

---

## O prompt otimizado (colar numa sessão do Claude Code em `~/dev/MCP`)

```
<contexto>
Este repositório é a trilha "Aprendendo MCP na prática": um servidor MCP em
servers/mydata/ mais um portal FastAPI pessoal em portal/app.py, que executa
o servidor como processo filho por stdio. Uso pessoal, uma sessão por vez
(E.sessao_unica), protegido por senha única (SENHA) e cookie de sessão por
visitante.

Ele é consumidor do MyData (~/dev/cvm-financas), pela porta que o MyData
define: GET /v1, com header X-API-Key. A chave de produção já existe e não
muda — c8125eee, ver ~/dev/cvm-financas/docs/contrato-consumidor.md:70. O
endereço, sim, precisa mudar: mydata.semente.dev é o endereço primário do
MyData desde 29/08/2026 (mydata.acamerini.app convive até corte decidido
pelo Alex, mas não é mais o padrão a assumir em código novo).

Contexto do ADR-23 (fonte de verdade: ~/dev/cvm-financas/docs/arquitetura.md,
seção ADR-23): o portfólio do Alex converge login e observabilidade em
semente.dev. A Fase 3 estende o admin do MyData para um console agregador em
admin.semente.dev, que consome GET /observabilidade de cada sistema do
portfólio no formato:

  GET /observabilidade
  { "situacao": "ok"|"atencao"|"critico",
    "alertas": [{"severidade", "titulo", "detalhe", "acao"}],
    "ultimas_execucoes": [...],
    "proximas": [...] }

Implementação de referência: ~/dev/cvm-financas/app/api/admin.py:737-753
(rota get_observabilidade), que devolve isso dentro de {"dados": {...}} e é
só o rearranjo de estado que já existia em alertas/execuções/agendamentos —
nada novo é calculado ali.

Este repositório NÃO tem cron nem agendamento — é um portal interativo, não
um pipeline de ingestão. Não existe execução agendada para preencher
ultimas_execucoes/proximas do jeito que o MyData preenche. O estado real
disponível está no objeto de estado do portal (E, em portal/app.py): sessão
MCP viva ou não, modo da fonte (fixture/meta/http), se a fonte degradou para
fixture depois de tentar a real, e o gasto contra os tetos de orçamento por
sessão e global.

Cada repositório é editado na sessão dele: nada aqui edita o MyData. O que
precisar de decisão do lado do MyData vira pergunta para o Alex.
</contexto>

<objetivo>
Dois alvos, independentes entre si:

1. ENDEREÇO — trocar o default hardcoded de mydata.acamerini.app para
   mydata.semente.dev nos pontos onde ele aparece como fallback de código
   (fonte.py, gravar_fixtures.py) e no que scripts/ligar-mydata.sh assume ou
   sugere como endereço, sem alterar a variável de ambiente MYDATA_URL como
   mecanismo — ela continua sendo a fonte de verdade em runtime.
2. OBSERVABILIDADE — publicar GET /observabilidade no contrato do ADR-23,
   mapeado ao que este portal realmente tem para reportar (sessão, modo da
   fonte, degradação, orçamento), sem inventar execuções ou agendamentos que
   não existem aqui.
</objetivo>

<restricoes>
- /health não muda de contrato — railway.json usa healthcheckPath=/health, e
  quebrar o formato quebra o healthcheck do Railway. /observabilidade é rota
  nova, ao lado.
- O deploy público continua com MYDATA_MODO=fixture por padrão no Dockerfile.
  Não ligue modo http em produção como parte desta tarefa — é decisão
  separada do Alex, e existe por causa dos Termos de Uso da B3 (redistribuir
  dado real de mercado num deploy público é o que a rubrica proíbe). Se
  scripts/ligar-mydata.sh referenciar o endereço de algum jeito que pareça
  ligar isso, pare e pergunte antes de mudar o comportamento dele.
- A chave c8125eee não muda — é só o endereço que muda.
- Meça, antes de trocar, todo lugar que ainda referencia mydata.acamerini.app
  (código, docs, scripts) — não assuma que os três pontos já identificados
  são os únicos; grep no repositório inteiro antes de decidir o escopo do
  alvo 1.
- ultimas_execucoes e proximas podem legitimamente vir como lista vazia, com
  uma linha de comentário explicando por quê (este portal não agenda nada) —
  não fabrique uma execução ou um agendamento fictício só para preencher o
  campo.
- Decida como /observabilidade se autentica, e documente a escolha numa
  frase: reaproveitar o gate de SENHA existente, ou expor sem segredo
  adicional por ser ferramenta pessoal de uso único. Implemente uma opção,
  não as duas.
- Nenhuma credencial em commit — MYDATA_TOKEN e SENHA continuam só em
  variável de ambiente.
</restricoes>

<tarefa>
Leia o ADR-23 (~/dev/cvm-financas/docs/arquitetura.md) e
~/dev/cvm-financas/app/api/admin.py:737-753 antes de desenhar o formato.

Entregue os dois alvos do objetivo. Para o alvo 2, decida o mapeamento de
estado → contrato com base no que E já expõe hoje (sessão, modo_fonte,
fonte_rebaixada, gasto vs tetos) — não adicione infraestrutura nova
(banco, fila, scheduler) só para ter o que reportar.

Se esbarrar em decisão que afeta o MyData ou o deploy público em modo http,
pare e traga para decisão em vez de contornar.
</tarefa>

<criterio_de_aceite>
- Nenhuma ocorrência de mydata.acamerini.app sobrevive como default de
  código ou valor sugerido em script — confirme com grep no repositório
  inteiro ao final, não só nos três pontos apontados no diagnóstico.
- GET /health responde exatamente o mesmo formato de antes.
- GET /observabilidade responde as quatro chaves do contrato, com teste
  cobrindo pelo menos um caso "ok" e um caso "atencao" ou "critico"
  (ex.: fonte_rebaixada = True, ou gasto perto do teto).
- A suíte do repositório passa inteira (test_portal.py, test_fonte.py e as
  demais).
- Nenhum token, senha ou client_secret em commit.
</criterio_de_aceite>

Decida sozinho o rotineiro e entregue no escopo acima. Se discordar de
alguma restrição, diga em uma frase e siga.
```

---

## Rubrica de qualidade

| Critério | Nota | Justificativa |
|---|---|---|
| Clareza do objetivo | 5 | Dois alvos independentes, sem dependência entre si, cada um com escopo declarado |
| Adequação ao alvo (Claude Code) | 5 | Caminhos e linhas reais do repositório, referência exata da rota espelho no MyData |
| Autonomia / execução sem intervenção | 4 | Um gatilho de parada (deploy público em http); a decisão de autenticação de `/observabilidade` fica a critério do agente, com opções explícitas — reduz um pouco a autonomia pura em troca de não travar por ambiguidade secundária |
| Verificabilidade | 5 | Aceite por grep total (não só os pontos já achados), teste dos dois cenários de situação, suíte inteira |
| Calibração | 5 | Enquadramento positivo; nenhum pedido de auto-verificação ou CoT |
| Estrutura e ausência de redundância | 5 | Contexto/objetivo/restrições/tarefa/aceite, cada seção com informação nova |
| Robustez | 5 | Cobre a armadilha real deste repo: contrato do ADR-23 foi desenhado para sistema com cron, e este não tem — o prompt resolve isso em vez de deixar o agente inventar dado |
| Atualidade | 5 | Referência à implementação de produção medida nesta semana (admin.py:737-753) |

---

## Antes / depois

| Mudança | Efeito esperado |
|---|---|
| "Trocar o endereço-base" tratado como 1 grep → **grep completo exigido no critério de aceite** | Evita repetir o padrão já visto no Boris+: assumir que os pontos medidos aqui são todos os que existem |
| Contrato do ADR-23 copiado literalmente → **mapeado ao que este sistema tem** | Sem isso, o agente mais provável inventaria `ultimas_execucoes` fictício para um portal que não agenda nada, poluindo o console com dado falso |
| "Publicar /observabilidade" sem tocar `/health` → **contrato de `/health` protegido explicitamente** | `railway.json` usa esse path como healthcheck; um formato novo ali derrubaria o deploy, não só a observabilidade |
| Endereço de produção corrigido sem ressalva → **proibição explícita de ligar `MYDATA_MODO=http` no deploy público** | A troca de endereço não pode virar pretexto para destravar dado real da B3 num serviço público, que é o que o `Dockerfile` existe para impedir |
| Autenticação de `/observabilidade` deixada implícita → **decisão explícita, com as duas opções nomeadas** | Este portal não tem hoje o conceito de "chave de máquina" que o MyData usa; sem apontar isso, o agente teria que inventar um mecanismo sem critério |

---

## Modelo recomendado

**Perfil:** tarefa menor que a Fase 4 do Boris+ — um repositório só, sem OIDC,
sem identificador irreversível no caminho, sem sistema multiusuário. O
julgamento real está em duas decisões contidas: mapear um contrato desenhado
para pipeline com cron a um portal que não tem nenhum, e escolher o mecanismo
de autenticação de uma rota nova sem inventar infraestrutura. Ambas já vêm
com as opções levantadas no prompt.

**Modelo:** `claude-sonnet-5`, effort padrão. Não é caso para `opus`: não há
superfície de produção multiusuário em jogo, o reference implementation está
pronto e citado por linha, e as duas decisões de julgamento têm as
alternativas já nomeadas — o trabalho é decidir entre opções dadas, não
descobri-las.
