# Auditoria da camada de apresentação e configuração

Estado real das duas superfícies visuais do MyData em 05/08/2026, medido
contra o código e contra a interface rodando. Cada achado diz onde está, o que
causa a quem usa, quanto pesa e quanto custa consertar.

**Como ler a severidade.** *Alta* significa que a capacidade existe e o usuário
não alcança, ou que a tela afirma algo que não é verdade. *Média*, que o
trabalho é possível mas mais caro do que precisaria. *Baixa*, incômodo sem
consequência.

**Resumo em três linhas.** A acessibilidade está sólida e é o que menos precisa
de trabalho. A maior classe de dado do sistema não tem uma tela. E o sistema de
design declara um acento que não existe — o que explica por que tudo parece
plano.

---

## 1. Design e direção de arte

### 1.1 O acento é uma cor morta — severidade alta para o resultado visual

[`web/src/index.css:15`](../web/src/index.css) declara
`--color-acento: #10151c`, que é **o mesmo valor** de `--color-tinta` na linha
8. E `acento` aparece **zero vezes** em componentes `.tsx`.

Duas consequências que se somam. A paleta tem oito tokens e efetivamente
quatro cores: tinta, tinta-suave, papel, borda — mais três de estado (alerta,
erro, ok) que só aparecem em selo. Não existe cor que diga "isto aqui
importa", então a hierarquia inteira recai sobre tamanho e peso de fonte.

É a causa raiz da impressão de planura na tela de Classes: título grande,
tabela cinza, um único botão preto. Nada compete pela atenção porque nada tem
permissão para competir.

**Custo:** baixo. É o token que já existe passar a ter valor próprio e ser
usado em ação primária, link e estado ativo.

### 1.2 Tipografia é a pilha do sistema, sem escala declarada

[`web/src/index.css:36`](../web/src/index.css) usa
`ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif`. Não há
fonte de display, não há escala tipográfica declarada, e o tamanho de cada
texto é decidido no componente com utilitário do Tailwind.

O efeito: o produto não tem voz visual. Um hub de dado financeiro auditável
podia dizer isso na tipografia — e diz o mesmo que um formulário administrativo
qualquer.

**Custo:** médio. Escolher a fonte é barato; aplicar consistentemente exige
passar pelas 19 telas.

### 1.3 Densidade sem ritmo — severidade média

Na tela de Classes, a coluna *Identidade* despeja
`cd_cvm,tipo_doc,dt_refer,grupo,consolidado,cd_conta,ordem_exerc,versao` como
uma corrida única de monoespaçado
([`web/src/telas/Classes.tsx`](../web/src/telas/Classes.tsx)). São oito
atributos que o olho tem de separar por vírgula. A linha da tabela cresce para
acomodar, e o ritmo vertical se perde.

Chave de identidade é justamente o conceito central do sistema — merece ser
lida como lista de partes, não como string.

---

## 2. UX e processo

### 2.1 A classe é um beco sem saída — severidade alta

A tela de Classes lista quatro classes com atributos, fontes, frescor e
situação. **Nenhuma leva ao dado.** "Negociação na B3, 40 atributos, em dia" e
o caminho acaba ali.

O operador que quer conferir um número precisa sair da interface: `curl` com
chave de API, ou consulta direta ao banco. O portal exibe o catálogo de um
acervo cuja estante ele não abre.

**Custo:** alto — é tela nova. É também o item de maior retorno da auditoria.

### 2.2 Gestão e Carga e custo se sobrepõem e nenhuma fecha — severidade média

Gestão mostra "Espaço do original: 915 kB", que é bronze
([`app/api/admin.py`](../app/api/admin.py), `get_gestao`). Carga e custo mostra
disco total, custo mensal e projeção
([`web/src/telas/Carga.tsx`](../web/src/telas/Carga.tsx)). São a mesma
pergunta — quanto isto pesa — respondida em dois lugares, cada um com metade.

Quem abre Gestão para saber o tamanho do hub recebe o número menos relevante:
915 kB de bronze contra 2,11 GB de banco em produção.

### 2.3 O erro de API chega cru ao usuário final — severidade alta

Abrindo `/` sem sessão, a apresentação mostra em caixa vermelha:

> Informe uma chave válida no cabeçalho X-API-Key.

É a mensagem de [`app/api/main.py`](../app/api/main.py) (`exigir_chave`),
escrita para quem consome a API por programa, exibida para quem abre um site.
O usuário final não tem como definir um cabeçalho HTTP, e a frase não diz o
que ele deveria fazer — entrar.

Este é o problema do token, concreto na tela: a superfície de leitura humana
herda o vocabulário da superfície de máquina.

### 2.4 "Atualizada há 5 h" sem a data absoluta — severidade baixa

Tempo relativo é bom para leitura rápida e ruim para conferência. Não há
`title` com o instante exato em nenhuma das telas que mostram frescor.

---

## 3. Integração — capacidade construída e invisível

Comparei os endpoints `GET` publicados com o que qualquer arquivo do front
alcança. **23 publicados, 16 nunca alcançados por caminho `/v1`** — mas boa
parte tem gêmeo em `/admin/api` e está visível. Filtrando por *capacidade*, e
não por URL, sobram quatro buracos reais.

### 3.1 A classe `negociacao_b3` não existe na interface — severidade alta

Busca por `negociacao_b3`, `b3_cotahist`, `ticker_objeto` e `preco_exercicio`
em `web/src/`: **zero ocorrências.** Idem `cotacoes`, `hv21`, `volatilidade`.

O que está fora da tela: 384.875 linhas em produção, das quais **329.262
contratos de opção**, com 295.835 volatilidades implícitas, gregas, prazo e
ativo-objeto resolvido. Três rotas servidas e nunca chamadas por navegador —
`/v1/opcoes/{ticker}`, `/v1/opcoes/{ticker}/vencimentos`,
`/v1/cotacoes/{ticker}`.

É a maior classe do sistema por volume, a mais recente, e a única sem qualquer
representação visual.

### 3.2 Correlação entre classes é invisível — severidade média

`cfg_correlacao` guarda as travessias declaradas, `/v1/meta/correlacoes` as
lista e `/v1/correlacoes/{chave}` as executa. O front cita `correlac` em um
único arquivo, sem tela dedicada.

A correlação existe justamente para o consumidor não reinventar a junção — e
o dono não consegue ver quais existem sem ler o banco.

### 3.3 O arquivo original não é alcançável por clique — severidade média

Toda resposta de dado carrega `proveniencia.arquivo_em`, um caminho para
`/v1/capturas/{id}/arquivo` — o ZIP como a fonte publicou, conferível pelo
`sha256` ao lado. `arquivo_em` aparece **zero vezes** em `web/src/`.

A promessa central do produto — proveniência auditável — para um clique antes
do fim.

### 3.4 `/v1/meta/contrato` não tem consumidor — severidade baixa

A rota entrega o perfil ODCS da classe: atributos, colunas de origem, o que a
normalização faz, o que a qualidade vigia. Foi construída para ser o contrato
publicado e nenhuma tela a lê.

---

## 4. Acessibilidade — a frente que está boa

Medido com `axe-core 4.12.1` em `chrome-headless`, nas dez abas do admin e na
apresentação:

| Superfície | Violações |
|---|---|
| `/` (apresentação) | 0 |
| `/admin/` e as nove abas restantes | 0 |

Zero violação automatizada em onze páginas. O `index.css` trata foco visível e
pular-para-conteúdo como requisito de aceite e não como estilo, com comentário
dizendo isso. `@axe-core/cli` já está no `package.json` com script `a11y`.

**Dois pontos ficam em aberto**, e nenhum é detectável por automação:

- O script só aponta para `/admin/`. A apresentação passa, mas passa sem estar
  no portão — nada impede uma regressão lá.
- Automação cobre entre 20% e 50% dos problemas. Navegação por teclado nos
  formulários longos (`DatasetForm.tsx`, 590 linhas) e leitura por leitor de
  tela nas tabelas não foram verificadas manualmente.

**Consequência para o redesenho:** isto é linha de base a não perder. Qualquer
componente novo entra com a mesma barra.

---

## 5. Camada de acesso

### 5.1 O que o modelo atual realmente oferece

`PORTAL_ADMIN_TOKEN` é um segredo único de 43 caracteres, comparado com
`hmac.compare_digest` em [`app/api/auth.py`](../app/api/auth.py). Desde o
commit de hoje, vale por cookie `HttpOnly` `SameSite=Lax` de 30 dias ou pelo
cabeçalho `X-Admin-Token`, nas duas superfícies.

Propriedades reais, sem elogio nem exagero: o segredo tem entropia suficiente,
não trafega em URL, não fica em `localStorage`, e o CSRF está coberto por
`SameSite=Lax` mais CORS negado por omissão mais JSON com verificação prévia.
Para um sistema de dono único, isso não é frágil.

### 5.2 Onde falha — severidade alta para quem usa

Quatro propriedades que faltam, em ordem de quanto incomodam:

1. **Não há identidade.** O token diz que alguém sabe o segredo, não quem.
   Nenhuma auditoria de acesso é possível.
2. **Não há revogação individual.** Trocar o token derruba todas as sessões e
   todo script ao mesmo tempo.
3. **É digitado à mão.** Um segredo de 43 caracteres copiado de um painel é
   exatamente o que o gerenciador de senhas existe para evitar, e é a queixa
   registrada.
4. **Não expira de forma útil.** Trinta dias de cookie sem renovação por uso e
   sem prazo no próprio segredo.

### 5.3 O que não é problema, e vale registrar

A chave de API por consumidor em `/v1` é outro mecanismo, com hash em repouso,
escopo por classe, quota por minuto e por dia e revogação por prefixo. Está
bem resolvida e **não deve ser tocada** pelo redesenho da autenticação humana.

Confundir as duas é o erro mais fácil de cometer aqui: passkey resolve o
navegador do dono e não tem nada a dizer sobre `curl`.

---

## Prioridade sugerida

| # | Achado | Severidade | Custo |
|---|---|---|---|
| 1 | `negociacao_b3` sem tela (3.1) | alta | alto |
| 2 | Erro de API cru para o usuário final (2.3) | alta | baixo |
| 3 | Acento morto (1.1) | alta para o visual | baixo |
| 4 | Classe é beco sem saída (2.1) | alta | alto |
| 5 | Arquivo original sem clique (3.3) | média | baixo |
| 6 | Gestão e Carga sobrepostas (2.2) | média | médio |
| 7 | Correlação invisível (3.2) | média | médio |
| 8 | Tipografia sem voz (1.2) | média | médio |
| 9 | Identidade como corrida de texto (1.3) | média | baixo |
| 10 | `/v1/meta/contrato` órfã (3.4) | baixa | médio |
| 11 | Tempo relativo sem absoluto (2.4) | baixa | baixo |

**Situação em 05/08/2026.** Fechados: 1 a 7, 9, 10 e 11. Aberto: o **8**
(tipografia sem voz). A direção de arte da fase 2 deu a fonte de display — a
serifada do conjunto A, aplicada em `h1`/`h2` — mas a escala tipográfica
continua decidida no componente, com utilitário do Tailwind. É o que sobra.

Os itens 2, 3 e 5 são de custo baixo e efeito imediato — cabem na primeira
etapa da construção. O 1 e o 4 são a mesma tela vista de dois ângulos, e é
onde está o valor.

---

## Uma restrição técnica que a construção precisa respeitar

Nenhuma tabela da interface é virtualizada ou paginada — busca por `virtual`
em componentes `.tsx` não retorna nada, e o catálogo pede
`?limite=10`. Todas renderizam a lista inteira.

Isso funcionou porque nenhuma tela mostra mais que dezenas de linhas. A tela
de negociação mudaria isso: um único pregão tem 15 mil linhas, e a cadeia de
opções da PETR4 sozinha tem 748 contratos. O grid precisa nascer virtualizado,
ou nasce quebrado.
