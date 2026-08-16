# Coding Conventions

**Analysis Date:** 2026-08-16
**Mapped commit:** `cce3c61`

## Naming Patterns

**Files:**
- Python modules em snake_case; componentes TSX em PascalCase; testes Python `test_*.py` e frontend `*.test.ts`.
- Vocabulário de domínio é português; nomes de infraestrutura e dependências seguem o idioma da biblioteca.

**Functions/variables:**
- Python snake_case (`criar_sink`, `exigir_chave`); TypeScript camelCase (`humanizar`, `deveRedirecionar`).
- Constantes em maiúsculas (`PORTA_PADRAO`, `STAGING`, `URL_PUBLICA`).

**Types:**
- Dataclasses Python para entidades/configuração (`app/repositorio.py`); `Protocol` para `Sink`.
- Pydantic `BaseModel` para payloads de API admin; type aliases/interfaces TypeScript para contratos HTTP.

## Code Style

- Python usa `from __future__ import annotations`, type hints modernos e docstrings/comentários extensos explicando invariantes.
- Frontend usa 2 espaços, semicolons e strings com aspas duplas no TypeScript existente.
- Não foi encontrado formatter/linter configurado no checkout; não presumir Prettier, Ruff ou mypy como gate.

## Import Organization

- Python separa stdlib, bibliotecas externas e imports relativos do pacote.
- Módulos compartilham dependências por imports relativos (`..sinks`, `..repositorio`); `app/api/admin.py` evita importar `main.py` para não criar ciclo.
- TypeScript importa bibliotecas primeiro, depois módulos relativos; `import type` é usado para contratos.

## Error Handling

- Domínio lança exceções nomeadas (`ErroIngestao`, `ErroConfiguracao`, exceções do cliente brapi); fronteiras convertem em HTTP/exit code.
- FastAPI centraliza forma de erro em `tratar_http` (`app/api/main.py`).
- `except Exception` aparece em pontos deliberados de isolamento: agendamento, medição, parsing de regra, WebAuthn e limpeza; mudanças nesses blocos devem preservar logging e contexto.
- Valores ausentes são preservados como `None`/nulo. O frontend diferencia nulo de zero, conforme testes em `web/src/objetos.test.ts`.

## Logging

- Python usa `logging.getLogger` e mensagens com contexto de dataset/fase; CLI configura formato/nível em `app/cli.py`.
- Execuções persistem status, duração e fases em vez de depender apenas de log textual (`app/motor/observabilidade.py`).
- Frontend apresenta estados de carregamento, vazio e erro com primitives de `web/src/ui.tsx`.

## Comments and Documentation

- Comentários explicam principalmente o porquê de uma proteção, decisão de domínio ou defeito histórico, não apenas a operação sintática.
- ADRs e limites de produto ficam em `docs/arquitetura.md`, `docs/fontes-terceiros.md` e `docs/contrato-consumidor.md`; não duplicar contratos divergentes em código.
- `CLAUDE.md` é a instrução operacional do checkout e deve ser consultado antes de alterar portas, bronze, fonte ou deploy.

## Function and Module Design

- Código genérico pertence a `app/motor/`; conhecimento de fonte deve ser configuração em `app/seed_cvm.py`.
- Funções têm guard clauses para validação e retorno explícito; operações de banco recebem `Sink` por parâmetro para manter os dois dialetos testáveis.
- Frontend separa regras puras de apresentação para testá-las sem montar toda a árvore React.

## Domain Invariants to Preserve

- Captura bronze é imutável e identificada por hash/URL/instante.
- `origem_dataset` participa da identidade quando há múltiplas fontes; precedência é resolvida em gold por atributo.
- DDL nasce de `cfg_classe`/`cfg_atributo`; divergência aparece para decisão, não vira `DROP COLUMN` silencioso.
- Toda resposta de dado deve carregar proveniência suficiente (`fonte`, captura, versão/publicação e, quando necessário, `por_atributo`).

---

*Convention analysis: 2026-08-16*
