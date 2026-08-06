# Documentar a API pelo código, não por um material à parte

## Diagnóstico do pedido original

> "precisamos de uma material que explique cada uma das API. Com a explicacao
> funcional e dos parametros. Na Aba Api tem que ser auto-explicativo"

- **Objetivo real**: cada rota exposta explicada em linguagem funcional (o que
  faz, para quê), e cada parâmetro documentado — de um jeito que a Aba API
  fique auto-suficiente, sem o operador ter de ir perguntar ou ler o código.
- **Ambiguidade resolvida, não perguntada**: "um material" sugere um documento
  à parte (markdown, PDF). Mas a Aba API (`web/src/telas/Api.tsx`) já lê o
  `/openapi.json` ao vivo e já renderiza `description` de rota e de parâmetro
  quando eles existem — é o comentário que abre o próprio arquivo: *"documentação
  e teste vêm da mesma fonte, então nunca desalinham"*. Um markdown separado
  recriaria exatamente o problema que essa arquitetura evita: duas fontes que
  podem divergir. A leitura correta do pedido é a segunda frase — **"auto-
  explicativo"** é o critério, e o caminho é escrever a explicação onde o
  FastAPI já vai pegar e publicar sozinho: docstring de função e
  `description=` de parâmetro.
- **Furo de autonomia**: sem um padrão de qualidade explícito, um agente tende
  a preencher docstring com paráfrase da assinatura ("Retorna a lista de
  empresas") — que não é explicação funcional, é ruído. O prompt abaixo dá o
  padrão certo com exemplo real do próprio código.
- **Escopo medido, não estimado**: contei via AST antes de escrever este
  prompt. `app/api/main.py` tem 30 rotas, 11 sem docstring (6 delas fora da
  Aba API porque são `include_in_schema=False` — login, logout, estáticos).
  `app/api/admin.py` tem 34 rotas, 22 sem docstring. Pelo menos 16 parâmetros
  `Query`/`Path` não têm `description=`. Isso vira critério de aceite
  verificável, não promessa.
- **Risco de domínio**: várias rotas tocam dado da CVM (DFP/ITR), que tem
  armadilhas conhecidas no projeto — ITR é acumulado no ano, não trimestre
  isolado; consolidado e individual não se somam. Uma explicação funcional
  *errada* é pior que nenhuma. O prompt aponta a skill `dados-cvm` e
  `docs/arquitetura.md` como fonte, para não inventar semântica plausível.

---

## O prompt otimizado (para colar numa sessão do Claude Code neste repositório)

```
<context>
MyData tem uma Aba API no admin (web/src/telas/Api.tsx) que lê o
/openapi.json ao vivo do backend FastAPI e renderiza cada rota com o
`description` do docstring da função, e cada parâmetro com o `description=`
declarado em Query()/Path(). Documentação e teste vêm da mesma fonte de
propósito — nunca existe uma cópia separada para desalinhar.

Hoje a maioria das rotas não tem docstring, e vários parâmetros não têm
description=. Quando ausentes, a Aba API cai de volta no `summary`
auto-gerado pelo FastAPI (tipo "Get Contrato", "Listar Empresas") — que é o
nome da função, não uma explicação. É essa lacuna que faz a aba não ser
auto-explicativa.

As duas famílias de rota moram em app/api/main.py (/v1/*, para consumidores
externos como o BolsIA) e app/api/admin.py (/admin/api/*, para o operador do
portal). Um exemplo do padrão de qualidade que já existe e deve ser replicado,
em app/api/main.py, rota /v1/empresas:

    q: str | None = Query(None, description="Busca por denominação, CNPJ ou ticker"),
    segmento: str | None = Query(
        None, description="Segmento de listagem na B3 (NM, N1, N2, MB...)"),
    listada_b3: bool | None = Query(
        None, description="Só companhias com registro de negociação na B3"),

Note o que esses três têm em comum: dizem o EFEITO no resultado, não o tipo
do campo (o tipo já aparece no schema, separado). Nenhum reformula o nome do
parâmetro.

Várias rotas tocam dado da CVM (DFP/ITR) ou da B3, que têm comportamento não
óbvio — a skill `dados-cvm` e docs/arquitetura.md documentam isso (ITR é
acumulado no ano, não trimestre isolado; consolidado e individual não se
somam; escala de moeda varia por registro). Consulte antes de descrever
qualquer rota que toque nesses dados, para a explicação ser funcionalmente
correta e não só plausível.
</context>

<task>
Escreva um docstring funcional em toda função de rota de app/api/main.py e
app/api/admin.py que ainda não tem um, e um description= em todo parâmetro
Query()/Path() que ainda não tem. Exclua rotas marcadas include_in_schema=False
— não aparecem na Aba API, não fazem parte deste pedido.
</task>

<constraints>
- Docstring explica o que a rota FAZ na prática e PARA QUEM ela existe — nunca
  parafraseia o nome da função ou a assinatura. Ruim: "Retorna a lista de
  empresas". Padrão esperado: uma frase que diga o efeito de negócio — quem
  usa isso e para decidir o quê.
- description= de parâmetro explica o EFEITO no resultado ou uma regra que não
  é óbvia só pelo nome (ex.: como um filtro combina com outro, o que um cursor
  de paginação espera, por que um limite tem teto). Não descreva o tipo — o
  schema já mostra.
- Onde o comportamento tem uma pegadinha real de domínio (CVM/B3), a descrição
  nomeia a pegadinha, com a skill dados-cvm e docs/arquitetura.md como fonte —
  não invente semântica plausível para o dado da CVM.
- Não mude assinatura, comportamento, nem adicione parâmetro novo. Não crie
  arquivo de documentação separado — o único lugar que este pedido escreve é
  docstring de função e description= de parâmetro nesses dois arquivos.
- Um commit por arquivo concluído (main.py, depois admin.py), como o resto do
  projeto já faz.
</constraints>

<acceptance_criteria>
Rode este script contra o /openapi.json do servidor local depois de terminar
cada arquivo — as duas listas têm de sair vazias:

    import json, urllib.request
    with urllib.request.urlopen("http://localhost:8420/openapi.json") as r:
        spec = json.load(r)
    sem_rota, sem_param = [], []
    for caminho, por_metodo in spec["paths"].items():
        for metodo, op in por_metodo.items():
            if metodo not in ("get", "post", "put", "patch", "delete"):
                continue
            if not op.get("description", "").strip():
                sem_rota.append(f"{metodo.upper()} {caminho}")
            for p in op.get("parameters", []):
                if p["in"] in ("query", "path") and not p.get("description", "").strip():
                    sem_param.append(f"{metodo.upper()} {caminho} :: {p['name']}")
    print("rotas sem descrição:", len(sem_rota), sem_rota)
    print("parâmetros sem descrição:", len(sem_param), sem_param)

Depois, suba o admin local (scripts/servidor.py subir), abra #/api, expanda
pelo menos 5 rotas de tags diferentes e confirme visualmente que o texto é
explicação de verdade — não a frase genérica de antes.
</acceptance_criteria>

Decida o texto de cada docstring e description sozinho — não pare para
perguntar frase por frase. Pare e pergunte só se encontrar uma rota cujo
comportamento você não conseguir confirmar lendo o código (motor/repositorio)
nem a skill dados-cvm — não escreva explicação funcional que você não
verificou.
```

*Este prompt é para uma ferramenta agêntica com acesso real ao sistema
(Claude Code). Confira que `app/api/main.py` e `app/api/admin.py` ainda são
os dois arquivos de rota antes de colar — o resto do projeto pode ter mudado
desde que este prompt foi gerado.*

---

## Rubrica de qualidade

| Critério | Nota | Justificativa |
|---|---|---|
| Clareza do objetivo | 5 | Uma ação (escrever descrição), dois arquivos, critério mensurável de pronto |
| Adequação ao alvo (Claude Code) | 5 | Caminhos reais, exemplo tirado do código atual, script de verificação executável |
| Autonomia / execução sem intervenção | 5 | Só um gatilho de parada — comportamento que não dá para confirmar lendo o código |
| Verificabilidade (critério de aceite + evidência) | 5 | Script conta contra o /openapi.json real; duas listas vazias é o "pronto", não opinião |
| Calibração (tom, sem CoT nem verificação redundante) | 5 | Nenhuma instrução de "confira sua resposta"; restrições em enquadramento positivo |
| Estrutura e ausência de redundância | 5 | XML-lite cabe bem neste tamanho; nada repetido entre context/constraints |
| Robustez (guardrails, bloqueio externo, continuidade) | 5 | Aponta a skill dados-cvm como fonte — evita o risco real de explicação plausível e errada sobre dado da CVM |
| Atualidade (parâmetros e modelos correntes) | 5 | Nenhum parâmetro obsoleto; recomendação de modelo usa IDs correntes |

---

## Antes / depois

| Mudança | Efeito esperado |
|---|---|
| "um material" → escrever nos dois arquivos de rota, não um doc separado | Elimina o risco de nascer uma segunda fonte que desalinha da primeira em semanas |
| "explicação funcional" vago → exemplo real do próprio código, com o padrão nomeado ("efeito, não tipo") | Evita 40+ docstrings do tipo "Retorna X", que tecnicamente cumprem a tarefa e não resolvem o pedido |
| Sem menção a risco de domínio → skill dados-cvm e docs/arquitetura.md citados como fonte obrigatória | Evita descrição plausível e errada sobre ITR acumulado, consolidado/individual, escala de moeda |
| Sem critério de pronto → script contra /openapi.json real, duas listas vazias | "Terminei" vira fato verificável em segundos, não a palavra do agente |
| Escopo indefinido → contagem exata (30+34 rotas, ~33 sem docstring, ~16 parâmetros sem description, com include_in_schema=False excluído) | O agente sabe quando parou de faltar coisa, sem re-varrer o repo do zero |

---

## Modelo recomendado

**Perfil**: volume de escrita técnica (~70 pontos de edição entre docstrings e
parâmetros) que exige correção de domínio, não só fluência — a CVM e a B3 têm
comportamento que engana quem não conhece as armadilhas do dado (a skill
`dados-cvm` documenta sete delas).

**Modelo**: `claude-opus-5` — o risco aqui não é a tarefa ser difícil de
executar, é ela ser fácil de executar **errado de um jeito que parece certo**:
uma frase fluente e plausível sobre "ITR" que ignora que é acumulado no ano
engana o próximo operador que ler a Aba API. Isso pesa mais que o volume.

**Effort**: `high` — é trabalho de leitura-e-escrita repetido, não uma
decisão arquitetural única; não precisa do `xhigh` reservado para refactor
ou design multi-arquivo. Se o agente hesitar em alguma rota específica de
domínio CVM/B3, isso é o gatilho de parada do próprio prompt, não motivo para
subir o effort geral.
