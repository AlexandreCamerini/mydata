# Camada de apresentação e administração — spec de execução

Dê ao MyData duas superfícies visuais sobre o que já existe: **apresentação**,
onde se vê o dado, e **administração**, onde se governa o pipeline.

O que já está construído está em [CLAUDE.md](CLAUDE.md) e
[docs/arquitetura.md](docs/arquitetura.md): classes de informação geradas de
configuração, multi-fonte com precedência por atributo, observabilidade de
ETL, 199 testes, no ar em `https://mydata.acamerini.app`. **Reaproveite tudo.**

## O que muda, em duas frases

A administração existe pela metade: cinco das oito telas são só leitura, então
a promessa do produto — *criar classe de informação pela interface, sem
deploy* — só é verdade por `curl`. A apresentação não existe: doze endpoints
em `/v1` e nenhuma tela que mostre um balanço.

## Decisões travadas

Se alguma estiver errada, diga em uma frase e siga; não pare o trabalho.

| Dimensão | Decisão |
|---|---|
| Superfícies | `/` apresentação, `/admin` administração. Mesmo serviço, mesmo build — a regra de um serviço no Railway continua valendo |
| Como a apresentação lê | **Só por `/v1`**, nunca do banco. Se uma tela precisa de algo que a API não dá, o buraco é da API e se fecha lá. É o que mantém o contrato honesto e prova a API a cada tela |
| Chave no navegador | O navegador nunca vê chave de API. Um repasse no próprio serviço, sob o token de admin, injeta a chave do lado do servidor. Chave em `localStorage` é chave pública |
| Proveniência | Todo número exibido diz de onde veio: fonte, captura, publicação, e por atributo onde há disputa. É o diferencial do produto; se a tela esconde, o produto vira mais um revendedor |
| Gráfico | SVG escrito à mão sobre as primitivas de `ui.tsx`. Série temporal de balanço tem dezenas de pontos, não milhares — uma biblioteca de gráfico custa mais em bytes do que entrega |
| Componentes | As primitivas em `web/src/ui.tsx` continuam sendo a base. Dependência nova precisa de aprovação, como qualquer decisão de infraestrutura |
| Acessibilidade | `axe-core` sem violação crítica ou séria segue sendo critério de aceite, incluindo telas novas e painéis que só existem depois de interação |

## Fases

Ordem obrigatória: a Fase 1 fecha uma promessa quebrada, e as demais se
apoiam nela. Cada fase tem aceite executável — rode e cole a saída real.

### Fase 1 — A administração passa a administrar

As cinco telas de leitura ganham escrita, usando os endpoints que já existem:
`POST /admin/api/classes`, `/fontes`, `/datasets`, `/metricas`.

Classe é o caso difícil e o mais importante: o formulário monta atributos com
tipo, obrigatoriedade, unidade e precedência, mostra o DDL que vai rodar antes
de salvar (`GET /admin/api/classes/{chave}/ddl`), e exibe divergências entre a
configuração e o banco.

**Aceite:** um teste de ponta a ponta cria uma classe nova **pela interface** —
não por HTTP à mão —, cadastra fonte e mapeamento, dispara a carga e lê o
resultado. Hoje `tests/test_gerador_ddl.py` prova isso por HTTP; o equivalente
pela tela é o que falta. `pytest -q` verde e `npm run build` concluindo.

### Fase 2 — A empresa

Busca por nome, CNPJ ou ticker. Ficha com o que a classe `empresa` sabe, e os
filtros que respondem ao escopo real do produto: `listada_b3`, `com_balanco`,
segmento de listagem.

A ficha mostra as fontes que alimentam aquela empresa e, onde elas discordam,
qual venceu e por quê — o dado que `proveniencia.por_atributo` já devolve.

**Aceite:** buscar "petrobras" chega à ficha; o filtro de B3 reduz o universo
de 5.499 para 564; a ficha da Petrobras mostra a razão social vindo do
cadastro da CVM e diz isso na tela.

### Fase 3 — As demonstrações

Balanço, resultado e fluxo de caixa por empresa, com série de anos. O ITR com
o trimestre isolado — que `gold_itr_trimestre` já calcula e ninguém vê.

Três armadilhas do dado precisam ficar visíveis, não corrigidas em silêncio:
consolidado versus individual como escolha do usuário; reapresentação
indicando qual versão está sendo mostrada; escala sempre em reais, com o valor
original disponível.

**Aceite:** a série de Ativo Total da Petrobras de 2020 a 2025 aparece com os
valores que a API devolve; alternar consolidado/individual muda os números;
uma empresa com reapresentação mostra qual versão está no ar.

### Fase 4 — O painel do operador

Uma tela que responde as três perguntas que a Etapa 5 já instrumentou: o que
está desatualizado (`/v1/meta/frescor`), o que quebrou (execuções com falha e
bloqueio), e de onde veio este número (`/v1/meta/linhagem`).

A linha do tempo por fase da execução já existe em `log_fase` e hoje só sai em
JSON.

**Aceite:** cole a tela com uma classe fora do SLA marcada e a linhagem de
`denom_social` mostrando as três fontes na ordem de precedência.

### Fase 5 — Acesso

A apresentação é do Alex, não pública. Ela vive sob o mesmo `PORTAL_ADMIN_TOKEN`
que já protege `/admin/api`, e o repasse para `/v1` injeta a chave no servidor.

**Aceite:** sem token, a apresentação responde 401; com token, a tela carrega e
nenhuma chave de API aparece no HTML, no JavaScript ou em `localStorage` —
verifique no navegador e cole o resultado.

## Trabalho que depende do Alex

Nada nesta spec exige o painel do Railway. Se algo aparecer, deixe versionado
no repositório e liste em uma linha no relatório final.

## Como executar

Uma fase por vez. No começo de cada uma, apresente o plano e espere o aval;
depois execute a fase inteira sem confirmar passo a passo — as permissões já
estão em `.claude/settings.json`. Ao final: rode o aceite, faça o commit, siga.

Verifique no navegador com as ferramentas de preview, não pedindo ao Alex que
olhe: a porta do projeto é a 8420, e `python scripts/servidor.py subir` respeita
quem já está no ar.

## Como trabalhar

Entregue no escopo acima. Decida sozinho o rotineiro. Se discordar de algo,
diga em uma frase e siga.

**A apresentação lê pela API.** Se uma tela ficaria mais simples lendo o banco
direto, o que ela revelou é uma falta na API — feche lá e a tela volta a ser
simples. Contornar pelo banco entrega a tela e esconde o buraco do contrato.

Delegue a subagentes só para trabalho grande e genuinamente independente. No
máximo 3 em paralelo. Verificação fica no loop principal.

No relatório final, comece pelo resultado: o que ficou pronto e o que não
ficou. Cole a saída real dos comandos de aceite e uma captura de cada tela
nova.

## Fora de escopo

Autenticação de usuário final e multi-usuário. Edição de dado — o portal
publica o que a fonte disse, e corrigir número é assunto da origem. Exportação
para planilha. Aplicativo móvel.
