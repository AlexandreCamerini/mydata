# Console de API no admin — MyData

## Diagnóstico do pedido original

> "PRECISAMOS CRIAR UMA PAGINA DE ADMINISTRACAO COM O SWAGGER DE TODAS AS APIS
> Q ESTAO SENTO EXPOSTAS PERMITINDO O TESTES E A DOCUMENTACAO DAS MESMAS"

- **Objetivo real**: uma tela dentro do admin já existente onde dá para
  navegar e **testar de verdade** (não só ler) cada rota exposta pela API,
  sem manter documentação à parte que desalinha do código.
- **Ambiguidade que precisava de decisão, não de pergunta**: "swagger de
  todas as APIs" podia significar (a) liberar o `/docs` padrão do FastAPI,
  (b) embutir um console dentro do admin autenticado. A primeira já existe
  hoje, pública, sem login — então o pedido só faz sentido como a segunda; a
  primeira não precisava de tarefa nova. Resolvido abaixo, não perguntado.
- **Furo de autonomia**: "todas as APIs" mistura duas famílias com
  autenticação diferente — `/admin/api/*` (sessão do admin) e `/v1/*` (chave
  de API por consumidor). Um prompt raso pediria "teste tudo" sem dizer como
  autenticar cada família, e a implementação pararia no primeiro 401.
- **Risco técnico não óbvio**: o front deste projeto não tem nenhuma
  dependência de UI além de `react`/`react-dom` — é deliberadamente enxuto
  (roteamento por hash escrito à mão em vez de `react-router`, componentes
  próprios em vez de biblioteca de componentes). O pacote mais comum para
  isto, `swagger-ui-react`, embrulha o `swagger-ui` core numa camada que
  historicamente atrasa para acompanhar versão nova de React, e o projeto
  está em React 19. Resolvido abaixo: usar o core, não o wrapper.
- **Lacuna de verificabilidade**: "permitindo testes" sem dizer o que conta
  como teste bem-sucedido. Fechado abaixo com critério de aceite checável.

---

## O prompt otimizado (para colar numa sessão do Claude Code neste repositório)

```
<context>
MyData (~/dev/cvm-financas) é um hub de dados com engine único: app/motor,
app/api e app/migracoes.py não conhecem CVM nem B3, fonte nova é config, não
código. O backend (FastAPI, app/api/main.py) já gera OpenAPI/Swagger
automaticamente em /openapi.json — 52 rotas publicadas hoje, /docs e /redoc
públicos e sem login (FastAPI padrão, não mexer nisso).

O admin (web/src/, React+Vite+TS+Tailwind) é servido pelo mesmo processo
FastAPI, com roteamento por hash escrito à mão — não há react-router. As
telas moram em web/src/telas/*.tsx, uma por arquivo, registradas no array
TELAS de web/src/App.tsx (id, titulo, componente, resumo). Hoje são 13:
Gestao, Classes, Fontes, Datasets, Calculados, Qualidade, Execucoes, Carga,
Chaves, Catalogo, Acesso, ClasseForm, DatasetForm. Todas usam os primitivos
de web/src/ui.tsx (Aviso, Botao, Campo, Carregando, Confirmar, Erro, Selo,
Tabela, Vazio, useDados) e o mesmo temas.css — nenhuma foge do sistema
visual.

Duas famílias de rota, duas autenticações:
- /admin/api/* — protegida por sessão do admin (cookie), ver
  app/api/admin.py (dependencies=[Depends(exigir_admin)]).
- /v1/* — protegida por chave de API por consumidor, header X-API-Key
  (ver app/api/main.py, Header(alias="X-API-Key")), com escopo por classe.

web/package.json hoje só tem react e react-dom como dependência de runtime
— nenhuma biblioteca de UI. Isso é deliberado, não esquecimento.
</context>

<task>
Adicione uma 14ª tela ao admin, "API", com um console interativo de API:
lista toda rota exposta lendo o /openapi.json ao vivo do próprio backend
(nunca uma cópia mantida à mão — se desalinhar do código, o bug é a cópia),
agrupada por tag, com "Try it out" funcional nas duas famílias de rota.
</task>

<constraints>
- Dependência: prefira o pacote `swagger-ui` (core, sem framework), não
  `swagger-ui-react` — monte-o imperativamente num container ref dentro do
  componente React. Isso evita amarrar a versão do React do projeto (19) à
  versão que o wrapper aceitar. Antes de instalar, confira compatibilidade;
  se o instalador acusar conflito de peer-dependency, pare e relate em vez
  de forçar com --force ou --legacy-peer-deps.
- A tela nova segue o sistema visual existente: primitivos de ui.tsx,
  temas.css, mesma voz do resumo das outras 13 entradas em TELAS. Não é um
  iframe nem um embed que destoa do resto do admin.
- "Try it out" em /admin/api/* funciona sozinho, via cookie de sessão
  (fetch same-origin já carrega isso — nenhuma configuração extra do
  swagger-ui deveria ser necessária além de credentials: 'include' se ele
  não fizer isso por padrão).
- "Try it out" em /v1/* precisa de um campo onde o operador cola uma chave
  de API, injetada via requestInterceptor do swagger-ui como header
  X-API-Key. Nunca grave a chave em localStorage, cookie ou estado
  persistente — só em memória do componente, e ela some ao sair da tela.
- Não toque em /docs, /redoc nem /openapi.json do FastAPI — continuam
  públicos e sem login, como estão hoje. Esta tela é um console autenticado
  adicional, não substitui nem esconde os existentes.
- Não adicione autenticação, funcionalidade ou tela além do pedido.
</constraints>

<acceptance_criteria>
Pronto quando, verificado de verdade e não apenas assumido:
1. A tela "API" aparece no menu do admin e lista as rotas do /openapi.json
   vigente, agrupadas por tag.
2. Um "Try it out" contra uma rota de /admin/api/* executa de verdade e
   mostra a resposta real, usando a sessão do admin já autenticada.
3. Um "Try it out" contra uma rota de /v1/*, depois de colar uma chave de
   API válida, executa e mostra a resposta real com os campos de
   proveniência (fonte, dt_captura etc.).
4. npm run build e npm run test (web/) passam.
5. Screenshot da tela nova ao lado de uma tela existente (ex.: Catalogo)
   mostra consistência visual — mesma tipografia, mesmas cores, mesmo
   espaçamento.
</acceptance_criteria>

Decida os detalhes de implementação sozinho — nome exato de variável,
onde guardar a chave de API em memória, como agrupar por tag. Pare e
pergunte só se o instalador do pacote reportar conflito real de
dependência, ou se precisar mudar algo fora de web/.
</task>
```

*Este prompt é para uma ferramenta agêntica com acesso real ao sistema
(Claude Code). Confira os limites de escopo e os pontos de parada antes de
colar — em especial, os caminhos web/src/App.tsx e web/src/telas/ precisam
bater com o estado atual do repositório.*

---

## Rubrica de qualidade

| Critério | Nota | Justificativa |
|---|---|---|
| Clareza do objetivo | 5 | Uma tela, um resultado, critério de "pronto" que se verifica rodando, não lendo |
| Adequação ao alvo (Claude Code) | 5 | Caminhos reais do repo, convenção de nomenclatura existente, referência a arquivos que já existem |
| Autonomia / execução sem intervenção | 5 | Só dois gatilhos de parada, ambos legítimos (conflito de dependência, mudança fora do escopo) |
| Verificabilidade (critério de aceite + evidência) | 5 | Cinco itens checáveis por execução real, não por leitura de código |
| Calibração (tom, sem CoT nem verificação redundante) | 5 | Nenhuma instrução de "confira sua resposta"; enquadramento positivo em toda restrição |
| Estrutura e ausência de redundância | 4 | XML-lite ajuda um prompt deste tamanho; um pouco de contexto arquitetural podia ir só em CLAUDE.md, mas o agente não tem garantia de já tê-lo carregado quando o prompt chega solto |
| Robustez (guardrails, bloqueio externo, continuidade) | 5 | O risco real do projeto (swagger-ui-react vs core) é nomeado, não deixado para o agente descobrir sozinho no primeiro erro de instalação |
| Atualidade (parâmetros e modelos correntes) | 5 | Nenhum parâmetro obsoleto; recomendação de modelo abaixo usa os IDs correntes |

---

## Antes / depois

| Mudança | Efeito esperado |
|---|---|
| "swagger de todas as APIs" → duas famílias de rota nomeadas com o cabeçalho exato de cada uma | Elimina o primeiro 401 que pararia a implementação na hora do "Try it out" |
| Nenhuma menção a dependência → `swagger-ui` core especificado, com o motivo de evitar o wrapper React | Evita que o agente escolha `swagger-ui-react`, veja o conflito de peer-dependency com React 19 e gaste um ciclo inteiro debugando instalação |
| "página" vago → 14ª entrada em `TELAS`, arquivo em `web/src/telas/`, primitivos de `ui.tsx` nomeados | Sai consistente com as outras 13 telas em vez de um componente-ilha com CSS próprio |
| Sem critério de pronto → 5 itens verificáveis por execução | Impede "implementei" sem ter clicado em Try it out nenhuma vez |
| Sem menção ao `/docs` público existente → constraint explícita de não tocar nele | Evita a leitura errada de "trocar o Swagger público" quando o pedido é aditivo |

---

## Modelo recomendado

**Perfil**: codificação agêntica em repositório existente, com uma decisão
arquitetural não trivial embutida (qual pacote de Swagger usar e por quê) e
duas integrações de autenticação diferentes para acertar.

**Modelo**: `claude-opus-5` — este é exatamente o caso "arquitetura +
decisão irreversível pequena" que justifica Opus em vez de Sonnet: a escolha
errada de pacote (`swagger-ui-react`) só aparece como sintoma no `npm
install`, e um modelo mais fraco tende a forçar a instalação com
`--legacy-peer-deps` em vez de reconhecer o sinal e trocar de pacote.

**Effort**: `xhigh` — é trabalho agêntico multi-arquivo (novo componente,
registro em `App.tsx`, possível ajuste de `package.json`) com um passo de
verificação real (rodar build, rodar teste, testar as duas famílias de rota
manualmente). Se, na prática, a integração se mostrar mais simples do que o
esperado, `high` também cobre — mas comece em `xhigh` e deixe o modelo gastar
menos se não precisar, não o contrário.
