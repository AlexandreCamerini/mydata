# Portal de Dados — spec de execução

Construa um portal de API de dados de mercado para empresas listadas na B3, com
plano de controle próprio: toda a recepção, o tratamento e a carga dos dados são
configurados por interface, não por código. O consumidor inicial é o BOLSIA, que
faz análise fundamentalista.

A CVM é a primeira fonte do portal e entra como configuração declarativa em
`app/seed_fontes.py`. O ciclo de ingestão é executado pelo motor em
`app/motor/`; não reescreva o parsing da CVM em um pipeline específico.

Stack, hospedagem, regra de custo, camadas do dado e convenções estão em
[CLAUDE.md](CLAUDE.md) — já carregado nesta sessão. Este documento é só o que
construir e como saber que ficou pronto. Se uma decisão do CLAUDE.md estiver
errada, diga em uma frase e siga; não pare o trabalho.

Primeira fonte a cadastrar: CVM Dados Abertos — `cad_cia_aberta.csv` (cadastro
das listadas) e os ZIPs DFP/ITR (demonstrações).

## Fases

Entregue em ordem. Cada fase tem um critério de aceite executável: rode o
comando e cole a saída real no relatório final.

### Fase 1 — Modelo de configuração e persistência

Tabelas do plano de controle: `cfg_fonte`, `cfg_dataset`, `cfg_coluna`,
`cfg_campo_calculado`, `cfg_regra_qualidade`, `cfg_agendamento`,
`cfg_chave_api`, `log_execucao`. Toda configuração é versionada (append-only,
com `versao` e `vigente`), porque uma reingestão precisa saber sob qual
configuração o dado antigo foi carregado.

Migrações idempotentes, aplicáveis nos dois sinks.

**Aceite:** `pytest -q tests/test_config_model.py` passa, e aplicar a migração
duas vezes seguidas na mesma base não gera erro nem duplicata.

### Fase 2 — Motor de ingestão dirigido por configuração

Um executor que lê `cfg_fonte` + `cfg_dataset` e roda o ciclo
baixar → gravar bronze → parsear → carregar silver → recomputar calculados →
avaliar regras de qualidade → publicar gold. A CVM entra como uma instância de
configuração, não como código especial.

O bronze é a tabela `bronze_captura` — DDL, trigger de imutabilidade e política
de retenção em [docs/arquitetura.md § 5.1](docs/arquitetura.md#51-bronze_captura).
O `UNIQUE (dataset_id, sha256)` faz recaptura de conteúdo idêntico ser no-op, e
o trigger de `UPDATE`/`DELETE` é parte do entregável, não opcional.

Carga idempotente pela chave natural declarada em `cfg_dataset`. Reexecutar a
mesma janela não duplica linhas.

Regras de qualidade são um gate: severidade `bloqueia` impede a publicação em
gold e deixa a versão anterior no ar. Implemente a reconciliação
Ativo = Passivo + PL (a regra está declarada em `app/seed_fontes.py`) como
primeira regra cadastrada.

Exponha `recomputar(janela)`: dropa silver, calculados e gold e reconstrói tudo
a partir do bronze já capturado, sem rede. É a rotina de correção padrão e
precisa ser barata de rodar.

**Aceite:** com as fixtures em `tests/`, `pytest -q` passa inteiro, incluindo
(a) um teste que roda a mesma janela duas vezes e confere que a contagem de
linhas em silver não muda, e (b) um teste que recomputa do bronze e chega ao
mesmo resultado da carga original.

### Fase 3 — API pública

```
GET /v1/empresas?q=&setor=&page=
GET /v1/empresas/{cd_cvm}
GET /v1/empresas/{cd_cvm}/demonstracoes?tipo=DFP|ITR&grupo=&de=&ate=&consolidado=
GET /v1/empresas/{cd_cvm}/metricas?nomes=
GET /v1/meta/datasets
GET /v1/meta/campos-calculados
GET /health
```

Toda resposta de dado carrega proveniência: `fonte`, `dt_captura`,
`versao_documento`, `calculado_em`. Paginação por cursor. `429` com
`Retry-After` quando a quota da chave estourar. OpenAPI gerado pelo FastAPI.

**Aceite:** subir a API contra a base de fixtures e mostrar a saída real de
`curl -s localhost:8000/v1/empresas/9512/demonstracoes?tipo=DFP | head -40`
com os campos de proveniência presentes.

### Fase 4 — Telas de configuração

| Tela | O que configura | Aceite |
|---|---|---|
| Fontes | URL template, encoding, separador, cadência, credencial | criar uma fonte pela UI e vê-la em `GET /v1/meta/datasets` |
| Datasets | arquivo→tabela, colunas, tipos, chave natural, política de versão | editar o mapeamento CVM sem tocar em código |
| Campos calculados | expressão, colunas de origem, preview sobre amostra real | salvar um campo com coluna inexistente é rejeitado com mensagem que nomeia a coluna |
| Qualidade | regra, severidade, gate de publicação | marcar uma regra como bloqueante e ver uma execução ser barrada |
| Execuções | histórico, logs, delta de volume, replay de janela | disparar replay de um ano e acompanhar o status mudar |
| Chaves de API | emissão, quota, revogação | revogar uma chave e receber `401` na chamada seguinte |
| Catálogo | schema, dicionário de dados, amostra (leitura) | navegar de uma tabela até uma amostra de 10 linhas |

Padrões de UX que valem como aceite, não como intenção: navegação por teclado
em todos os formulários, foco visível, rótulo associado a cada campo, erro
descrito em texto ao lado do campo que o causou, estado de carregamento e
estado vazio em cada listagem, ação destrutiva com confirmação que nomeia o
objeto. Contraste mínimo AA.

**Aceite:** `npm run build` conclui sem erro, e `npx @axe-core/cli
http://localhost:8000/admin` reporta zero violações críticas ou sérias.

### Fase 5 — Prontidão para o Railway

O código sai deste repositório pronto para subir, mas quem executa o deploy é o
Alex, na conta dele.

- Um único serviço web: FastAPI serve a API e o build estático do front.
- Bind em `0.0.0.0:$PORT`. Nada de porta fixa.
- Conexão pela `DATABASE_URL` que o Railway injeta; DuckDB só quando ela estiver
  ausente (desenvolvimento local).
- **Filesystem do container é efêmero.** Nenhum serviço pode depender de estado
  em disco. O bronze já mora em tabela (`bronze_captura`, decidido em
  [ADR-10](docs/arquitetura.md#adr-10--bronze-em-tabela-não-em-volume)), então
  não há volume a configurar — confira que nada escreve em disco local para
  persistir.
- `GET /health` como healthcheck, respondendo sem tocar no banco.
- Ingestão como cron do Railway apontando para um comando da CLI, não como
  thread dentro da API.
- `railway.json` e `.env.example` versionados, com toda variável documentada.

**Aceite:** `docker build` (ou o build nativo do Railway rodando local) conclui,
o serviço sobe com `PORT=8080 DATABASE_URL=... uvicorn ...`, e `curl
localhost:8080/health` retorna 200. Cole a saída.

## Trabalho bloqueado

O download da CVM depende de rede externa. Se o domínio não responder, siga com
as fixtures locais, entregue tudo que não depende de rede e diga no relatório
final exatamente qual passo ficou pendente e qual comando o desbloqueia. O mesmo
vale para PyPI e npm indisponíveis.

Este diretório ainda não é um repositório git. Rode `git init` e faça um commit
por fase concluída, para que cada fase seja revisável isoladamente.

## Como executar

Uma fase por vez, na ordem. No começo de cada fase, apresente o plano dela e
espere o aval; depois execute a fase inteira sem pedir confirmação a cada passo
— as permissões já estão em `.claude/settings.json`. Ao final da fase: rode o
aceite, faça o commit, e só então passe para a próxima.

Rastreie os passos da fase corrente na lista de tarefas, não em prosa. As
armadilhas do dado da CVM estão na skill `dados-cvm`, que carrega sozinha —
não repita esse conteúdo aqui.

## Como trabalhar

Entregue no escopo acima. Decida sozinho o que for rotina — nome de variável,
formato de log, escolha entre duas bibliotecas equivalentes. Se discordar de
algo, diga em uma frase e siga.

Delegue a subagentes só quando o trabalho for grande e genuinamente
independente — varredura ampla de arquivos, fases sem dependência entre si.
Verificação e revisão ficam no loop principal. No máximo 3 subagentes em
paralelo.

No relatório final, comece pelo resultado: o que ficou pronto e o que não
ficou. Cole a saída real dos comandos de aceite — não afirme que um teste passa
sem mostrar o `pytest` que passou. Documentos e comentários no tamanho que a
substância exige, sem seção de preenchimento.

## Fora de escopo

Cotação intradiária e dados de pregão. Fontes de terceiros (brapi, dadosdemercado)
como fonte de verdade — cabem depois, como atalho validado contra a CVM. Camada
dbt. Faturamento. Executar o deploy e mexer na conta do Railway: a configuração
entra no repositório, o `railway up` é do Alex.
