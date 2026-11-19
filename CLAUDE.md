# MyData — hub de dados (repositório `cvm-financas`)

Sistema **independente** que fornece informação, por API ou integração direta,
ao BolsIA e a outros sistemas que precisarem. Existe para o Alex ter o dado
sem pagar integrador que apenas atravessa a informação e cobra caro — daí a
fonte ser sempre a origem oficial, nunca um revendedor.

Nasce integrado ao BolsIA, mas não é parte dele: BolsIA é um consumidor, o
primeiro de vários.

**Endereço:** `https://mydata.acamerini.app/` — subdomínio próprio, não o
ápice. O ápice `acamerini.app` pertence a outro sistema, e um domínio
customizado no Railway aponta para um serviço só. A URL pública vive apenas em
`PORTAL_URL_PUBLICA`; mudar de endereço é trocar a variável e o DNS.

**Independência de projeto:** cada sistema do Alex tem seu próprio repositório
e sua própria sessão de trabalho. Não edite outro repositório a partir daqui.
O que atravessa a fronteira vira item em
[docs/contrato-consumidor.md](docs/contrato-consumidor.md), para o Alex
negociar com o outro projeto.

Primeira fonte de dado: CVM Dados Abertos. Hoje também Banco Central (SGS) e
B3 — COTAHIST (pregão diário, com a cadeia de opções, volatilidade implícita
e gregas) e o cadastro consolidado de instrumentos, que traz o estilo de
exercício que o COTAHIST não publica. As duas sob a restrição de uso pessoal
do [ADR-18](docs/arquitetura.md#adr-18--cotahist-entra-sob-uso-pessoal-e-a-classe-é-negociação)
e do [ADR-20](docs/arquitetura.md#adr-20--o-cadastro-de-instrumentos-entra-como-classe-própria-e-não-substitui-o-cotahist).

- Arquitetura e definição do sistema: [docs/arquitetura.md](docs/arquitetura.md)
- O que depende do painel do Railway: [docs/deploy-railway.md](docs/deploy-railway.md)
- Brief das fases 1–5: [prompt-portal-dados-otimizado.md](prompt-portal-dados-otimizado.md)
- Brief do hub multi-fonte: [prompt-hub-multifonte-otimizado.md](prompt-hub-multifonte-otimizado.md)

## Stack (decidido — mudar só aqui)

| Dimensão | Decisão |
|---|---|
| Backend | Python 3.10+, FastAPI + uvicorn |
| Frontend | React + Vite + TypeScript + Tailwind, build estático servido pelo FastAPI (um serviço só) |
| Hospedagem | Railway: API, front e cron de ingestão no mesmo projeto |
| Banco | Postgres do Railway, dentro do que o plano já inclui. DuckDB em arquivo só para dev local e testes |
| Agendamento | Cron do Railway, não runner externo |
| Auth | Chave de API por consumidor, hash em repouso, quota e escopo por classe |

**Regra de custo:** nada além do que o plano do Railway já inclui. Serviço
gerenciado de terceiros, add-on ou tier pago precisa de aprovação antes de
entrar no código — vale para banco, fila, storage, observabilidade e qualquer
outra decisão de infraestrutura.

## Classe de informação é o conceito central

Uma **classe** é a coisa sobre a qual o portal guarda dado — Empresa,
Demonstração financeira, Cotação. Ela tem atributos, chave de identidade e é
alimentada por N mapeamentos (`cfg_dataset`), cada um lendo uma fonte.

A tabela física é **consequência** da classe, não código: `motor.ddl` gera
DDL a partir de `cfg_classe`/`cfg_atributo`, e `cfg_vista` guarda o corpo das
vistas de gold. Não existe `CREATE TABLE` de domínio em migração — se você
está prestes a escrever um, a classe é que devia declarar aquilo
([ADR-11](docs/arquitetura.md#adr-11--a-tabela-como-consequência-da-classe)).

**Engine único:** `app/motor/`, `app/api/` e `app/migracoes.py` não sabem o
que é CVM. Fonte nova é linha em `cfg_*`, nunca linha em `app/`.
`app/seed_fontes.py` é a única exceção, porque ele é dado.

Duas fontes na mesma classe **coexistem**: `origem_dataset` faz parte da
identidade física, e a linha publicada sai de uma vista que escolhe por
precedência declarada **por atributo**. Reordenar precedência é republicar,
não recarregar
([ADR-12](docs/arquitetura.md#adr-12--resolução-multi-fonte-é-derivação-não-sobrescrita)).

## O dado

Imutável é **o arquivo oficial que a fonte publicou** (bronze): gravado
intacto, com hash SHA-256, URL e timestamp de captura; nunca reescrito, nunca
apagado. É a única cópia que não dá para reconstruir — a URL da CVM é endereço
mutável, regerado a cada reapresentação, então rebaixar não reproduz a captura.

Bronze mora na tabela `bronze_captura` (`bytea`), não em volume nem em disco:
o filesystem do container é efêmero e o volume do Railway monta em um serviço
só. Imutabilidade é imposta por trigger, não por convenção
([ADR-10](docs/arquitetura.md#adr-10--bronze-em-tabela-não-em-volume)).

Tudo que o portal deriva — silver tipado, campos calculados, vistas de gold —
é descartável por construção. **Dropar e recomputar do bronze é a rotina
normal de correção**, não um último recurso. `python -m app.cli recomputar`
faz isso e compara a digital de gold antes e depois; código de saída 3
significa que o recomputo não reproduziu o estado, ou seja, alguma coisa
entrou no banco por fora do pipeline.

Campos calculados vivem em catálogo declarativo e declaram as colunas de
origem que usam. Um que não consiga declarar isso falha na validação, não na
carga.

Um hook `PreToolUse` bloqueia escrita em `bronze/` e DDL contra as tabelas de
captura. Ele não atrapalha nada em silver/gold — se você foi bloqueado, o alvo
era dado oficial.

## Comandos

```bash
pip install -e ".[dev]"                 # ambiente
python -m pytest -q                     # testes — `-m` importa; `app/` não
                                         # está em `src/`, e só o `-m` insere
                                         # a raiz do projeto no sys.path
python scripts/demo.py                  # base local com dado de exemplo
python -m app.cli migrar --seed         # migrações + configuração (idempotente)
python -m app.cli ingerir cvm_dfp 2023  # uma janela, com rede
python -m app.cli ingerir b3_cotahist 2026-07-31   # um pregão da B3
python -m app.cli ingerir b3_instrumentos_bvbg 2026-11-19  # cadastro do dia (BVBG.028, ADR-26)
python -m app.cli recomputar            # refaz tudo do bronze e verifica
python -m app.cli verificar             # digital de gold, sem mexer em nada
python -m app.cli chave app --classe empresa   # chave com escopo
python scripts/servidor.py subir        # API local (ver "Porta local")
npm run build                           # front (em web/)
```

## Porta local

Esta máquina tem muitos serviços em escuta (3000, 5000, 5173, 8000, 8002,
8123, 8765, 8787…). **A porta deste projeto é a 8420**, declarada em
`scripts/servidor.py` e em `.claude/launch.json` — um teste falha se as duas
divergirem.

```bash
python scripts/servidor.py status           # quem está na porta, e de quem é
python scripts/servidor.py subir            # respeita quem já está no ar
python scripts/servidor.py parar --orfaos   # derruba os nossos, em qualquer porta
```

Duas regras, que existem por erro já cometido aqui:

- **Nunca matar processo que não é nosso.** Dono é o diretório de trabalho do
  processo, não a porta. `parar` recusa tocar em PID de outro repositório.
- **Nunca cair em outra porta em silêncio.** Porta tomada por terceiro é erro
  com nome e PID; servidor em porta que ninguém sabe qual é já desorientou uma
  vez, e um órfão deste repo foi encontrado servindo código velho na 8123.

Não suba servidor com `uvicorn` direto pelo Bash: ele escapa dessa checagem e
sobrevive à sessão.

## Armadilhas da CVM

A skill `dados-cvm` carrega as sete armadilhas do dado (reapresentação,
`ORDEM_EXERC`, escala, con/ind, ITR acumulado, contas custom, encoding) e a
regra de consulta. Elas já estão declaradas em `app/seed_fontes.py` — procure
os comentários `# Armadilha N`. Não reescreva a lógica em Python: a
configuração declarativa é a fonte de verdade.

Resumo operacional: nenhuma agregação sem filtrar `is_latest`,
`ordem_exerc = 'ÚLTIMO'` e um único valor de `consolidado`.

## Convenções

- Domínio contábil em português (`fato_conta`, `vl_conta_norm`); infraestrutura
  em inglês.
- Carga idempotente pela identidade da classe mais `origem_dataset`.
- Toda resposta de dado carrega proveniência: `fonte`, `dt_captura`,
  `versao_documento`, `publicacao` — e `por_atributo` quando a classe tem mais
  de uma fonte disputando o mesmo campo.
- Um commit por etapa concluída.
