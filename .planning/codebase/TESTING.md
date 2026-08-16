# Testing Patterns

**Analysis Date:** 2026-08-16
**Mapped commit:** `cce3c61`

## Test Framework

**Python:**
- pytest, configurado por `tool.pytest.ini_options` em `pyproject.toml` com `testpaths = ["tests"]`.
- `pytest -q` executa a suíte; `TestClient` do FastAPI cobre HTTP.

**Frontend:**
- Vitest via `npm test`/`npm run test` em `web/package.json`.
- TypeScript é compilado como parte de `npm run build` (`tsc -b && vite build`).
- `npm run a11y` usa `axe` contra o servidor local na porta 8420.

## Test File Organization

- Backend fica em árvore separada `tests/`, com 34 arquivos Python observados no checkout.
- Fixtures e dados sintéticos compartilhados ficam em `tests/conftest.py`; não há diretório de snapshots/fixtures separado.
- Frontend mantém testes ao lado da implementação lógica: `web/src/objetos.test.ts` e `web/src/apresentacao/regras.test.ts`.

```text
tests/
  conftest.py
  test_api*.py, test_acesso.py
  test_motor.py, test_*.py de parsing/DDL/agenda/recomputo
web/src/
  objetos.tsx
  objetos.test.ts
  apresentacao/{api.ts,Negociacao.tsx,regras.test.ts}
```

## Test Structure

- pytest usa funções `test_*`, fixtures e asserts diretos; docstrings descrevem a invariável/regressão protegida.
- Suites TypeScript usam `describe`/`it`/`expect`, normalmente agrupadas por função pura.
- Testes enfatizam casos de borda: reapresentação, escala, nulo vs zero, prazo zero, cursor, quota, divergência, publicação e dialetos.

## Fixtures and Test Data

- `tests/conftest.py` cria CSV latin-1 separado por `;` e ZIPs com nomes reais da CVM (`zip_dfp_2023`, `zip_itr_2024`, `zip_cvm`).
- Fixture `sink` prepara schema completo; por padrão é `SinkDuckDB(":memory:")`.
- `PORTAL_TESTE_POSTGRES` habilita testes contra Postgres e recria o schema `public` por teste.
- `cliente` monta a API sobre banco carregado e usa `baixador` para substituir rede por bytes controlados.

## Mocking

- Rede é isolada por funções injetadas (`baixar=baixador(...)`) em vez de chamar a fonte nos testes do motor.
- Banco não é mockado: o sink real DuckDB é usado; Postgres real é opção explícita.
- Pure functions do frontend não precisam de mock; fetch/API é exercitado principalmente por testes Python de integração e pelo console ao vivo.

## Coverage and Validation

- Não há configuração ou threshold de coverage encontrado.
- Não há CI encontrado; a validação manual recomendada é:

```bash
pytest -q
cd web && npm test
cd web && npm run build
cd web && npm run a11y
```

## Test Types

**Unit:**
- `tests/test_campo_numerico.py`, `test_nucleos.py`, `test_correlacao.py`, `test_cotahist.py`, `test_largura_fixa.py` e os testes TypeScript de `objetos`.

**Integration:**
- `tests/test_api.py`, `test_api_opcoes.py`, `test_acesso.py`, `test_multifonte.py`, `test_recomputo.py`, `test_migracao_incremental.py` e `test_deploy.py` exercitam módulos/banco/API juntos.

**Regression/contract:**
- `tests/test_escopo_da_escrita.py`, `test_gerador_ddl.py`, `test_observabilidade.py`, `test_portal_mestre.py`, `test_relatorio_carga.py` e `test_virada.py` fixam invariantes operacionais.

## Important Gaps

- Não há E2E automatizado de navegador; `axe` e console ao vivo são scripts externos.
- A suíte pode cobrir Postgres somente se `PORTAL_TESTE_POSTGRES` estiver configurado; execução padrão cobre DuckDB.
- Não há medição de coverage/benchmark automática, embora existam números de performance documentados em comentários de `app/sinks.py`.

---

*Testing analysis: 2026-08-16*
