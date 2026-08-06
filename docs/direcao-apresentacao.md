# Direção do redesenho

O que o produto vira, decidido contra os achados de
[auditoria-apresentacao.md](auditoria-apresentacao.md). A decisão da camada de
acesso está no [ADR-19](arquitetura.md#adr-19--passkey-entra-ao-lado-do-token-não-no-lugar).

---

## 1. O que vale copiar, e por quê cabe aqui

Quatro categorias de produto resolvem partes deste problema. O que interessa é
o mecanismo, não o nome — e o filtro é sempre o mesmo: **este hub tem um dono e
poucos consumidores máquina**, não mil usuários. Metade do que uma plataforma
de dado faz existe para coordenar equipes que aqui não existem.

| Mecanismo | Vem de | Por que cabe |
|---|---|---|
| **Linhagem como caminho navegável** — clicar num campo e subir até a origem | Catálogos de dado | O hub já calcula isso em `/v1/meta/linhagem` e não mostra. É a promessa central do produto virando clique |
| **Saúde por entidade, não por job** | Observabilidade de dado | Já é o modelo de `observabilidade.frescor`: quem opera pensa "a Empresa está velha", não "o `cvm_cadastro` não rodou" |
| **Linha do tempo de execução por fase** | Rastreamento distribuído | `log_fase` já grava fase e duração. Foi o que revelou que `calcular` levava 119 s |
| **Grid virtualizado com coluna congelada** | Ferramentas de planilha e dado denso | Obrigatório: um pregão tem 15 mil linhas e a cadeia da PETR4 tem 748 contratos |
| **Escopo e quota visíveis na credencial** | Consoles de infraestrutura | Já existe no modelo de chave; falta a tela dizer o que a chave alcança |

**O que deliberadamente não se copia.** Colaboração, comentário, aprovação,
papel e permissão por time, glossário de negócio colaborativo, alerta por
canal. Tudo isso resolve coordenação entre pessoas, e aqui há uma. Adotar
custaria complexidade permanente por um problema que o produto não tem.

---

## 2. Direção de arte

Quatro conjuntos de token, cada um substituindo o bloco `@theme` de
[`web/src/index.css`](../web/src/index.css). Trocar de direção é trocar este
bloco — oito linhas.

**Regra que vale nos quatro:** o nome do token é semântico, nunca cor.
`--color-acento`, não `--color-indigo`. Token com nome de cor trava a paleta no
código e transforma a troca de direção em busca-e-substitui.

### A — Arquivo *(construída)*

O registro oficial. Papel morno, tinta profunda, acento índigo. Serifada só
no display; o dado continua em grotesca, porque serifa em grid de número
atrapalha.

```css
--color-tinta: #14161a;  --color-tinta-suave: #4a515c;
--color-papel: #faf8f4;  --color-borda:      #ddd6c9;
--color-acento: #2f3d8f;
--color-alerta: #8a4b00; --color-erro: #99131a; --color-ok: #1c5c34;
```

### B — Terminal

Superfície escura, monoespaçado adiantado, acento ciano. Densidade de console
de operador.

```css
--color-tinta: #e6edf3;  --color-tinta-suave: #8b98a5;
--color-papel: #0d1117;  --color-borda:      #2a323c;
--color-acento: #2dd4bf;
--color-alerta: #d29922; --color-erro: #f85149; --color-ok: #3fb950;
```

### C — Instituto

Cinza-azulado frio, grotesca, acento igual à cor de foco que já existe
(`--cor-foco: #1f5fb8`). O mais sóbrio dos quatro, e o que menos muda o que
está lá.

```css
--color-tinta: #12181f;  --color-tinta-suave: #5a6673;
--color-papel: #f7f9fb;  --color-borda:      #d3dae2;
--color-acento: #1f5fb8;
--color-alerta: #8a4b00; --color-erro: #99131a; --color-ok: #1c5c34;
```

### D — Pregão

Neutros quentes, acento verde-azulado. Fala de mercado sem cair no
vermelho-e-verde, que aqui são cores de estado e não de direção de preço.

```css
--color-tinta: #1a1714;  --color-tinta-suave: #57504a;
--color-papel: #fcfaf7;  --color-borda:      #e0d8cd;
--color-acento: #0f766e;
--color-alerta: #9a5b00; --color-erro: #a01c22; --color-ok: #15803d;
```

### Por que A foi a construída

O diferencial do produto sobre um agregador é a proveniência: o arquivo
original guardado, com `sha256`, reconstruível. **A** é a única das quatro que
diz isso visualmente — papel e registro. **B** é a mais bonita para o operador
e a pior para a apresentação, que é leitura, não console. **C** é segura e não
diz nada. **D** é agradável e genérica.

A escolha é reversível: as quatro estão em
[`web/src/temas.css`](../web/src/temas.css), e trocar é uma linha de `@import`.

---

## 3. Objetos gráficos

Seis classes. Para cada uma: o dado que consome, os estados e o que ela
precisa fazer.

### 3.1 `Grid` — tabela de dado denso

**Consome:** qualquer lista paginada por cursor de `/v1`.
**Nasce virtualizado** — a auditoria mostrou que nenhuma tabela atual é, e um
pregão tem 15 mil linhas.

Coluna congelada à esquerda, ordenação, densidade em dois níveis, e **célula
que revela proveniência** — o gesto que fecha o buraco 3.3 da auditoria.
Estados: vazio com dica do que fazer, carregando com esqueleto do tamanho
certo, erro com o que falhou e o que tentar, parcial quando o cursor tem mais.

### 3.2 `SaudeClasse` — painel de saúde por entidade

**Consome:** `/v1/meta/frescor` + contagem por classe.
Por classe: frescor contra o SLA declarado, volume, quanto o gate reteve,
última publicação e última falha lado a lado — uma classe pode estar em dia e
ter quebrado ontem, e as duas informações precisam aparecer juntas.

### 3.3 `Linhagem` — o caminho até a origem

**Consome:** `/v1/meta/linhagem?classe=&atributo=`.
De um atributo até a captura: expressão do campo calculado, colunas que ele
usa, regras que o vigiam, precedência quando disputado, e a captura com
`sha256` e link para o arquivo. É `/v1/capturas/{id}/arquivo` ganhando um
clique.

### 3.4 `LinhaDoTempo` — execução fase a fase

**Consome:** `/admin/api/execucoes/{id}/fases`.
Barras proporcionais à duração, com o que cada fase produziu. Já existe em
`Execucoes.tsx` como lista; vira objeto reutilizável e ganha proporção
visual — foi assim que os 119 s de `calcular` apareceram.

### 3.5 `Serie` — observabilidade no tempo

**Consome:** `relatorio_carga` via `/admin/api/carga`.
Disco, custo e duração por carga. Sem biblioteca de gráfico: SVG próprio, que
é o que cabe em quatro séries simples e evita dependência.

### 3.6 `CadeiaOpcoes` — a tela que não existe

**Consome:** `/v1/opcoes/{ticker}`, `/v1/opcoes/{ticker}/vencimentos`,
`/v1/cotacoes/{ticker}`.
Vencimentos como filtro, contratos no `Grid`, strike contra prêmio, e a
comparação que a camada de opções existe para fazer: **implícita contra
realizada** — `volatilidade_implicita` do contrato ao lado de `hv21_objeto` do
papel.

Trata nulo como fato, não como zero: 10% dos contratos não têm implícita
porque o prêmio ficou fora do alcance do modelo, e a tela precisa dizer isso
em vez de mostrar um traço mudo.

---

## 4. Ordem da construção

Do mais barato e mais visível para o mais caro, com uma exceção deliberada.

| Etapa | O que | Fecha |
|---|---|---|
| 1 | Tokens com acento vivo + `temas.css` | 1.1 |
| 2 | Mensagem de sessão em vez de erro de API cru | 2.3 |
| 3 | `Grid` virtualizado + revelação de proveniência | 3.3, restrição técnica |
| 4 | `CadeiaOpcoes` — a classe invisível ganha tela | 3.1, 2.1 |
| 5 | `SaudeClasse`, `Linhagem`, `LinhaDoTempo`, `Serie` | 2.1, 2.2, 3.2 |
| 6 | Camada de acesso, aditiva | 5.2 |

A camada de acesso vai por último porque é a única que pode trancar o dono
fora do próprio sistema. Ela merece a base estável embaixo e o `PORTAL_ACESSO_LEGADO`
já documentado.
