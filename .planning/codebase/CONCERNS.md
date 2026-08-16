# Codebase Concerns

**Analysis Date:** 2026-08-16
**Mapped commit:** `cce3c61`

## Tech Debt

**Dois pipelines CVM coexistem:**
- Issue: `src/cvm_financas/` usa pandas e schema próprio, enquanto `app/` usa motor declarativo sem pandas.
- Impact: correções de parsing/contrato podem ser aplicadas a um caminho e esquecidas no outro; o próprio `tests/conftest.py` testa ambos.
- Safe approach: decidir e documentar qual caminho é público para cada consumidor antes de alterar semântica; manter testes de compatibilidade até retirar o legado.

**Seed extenso como fonte de configuração:**
- Issue: `app/seed_fontes.py` concentra muitas definições de fontes, classes, views, calculados e agendamentos.
- Impact: revisão e evolução são difíceis; um erro no seed pode mudar versões/DDL/gold no boot.
- Safe approach: mudanças devem ser idempotentes, cobertas por testes de seed/DDL e verificadas com `migrar --seed` antes do deploy.

**Ausência de gates automatizados no repositório:**
- Issue: não foram encontrados workflows CI, formatter/linter ou threshold de coverage.
- Impact: regressões dependem de execução manual e revisão.
- Fix approach: adicionar pipeline somente após alinhar custo/ambiente; incluir pelo menos pytest, build frontend e validação do pacote.

## Known Risks / Bugs

**Bronze cresce continuamente:**
- Evidence: risco registrado em `app/motor/custo.py`, `app/migracoes.py` e `docs/arquitetura.md`.
- Impact: armazenamento Postgres pode superar o plano Railway, especialmente no cadastro diário de instrumentos.
- Mitigation: medir custo/volume em `app/motor/observabilidade.py`; não trocar bronze por filesystem sem rever a decisão de imutabilidade/backup.

**CVM não é fonte estável de layout:**
- Risk: mudança de encoding, colunas, nomes de arquivo, escala ou valores de `ORDEM_EXERC` pode produzir carga incompleta/errada.
- Current mitigation: colunas obrigatórias, regex, regras declarativas em `app/seed_fontes.py` e fixtures sintéticas.
- Safe change: adicionar fixture do novo layout e regra bloqueadora antes de liberar ingestão.

## Security Considerations

**Segredos e superfícies de desenvolvimento:**
- Risk: `PORTAL_API_ABERTA=1` libera `/v1`; ausência de `PORTAL_ADMIN_TOKEN` deixa admin aberto em dev.
- Current mitigation: variáveis são documentadas como desenvolvimento; produção depende de configuração Railway.
- Recommendation: health/deploy checks devem confirmar que flags abertas não estão ativas em produção, sem imprimir tokens.

**Passkey e recuperação de acesso:**
- Risk: perda do único autenticador pode bloquear o administrador; `PORTAL_ACESSO_LEGADO=1` reabre token como saída de emergência.
- Current mitigation: sessões no servidor, desafios de uso único, origem/RP ID e possibilidade de registrar segundo autenticador em `app/api/acesso.py`.
- Safe change: testar sempre registro, login, revogação, expiração e recuperação em `tests/test_acesso.py`; não persistir credencial em frontend/localStorage.

**COTAHIST/cadastro B3:**
- Risk: dados B3 têm restrição de redistribuição documentada.
- Current mitigation: classes e contrato identificam uso pessoal e escopo por chave; `docs/fontes-terceiros.md` registra a decisão.
- Recommendation: não expor essas vistas como classe pública nem tratar agregador brapi como origem oficial sem nova decisão.

## Performance Bottlenecks

**Carga:**
- `app/sinks.py` documenta que upsert linha a linha era cerca de 300 linhas/s e staging/COPY chega a aproximadamente 9.300 linhas/s.
- O staging temporário é ponto crítico: manter a chave natural, `_ord` e descarte da tabela ao alterar carga em lote.

**Cálculos de negociação:**
- `app/motor/nucleos.py` inclui Black-Scholes/solução iterativa; `app/seed_fontes.py` usa calculados e joins contra histórico.
- `web/src/apresentacao/Negociacao.tsx` usa janela virtualizada para cadeias grandes; mudanças devem preservar a regra de não renderizar todos os contratos no DOM.

## Fragile Areas

**DDL metadata-driven:**
- Why fragile: tabela física, atributos, vistas e publicação precisam permanecer alinhados.
- Common failures: coluna órfã, atributo novo ausente, schema sem gold ou divergência de dialeto.
- Safe modification: usar prévia/divergências em `app/motor/ddl.py`/`app/api/admin.py`, testar `tests/test_gerador_ddl.py` e evitar DROP destrutivo.

**Multi-fonte e precedência:**
- Why fragile: identidade inclui `origem_dataset`, mas gold resolve por atributo; alterar precedência muda publicação sem nova captura.
- Safe modification: preservar `por_atributo`, testes em `tests/test_multifonte.py` e possibilidade de reverter publicação.

**Porta/processos locais:**
- Why fragile: vários serviços ocupam portas na máquina.
- Safe modification: usar `scripts/servidor.py`, porta 8420 e nunca matar processo apenas pelo número da porta.

**API grande em módulos centrais:**
- `app/api/main.py` tem aproximadamente 1.414 linhas e `app/api/admin.py` aproximadamente 933.
- Impact: alterações em auth, erro, static serving ou contratos podem afetar muitas superfícies; exige teste de integração direcionado.

## Scaling Limits

- Bronze binário em Postgres é simples e auditável, mas limita armazenamento e custo conforme capturas diárias acumulam.
- Um único serviço Railway hospeda API, frontend e cron; ingestão pesada pode competir por CPU/memória com requisições se o isolamento operacional não for respeitado.
- `dim_instrumento` é documentada como potencialmente grande (dezenas/centenas de milhares de instrumentos por fotografia); reter cada dia exige acompanhamento de volume.

## Test Coverage Gaps

- Não há E2E de navegador automatizado para login/passkey, redirecionamentos, apresentação pública e console admin.
- Build TypeScript não prova funcionamento de rede/rotas; a própria documentação de regressões em `web/src/apresentacao/regras.test.ts` mostra que alguns defeitos só apareceram olhando tela e aba de rede.
- Postgres real, triggers e diferenças de numeric/placeholder só são cobertos quando `PORTAL_TESTE_POSTGRES` está disponível.
- Não há teste de deploy publicado/Railway neste checkout; `tests/test_deploy.py` cobre consistência de configuração local, não disponibilidade externa.

## Missing Critical Features / Open Decisions

- Reconciliação contábil é regra de qualidade, mas divergência originada na fonte ainda requer decisão do operador; não é correção automática.
- O pacote legado documenta que `dim_empresa`/cadastro separado não fazia parte do loop original; o portal atual possui dataset dedicado, portanto mudanças devem evitar assumir que os dois pipelines têm o mesmo escopo.
- Não há estratégia de retenção/backup documentada para bronze em crescimento; esta é a principal decisão operacional antes de aumentar a frequência de cargas.

---

*Concerns audit: 2026-08-16*
