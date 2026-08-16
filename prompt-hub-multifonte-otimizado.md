# Hub multi-fonte — spec de execução

Evolua o portal de um ingestor da CVM para um **hub de informação multi-fonte**:
várias fontes alimentam as mesmas classes de informação, num banco só, que
abastece os apps do Alex para tomada de decisão. O operador cria, administra e
observa todo o ETL pela interface.

O que já existe (fases 1–5, 81 testes) está em [CLAUDE.md](CLAUDE.md) e
[docs/arquitetura.md](docs/arquitetura.md): plano de controle versionado, motor
dirigido por configuração, bronze imutável, gate de qualidade, publicação por
rótulo, API com proveniência, 7 telas, deploy Railway. **Reaproveite tudo.**

## O que muda, em uma frase

Hoje um dataset aponta para uma tabela física que existe no código
(`fato_conta`, `dim_empresa` estão na migração `0004`; as views de gold estão
no dicionário `VIEWS` do `publicacao.py`). Isso significa que **criar uma nova
classe de informação exige deploy** — o oposto do produto pedido. A mudança
central é tornar a classe de informação uma entidade de primeira classe do
plano de controle, com tabela e views geradas a partir da configuração.

## Decisões travadas

Se alguma estiver errada, diga em uma frase e siga; não pare o trabalho.

| Dimensão | Decisão |
|---|---|
| "Classe de dados e informações" | Classe **de domínio** (Empresa, Demonstração Financeira, Cotação, Indicador), não classe de código. Uma classe tem atributos, chave de identidade, e é alimentada por **N fontes** |
| Relação fonte↔classe | Muitos-para-muitos. Um dataset deixa de "ter uma tabela" e passa a **mapear atributos de uma classe** |
| Conflito entre fontes | Precedência declarada **por atributo**, não por fonte inteira. Toda linha registra qual fonte venceu cada atributo disputado |
| Tabelas físicas | Geradas por DDL a partir de `cfg_classe`/`cfg_atributo`, aplicadas por migração automática versionada. Sem `CREATE TABLE` escrito à mão para classe nova |
| Endpoint raiz | `https://mydata.acamerini.app/` serve o hub: `/v1` (API), `/admin` (plano de controle), `/health`. O ápice `acamerini.app` é do BolsIA; o MyData é sistema independente e tem endereço próprio |
| Hospedagem e custo | Railway, um serviço, nada além do que o plano já inclui — restrição mantida do projeto atual |
| Invariante do dado | Mantido integralmente: bronze imutável por fonte, derivado recomputável, gate antes de publicar |

## Fases

Ordem obrigatória: a Fase 1 destrava as demais. Cada fase tem aceite
executável — rode e cole a saída real no relatório.

### Fase 1 — Classe de informação no plano de controle

`cfg_classe` (chave, nome, descrição, chave_identidade, versionada como
agregado) e `cfg_atributo` (nome, tipo, obrigatório, unidade, descrição).
Um gerador transforma essa configuração em DDL e o aplica como migração
registrada em `schema_migracao` — mesma idempotência das existentes.

`cfg_dataset` passa a declarar `classe_chave` e o mapeamento
`coluna_origem → atributo`, em vez de `tabela_destino`.

Migre a CVM atual para o novo modelo, sem perder dado: `fato_conta` vira a
classe `demonstracao_financeira`, `dim_empresa` vira `empresa`.

**Aceite:** `pytest -q` passa inteiro (as 81 existentes continuam verdes), e um
teste cria uma classe nova pela API do plano de controle, ingere um CSV nela e
lê o resultado — sem nenhuma migração escrita à mão.

### Fase 2 — Resolução multi-fonte

Duas ou mais fontes alimentando a mesma classe. Para cada atributo disputado,
a configuração declara precedência (lista ordenada de fontes) e o que fazer
quando a de maior precedência está ausente ou vazia.

Cada linha publicada carrega, por atributo disputado, qual captura a originou.
Proveniência deixa de ser por linha e passa a ser **por atributo** onde houver
disputa.

**Aceite:** um teste com duas fontes divergentes para a mesma empresa mostra
que o valor publicado é o da fonte de maior precedência, e que a resposta da
API diz de qual captura veio cada atributo disputado.

### Fase 3 — Observabilidade de ETL

O operador precisa responder três perguntas sem abrir o banco: *o que está
desatualizado*, *o que quebrou*, *de onde veio este número*.

- **Frescor por classe**: última publicação bem-sucedida, idade, e SLA
  declarado em `cfg_classe`. Classe fora do SLA aparece marcada.
- **Linhagem**: dado um atributo, mostrar fonte → captura → dataset → regra que
  o aprovou → publicação.
- **Linha do tempo de execução**: fases do ciclo com duração, para achar onde
  a carga demora.

**Aceite:** `GET /v1/meta/frescor` lista cada classe com idade e situação de
SLA; `GET /v1/meta/linhagem?classe=&atributo=` devolve a cadeia completa. Cole
a saída real dos dois.

### Fase 4 — UX centrado em classe

Esta é a mudança de UX pedida. Hoje as telas são centradas em *dataset* — o
operador precisa saber que `cvm_dfp` existe para achar uma empresa. Passam a
ser centradas em **classe de informação**: o operador pensa em "Empresa", vê
quais fontes a alimentam, quais atributos estão em disputa e quando cada uma
atualizou.

| Tela | Passa a ser |
|---|---|
| **Classes** (nova, entrada principal) | catálogo de classes, atributos, fontes que alimentam, frescor |
| **Fontes** | mantida, agora mostrando quais classes cada fonte alimenta |
| **Datasets** | vira "Mapeamentos": ligação fonte → classe, com precedência por atributo |
| **Campos calculados** e **Qualidade** | mantidas, escopo por classe |
| **Execuções** | ganha a linha do tempo por fase e o painel de frescor |
| **Chaves de API** e **Catálogo** | mantidas |

Os padrões de acessibilidade seguem sendo critério de aceite: navegação por
teclado, foco visível, rótulo associado, erro ao lado do campo, estado de
carregamento e vazio, confirmação que nomeia o objeto, contraste AA.

**Aceite:** `npm run build` conclui, e a auditoria axe-core reporta zero
violações críticas ou sérias em todas as telas — incluindo as novas. Cole a
saída.

### Fase 5 — Domínio e contratos por app

`https://mydata.acamerini.app/` como raiz — não o ápice, que é do BolsIA.
Configure no Railway o domínio
customizado, e no app: `CORS` restrito aos subdomínios dos apps, `root_path`
correto para o OpenAPI apontar para o domínio público, e redirecionamento de
`http` para `https` a cargo da borda do Railway.

Cada app consumidor tem sua chave de API com escopo — o escopo diz **quais
classes** ele lê. Um app novo não implica código novo.

**Aceite:** `curl -sI https://mydata.acamerini.app/health` retorna 200 pelo domínio
público, e `GET /openapi.json` traz o servidor com a URL pública. Se o DNS
ainda não estiver propagado, entregue a configuração versionada e diga
exatamente qual passo depende do painel do Railway.

## Trabalho que depende do Alex

O domínio, o DNS e o deploy são da conta dele. Deixe a configuração no
repositório, valide tudo o que roda local, e no relatório final liste em uma
linha cada passo que precisa do painel do Railway.

## Como executar

Uma fase por vez. No começo de cada uma, apresente o plano e espere o aval;
depois execute a fase inteira sem confirmar passo a passo — as permissões já
estão em `.claude/settings.json`. Ao final: rode o aceite, faça o commit, siga.

Rastreie os passos da fase corrente na lista de tarefas. As armadilhas do dado
da CVM estão na skill `dados-cvm`, que carrega sozinha.

## Como trabalhar

Entregue no escopo acima. Decida sozinho o rotineiro. Se discordar de algo,
diga em uma frase e siga.

**Migração sem perda é requisito, não detalhe:** a base atual tem dado
publicado e capturas em bronze. Nenhuma fase pode exigir reingestão para
funcionar — o bronze existente tem de ser suficiente para reconstruir tudo no
modelo novo.

Delegue a subagentes só para trabalho grande e genuinamente independente. No
máximo 3 em paralelo. Verificação fica no loop principal.

No relatório final, comece pelo resultado: o que ficou pronto e o que não
ficou. Cole a saída real dos comandos de aceite.

## Fora de escopo

Cotação intradiária e dados de pregão como fonte nova nesta rodada — a
arquitetura tem de suportá-los, mas o cadastro fica para depois. Faturamento.
Autenticação de usuário final nos apps. Remoção do pipeline CVM legado já
substituído pelo motor declarativo.
