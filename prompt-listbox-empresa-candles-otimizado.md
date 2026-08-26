# Três achados de UX/dado — busca de ativo, card de empresa mentiroso, candle

## Diagnóstico do pedido original

> "nas opcoes colocar um listbox com os ativos ou um objeto mais inteligente
> que possa buscar o atiubo. Nas empresas continuo com vaiorar iinformacoes
> que nao apresenta dados. na empresa panamericana por exemplo em varios
> cards ele apresenta 62 linhas mas voce pode selecionar qualquer opcao e nao
> aparece nada. [...] checar se no mydata temos as informacoes historicas de
> candles dos ativos porque eles serao utilizados na analise das opcoes."

Três pedidos distintos, investigados contra o código antes de virar tarefa —
nenhum ficou "acho que":

**1. Busca de ativo em Negociação — confirmado.** [Negociacao.tsx](web/src/apresentacao/Negociacao.tsx)
tem um `<input placeholder="PETR4">` de texto livre, sem autocompletar. O
backend já tem o que precisa pra virar busca de verdade: `/v1/empresas?q=...`
já existe, já pagina, e devolve `ticker`. Não precisa de rota nova, precisa de
componente novo — um combobox com debounce, mesmo padrão que `Busca.tsx` já
usa (`atraso` com `setTimeout(500ms)`).

**2. Card de empresa mentindo sobre "62 linhas" — causa raiz encontrada, não
suposta.** Rastreei os três pontos:
- `app/api/main.py:898` — o resumo agrega com `GROUP BY grupo, upper(tipo_doc),
  consolidado`. Cada linha de `demonstracoes` no resumo já vem **separada**
  por consolidado/individual.
- [Empresa.tsx](web/src/apresentacao/Empresa.tsx), `porFamilia` — soma
  `linhas` de todos os grupos da família **sem filtrar por `consolidado`**
  (`r.demonstracoes.filter((d) => f.grupos.includes(d.grupo))` seguido de
  `.reduce((s, d) => s + d.linhas, 0)`). O card mostra a soma dos dois modos
  juntos.
- [Demonstracoes.tsx](web/src/apresentacao/Demonstracoes.tsx) abre sempre com
  `consolidado: true` (linha ~116), **independente de qual dos dois modos
  tem o dado**.

Ou seja: quando a Panamericana só publicou individual (comum em holding sem
demonstração consolidada), o card soma as linhas do individual, mostra "62
linhas", e a tela abre no modo consolidado — que está vazio. Não é falha de
apresentação, é o card e a tela usando critérios diferentes pra "tem dado".

**3. Candle histórico — já existe, não precisa checar de novo, precisa
expor.** `app/seed_fontes.py:811-819`, a vista `gold_cotacoes`: `SELECT
preco_abertura, preco_maximo, preco_minimo, ..., preco_fechamento FROM
fato_negociacao` — OHLC completo, `preco_abertura` incluso, direto do
COTAHIST (`COLUNAS_COTAHIST`, campo `PREABE`). `/v1/cotacoes/{ticker}`
(`app/api/main.py:634`) faz `SELECT *` sobre essa vista — o campo já viaja na
resposta da API hoje. O furo é só no front: o tipo `Cotacao` em
[apresentacao/api.ts](web/src/apresentacao/api.ts) declara
`preco_fechamento`/`preco_maximo`/`preco_minimo` mas **não declara
`preco_abertura`** — o dado chega e o TypeScript não deixa usar. Resposta
direta pro Alex: sim, MyData tem candle diário completo (O, H, L, C, volume)
desde que o COTAHIST correspondente foi carregado; só falta o tipo do front
acompanhar o que a API já devolve.

## O prompt otimizado (para colar numa sessão do Claude Code neste repositório)

```
<context>
Três tarefas independentes no MyData (React 19 + Tailwind v4 em web/src/,
FastAPI em app/). Cada uma já foi investigada — não redescubra a causa raiz,
implemente a partir dela.

1. web/src/apresentacao/Negociacao.tsx tem um <input> de texto livre para o
   ticker (placeholder="PETR4"), sem autocompletar. /v1/empresas?q=... já
   existe, pagina, e devolve `ticker` — é a fonte de busca. Busca.tsx já tem
   o padrão de debounce a copiar (`atraso` + setTimeout 500ms).

2. Empresa.tsx soma `linhas` de todos os grupos de uma família SEM filtrar
   por `consolidado` (cada ResumoDemonstracao já vem separada por
   consolidado — confirmado em app/api/main.py:898, GROUP BY inclui
   `consolidado`). Demonstracoes.tsx abre sempre com `consolidado: true`
   (linha ~116), então quando uma empresa só publicou no modo individual, o
   card mostra a soma errada e a tela abre vazia no modo que não tem dado.

3. A vista gold_cotacoes (app/seed_fontes.py:811-819) e a rota
   /v1/cotacoes/{ticker} (app/api/main.py:634, SELECT *) já devolvem
   preco_abertura — candle OHLC completo já existe na API. Só o tipo
   `Cotacao` em web/src/apresentacao/api.ts não declara esse campo.
</context>

<task>
Tarefa 1 — Busca de ativo em Negociação:
Substitua o <input> de texto livre em Negociacao.tsx por um combobox com
busca ao vivo contra /v1/empresas?q=&listada_b3=true, mostrando nome +
ticker, navegável por teclado (seta/enter/escape), com debounce igual ao de
Busca.tsx. Sem biblioteca nova — o projeto não usa dependência de UI de
terceiro (ver CLAUDE.md, filosofia de zero-dependência já seguida em Api.tsx).

Tarefa 2 — Card de empresa não pode prometer dado que a tela não mostra:
Em Empresa.tsx, corrija porFamilia para não somar consolidado e individual
juntos — decida um critério único por família (ex.: prefira consolidado
quando ele tiver linha > 0, senão individual) e propague essa escolha para o
link, para que Demonstracoes.tsx abra no modo que de fato tem o dado (via
query param ou prop), em vez de sempre abrir consolidado=true. O card
continua mostrando "o que existe", só que agora o clique leva pro lugar
certo.

Tarefa 3 — Expor preco_abertura no tipo Cotacao:
Adicione `preco_abertura: number | null` ao tipo `Cotacao` em
web/src/apresentacao/api.ts, no mesmo formato dos outros campos de preço.
Não construa gráfico de candle agora — isto é só destravar o dado que a API
já entrega para quem for construir a visualização depois.
</task>

<constraints>
- Um commit por tarefa concluída, como o resto do projeto já faz.
- Não adicione dependência nova (biblioteca de combobox, date-picker, etc.) —
  zero-dependência é decisão de arquitetura deste projeto, não descuido.
- Não mude o schema do banco nem a vista gold_cotacoes — a Tarefa 3 é
  front-end puro, o dado já existe.
- Antes de mexer em Empresa.tsx/Demonstracoes.tsx, confirme lendo o código
  atual se a estrutura descrita acima ainda bate — pode ter mudado depois
  desta investigação.
- Rode `npm run build` depois de cada tarefa. Se a Tarefa 1 ou 2 forem
  observáveis num servidor local, verifique no navegador antes de dar por
  pronta — sessão de dev local sem PORTAL_API_ABERTA pode bloquear a
  apresentação pública; se isso acontecer, documente e não tente contornar
  autenticação.
</constraints>

<acceptance_criteria>
Tarefa 1: digitar 2+ letras no campo de Negociação mostra sugestões reais de
/v1/empresas; selecionar uma navega para a cadeia de opções do ticker certo;
teclado funciona sem mouse.

Tarefa 2: para uma empresa que só publicou um dos dois modos (consolidado ou
individual), o número de linhas no card bate com o que a tela de
demonstrações mostra ao abrir — não pode abrir vazia quando o card promete
dado.

Tarefa 3: `tsc -b` passa; o tipo Cotacao inclui preco_abertura; nenhum outro
comportamento muda.
</acceptance_criteria>

Decida sozinho os detalhes de implementação de cada tarefa — não pare para
perguntar formato de UI ou nome de variável. Pare e pergunte só se ao ler o
código atual a estrutura que este prompt descreve (GROUP BY, tipos, campos)
não bater mais com o que está no repositório.
```

*Este prompt é para uma ferramenta agêntica com acesso real ao sistema
(Claude Code). Confira o caminho dos arquivos citados antes de colar — o
projeto pode ter mudado desde que este prompt foi gerado. Revise escopo e
condições de parada antes de rodar.*

---

## Rubrica de qualidade

| Critério | Nota | Justificativa |
|---|---|---|
| Clareza do objetivo | 5 | Três tarefas, cada uma com uma ação e um arquivo-âncora |
| Adequação ao alvo (Claude Code) | 5 | Caminhos reais, linha citada, comando de verificação executável |
| Autonomia / execução sem intervenção | 5 | Único gatilho de parada é a estrutura ter mudado — não pede aprovação de formato |
| Verificabilidade (critério de aceite + evidência) | 5 | Cada tarefa tem um teste manual concreto, não "parece certo" |
| Calibração (tom, sem CoT nem verificação redundante) | 5 | Nenhuma instrução de "pense passo a passo"; restrições em enquadramento positivo |
| Estrutura e ausência de redundância | 5 | Causa raiz já resolvida no diagnóstico — o prompt não pede pra redescobrir |
| Robustez (guardrails, bloqueio externo, continuidade) | 4 | Cobre a limitação de auth local já conhecida; não cobre o que fazer se `/v1/empresas` mudar de contrato — risco baixo, não valia instrução extra |
| Atualidade (parâmetros e modelos correntes) | 5 | Nenhum parâmetro obsoleto |

---

## Antes / depois

| Mudança | Efeito esperado |
|---|---|
| "checar se temos candle" → resposta fechada nesta investigação, não delegada ao agente | Claude Code não perde uma chamada de ferramenta redescobrindo o que já é fato: `preco_abertura` está em `gold_cotacoes` e na resposta da API |
| "não aparece nada" vago → causa raiz nomeada (soma sem filtrar consolidado, tela abre no modo errado) | Agente corrige o mecanismo, não só re-busca o sintoma numa empresa aleatória |
| "listbox ou objeto mais inteligente" → especificado como combobox contra endpoint já existente | Evita o agente escolher um componente de terceiro que quebraria a filosofia zero-dependência |
| Três pedidos numa frase só → três tarefas com commit e critério de aceite próprios | "Pronto" vira checável por tarefa, não promessa única no fim |

---

## Modelo recomendado

**Perfil**: duas tarefas são correção de lógica com causa raiz já isolada
(baixo risco de exploração, alto risco de "parecer resolvido" sem estar —
por isso o critério de aceite é comportamental, não visual) e uma é
componente de UI novo sem biblioteca.

**Modelo**: `claude-opus-5` — a Tarefa 2 mexe em dois arquivos que se
comunicam por uma decisão implícita (qual modo abrir); errar a propagação
silenciosamente troca um bug óbvio ("não aparece nada") por um sutil
("abre o modo errado só às vezes"). Vale o tier mais forte.

**Effort**: `high` — nenhuma das três é decisão arquitetural nova, mas a
Tarefa 2 pede leitura correta de como dois componentes hoje divergem antes de
escrever a correção; `medium` arrisca aplicar a correção óbvia (filtrar por
`consolidado: true` sempre) em vez da correta (abrir o modo que tem dado).
