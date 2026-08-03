# Fundação de dados — o documento que rege, e a camada que o executa

Dois entregáveis, nesta ordem: **o documento de arquitetura que vira lei para
todos os projetos do Alex**, e a camada do MyData que o torna verdadeiro na
tela — configuração, validação, observabilidade, visualização e correlação.

O que já está construído está em [CLAUDE.md](CLAUDE.md) e
[docs/arquitetura.md](docs/arquitetura.md): classes de informação geradas de
configuração, bronze imutável com hash, multi-fonte por precedência declarada
por atributo, observabilidade de ETL, apresentação e painel do operador no ar
em `https://mydata.acamerini.app/`. Reaproveite tudo.

## O que muda, em três frases

O MyData tem os invariantes certos e nenhum documento que os imponha a
**outros** projetos — cada app novo pode decidir guardar sua própria cópia do
dado de mercado, e nada no repositório diz que isso é errado. A configuração
de fonte nova existe, funciona por tela desde a Fase 1 da apresentação, e
ainda exige que quem opera saiba o que é `padrao_arquivo` e chave natural. E
correlacionar duas classes — empresa com demonstração, demonstração com
cotação — não é possível por nenhuma superfície: nem tela, nem API.

## Vocabulário: o que o MyData é

**Hub de classes de informação, não data lake.** A distinção decide
arquitetura, não é preferência de nome. Data lake guarda arquivo cru e adia a
modelagem para a leitura; aqui a classe é declarada primeiro e a tabela é
consequência dela ([ADR-11](docs/arquitetura.md#adr-11--a-tabela-como-consequência-da-classe)).
O que o Alex descreve como necessidade — dado-verdade centralizado, originais
intactos — é o que o sistema já faz por construção; o que falta é impor isso
fora dele. Se um documento ou uma tela chamar o MyData de data lake, alguém
eventualmente vai jogar arquivo num bucket e chamar de ingestão.

## Decisões travadas

Se alguma estiver errada, diga em uma frase e siga; não pare o trabalho.

| Dimensão | Decisão |
|---|---|
| **Fronteira** | Dado-verdade do mercado é do MyData; dado próprio do app é do app. O documento vale pelo **teste que resolve os casos do meio**, não pela frase que resolve os extremos |
| **Porta única** | Consumidor lê por `/v1`. Nenhum app abre conexão com o Postgres do MyData, nem replica classe para banco próprio. Cópia local é cache com validade declarada, nunca fonte |
| **Canvas estilo Digibee** | É **projeção** do modelo declarativo — lê e escreve `cfg_*`. Um canvas que guarde topologia própria vira modelo paralelo que diverge de `cfg_classe`, e quebra [ADR-11](docs/arquitetura.md#adr-11--a-tabela-como-consequência-da-classe) e [ADR-12](docs/arquitetura.md#adr-12--resolução-multi-fonte-é-derivação-não-sobrescrita). Roube a UX; não roube o modelo |
| **Correlação** | Declarada como configuração, do mesmo jeito que classe e vista. SQL livre pela interface furaria o escopo por classe das chaves (ADR-14) e reabriria o que ADR-5 fechou |
| **Originais** | Já são invariante fechado ([ADR-10](docs/arquitetura.md#adr-10--bronze-em-tabela-não-em-volume)): `bytea`, SHA-256, trigger. A Fase 2 **mostra e prova** isso; não redecide |
| **Normalização** | O que hoje vive espalhado em `cfg_coluna`, calculados e regras passa a ter forma publicada: um contrato por classe, legível pelo consumidor em `/v1` |
| **Onde mora o documento** | `docs/fundacao-de-dados.md` neste repositório, com ponteiro em `~/.claude/CLAUDE.md`. O MyData é o hub, então a lei da fronteira mora nele; o ponteiro global é o que torna "obrigatório" mecânico em vez de aspiracional |
| **Pesquisa de mercado** | Serve para decidir questões nomeadas na Fase 0. A saída é decisão com fonte, não relatório |
| **Dependência nova** | Continua exigindo aprovação, como qualquer decisão de infraestrutura |

## Fases

Ordem obrigatória. A Fase 1 rege as decisões de todas as outras — construir
tela antes de escrever o documento é decidir arquitetura implicitamente e
documentar depois o que já foi feito. Cada fase tem aceite executável — rode e
cole a saída real.

### Fase 0 — Pesquisa que fecha decisão

Use o scraper para responder às perguntas abaixo, com fonte. Teto: até 6
questões, e pare quando cada uma tiver resposta suficiente para decidir.

1. **UX de mapeamento de campo** — como Digibee, Workato e Boomi apresentam
   "ligar origem a destino" e onde essa UX pressupõe modelo imperativo que não
   se aplica aqui.
2. **Contrato de dado** — como Open Data Contract Standard e o `contracts` do
   dbt versionam e publicam o contrato; o que cabe em `/v1/meta`.
3. **Linhagem** — vocabulário do OpenLineage contra o que
   `/v1/meta/linhagem` já devolve: adotar, traduzir na borda, ou ignorar com
   motivo.
4. **Fronteira de domínio** — como Data Mesh trata dado de domínio versus dado
   compartilhado, e o que disso resolve o caso do meio da nossa fronteira.
5. **Correlação declarada** — como ferramentas de semantic layer (Cube, dbt
   semantic layer) declaram junção entre entidades sem expor SQL ao usuário.

**Aceite:** `docs/pesquisa-mercado.md` com uma seção por questão, cada uma
terminando em **Decisão:** e a fonte que a sustenta. Uma questão que a
pesquisa não resolveu fecha com **Decisão: mantido como está, porque…**.

### Fase 1 — O documento que rege

`docs/fundacao-de-dados.md`. Escreva para quem começa um projeto novo daqui a
um ano e não participou de nenhuma dessas conversas.

Cobre:

- **A tese e a assimetria** — dado-verdade centralizado; app depende do
  MyData, nunca o contrário. Já está em
  [docs/contrato-consumidor.md](docs/contrato-consumidor.md) para o caso do
  BolsIA; aqui vira regra geral.
- **O teste de decisão.** É a parte que dá valor ao documento. "Preço da ação"
  e "carteira do usuário" são fáceis; o teste precisa resolver: indicador
  calculado a partir de dado-verdade, classificação proprietária que o app
  inventou, dado de mercado que só um app consome hoje, e cache local de
  classe do MyData. Escreva o teste como pergunta encadeada com resposta
  determinística, e passe os quatro casos por ele no próprio documento.
- **Como o consumidor lê e o que ele nunca faz** — a porta única, o escopo por
  classe, a proveniência que acompanha todo número.
- **O invariante do original** — por que bronze intacto é a base da confiança e
  o que se perde se um projeto guardar "o dado já tratado".
- **Como esta lei se aplica** — o mecanismo, não a intenção: ponteiro no
  `CLAUDE.md` global, e a regra de que decisão que contraria o documento vira
  ADR novo aqui antes de virar código lá.

**Aceite:** o documento existe, tem o teste de decisão com os quatro casos
resolvidos, e `~/.claude/CLAUDE.md` ganhou o ponteiro. Cole o teste de decisão
na resposta.

### Fase 2 — Validação e normalização, visíveis e provadas

Torne verificável, pela tela, a cadeia que hoje só existe no código: arquivo
oficial capturado → tipado → calculado → aprovado pelo gate → publicado.

- **Contrato por classe** em `/v1/meta` — colunas de origem, tipo, formato,
  regra que vigia, e o que a normalização faz com cada campo. É o que o
  consumidor lê para saber o que recebe.
- **A prova do original** na tela: hash, tamanho, URL e captura do arquivo
  oficial, com o valor original ao lado do normalizado — o par
  `vl_conta` / `vl_conta_norm` já existe e é o exemplo a generalizar.
- **As regras de qualidade em contexto**: quantas linhas cada regra reprovou na
  última carga, e o que ficou retido.

**Aceite:** para uma conta da Petrobras, a tela mostra a cadeia completa até o
SHA-256 do ZIP da CVM; `GET /v1/meta/contrato?classe=demonstracao_financeira`
devolve o contrato; e os quatro bloqueios reais de `reconciliacao_ativo_passivo`
aparecem com contagem de linhas. Cole a saída da API e uma captura da tela.

### Fase 3 — Conectar fonte nova sem saber o que é `padrao_arquivo`

A configuração existe e é correta; o que falta é ser simples. Construa o fluxo
guiado, com a UX da Digibee sobre o modelo declarativo que já temos:

- Passo a passo de fonte nova: **origem → amostra → mapear campos → classe →
  agendar → carregar**, com o arquivo real baixado na hora servindo de amostra.
- Mapeamento de campo lado a lado — coluna do arquivo à esquerda, atributo da
  classe à direita — em vez do formulário de `cfg_coluna` cru.
- Diagnóstico antes de gravar: o que a validação recusa dito em português, na
  linha do campo que causou.
- O canvas lê e escreve `cfg_*`. Nenhuma topologia paralela.

**Aceite:** um teste de ponta a ponta conecta uma fonte que hoje não existe no
sistema, **pelo fluxo guiado**, e chega a dado publicado. `pytest -q` verde,
`npm run build` concluindo, axe sem violação séria ou crítica.

### Fase 4 — Correlação entre classes

Declare junção entre classes como configuração, do mesmo modo que classe e
vista são declaradas hoje. O primeiro caso concreto: empresa × demonstração
financeira, que hoje o consumidor só junta do lado dele.

A correlação respeita o escopo da chave: quem lê só `empresa` não alcança
`demonstracao_financeira` por dentro de uma junção.

**Aceite:** uma correlação declarada pela tela devolve, por `/v1`, empresas com
o Ativo Total do último exercício; uma chave com escopo restrito recebe 403 na
mesma consulta. Cole as duas respostas.

### Fase 5 — Gestão consolidada

Uma tela de gestão que responda, sem abrir o banco: o que o hub tem, quanto
tem, quem consome, quanto custa em espaço, e o que está para vencer o SLA.
Reaproveite frescor, execuções e linhagem, que já existem.

**Aceite:** a tela mostra as classes com contagem de linhas real da base
(7,48 milhões em `gold_demonstracoes`, 5.499 em `gold_empresa`), as chaves
emitidas com consumo, e o espaço de `bronze_captura`. Cole a captura.

## Trabalho que depende do Alex

Nada nesta spec exige o painel do Railway. Se algo aparecer, deixe versionado
no repositório e liste em uma linha no relatório final.

## Como executar

Uma fase por vez. No começo de cada uma, apresente o plano e espere o aval;
depois execute a fase inteira sem confirmar passo a passo — as permissões já
estão em `.claude/settings.json`. Ao final: rode o aceite, faça o commit, siga.

Verifique no navegador com as ferramentas de preview, não pedindo ao Alex que
olhe: a porta do projeto é a 8420, e `python scripts/servidor.py subir`
respeita quem já está no ar. Verificação de tela roda sobre
`dados/mydata.duckdb`, que tem o dado real — base de demonstração produziria
tela bonita com número sintético.

## Como trabalhar

Entregue no escopo acima. Decida sozinho o rotineiro. Se discordar de algo,
diga em uma frase e siga.

A configuração declarativa é a fonte da verdade. Se uma tela ficaria mais
simples guardando estado próprio, o que ela revelou é uma falta no modelo de
configuração — feche lá e a tela volta a ser simples. Estado paralelo entrega
a tela e cria a divergência que ninguém vê até o recomputo discordar.

Delegue a subagentes só para trabalho grande e genuinamente independente. No
máximo 3 em paralelo. A Fase 1 é escrita, não paralelizável: faça-a no fio
principal.

No relatório final, comece pelo resultado: o que ficou pronto e o que não
ficou. Cole a saída real dos comandos de aceite e uma captura de cada tela
nova.

## Fora de escopo

Autenticação de usuário final e multi-tenant — a questão 2 do §14 continua
aberta e o documento da Fase 1 deve dizer que está. Edição de dado: o portal
publica o que a fonte disse, e corrigir número é assunto da origem.
Exportação para planilha. Aplicativo móvel. Fonte de dado nova de verdade
(cotação, por exemplo): a Fase 3 prova o fluxo, mas qual fonte entra é decisão
do Alex, não desta spec.
