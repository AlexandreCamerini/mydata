# Estado do redesenho

Leia este arquivo antes de qualquer outra coisa. Reescreva-o ao fim de cada
etapa concluída.

**Atualizado:** 05/08/2026, fim da fase 1.

## Pronto

- **Prompt corrigido** (`prompt-redesign-portal-otimizado.md`, commit `b3726c3`)
  — cinco mudanças: portão de arte não bloqueia, camada de acesso aditiva com
  `PORTAL_ACESSO_LEGADO`, este arquivo de estado, mínimo entregável por fase,
  `axe` como portão numérico nas duas superfícies.
- **Fase 1 — auditoria** (`docs/auditoria-apresentacao.md`). Cinco frentes
  cobertas, onze achados localizados e priorizados.

## Em voo

Nada. Fase 2 não começou.

## Decidido, e por quê

- **Sem deploy em produção durante a execução noturna.** O trabalho fica
  commitado no branch `claude/mydata-handoff-3b2cc1` e verificado localmente.
  Subir interface e autenticação sem o Alex poder olhar tem risco assimétrico
  e nenhum ganho — ninguém usa o portal de madrugada.
- **A construção começa pela classe `negociacao_b3`.** É o achado de maior
  valor da auditoria: 384.875 linhas, 329 mil contratos de opção com
  volatilidade implícita e gregas, e zero representação na interface.
- **O grid nasce virtualizado.** Nenhuma tabela atual é, e um pregão tem 15 mil
  linhas. Sem isso a tela nasce quebrada.

## Próxima ação

Fase 2: quatro conjuntos de token, ADR da camada de acesso em
`docs/arquitetura.md`, especificação dos objetos gráficos. O mínimo entregável
da fase é o ADR escrito e os quatro conjuntos definidos.
