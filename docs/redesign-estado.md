# Estado do redesenho

Leia este arquivo antes de qualquer outra coisa. Reescreva-o ao fim de cada
etapa concluída.

**Atualizado:** 05/08/2026, madrugada — fim da etapa 3 da fase 3.

## Pronto

- **Prompt corrigido** (`b3726c3`) — as cinco mudanças da proposta.
- **Fase 1 — auditoria** (`docs/auditoria-apresentacao.md`, `bfc6e17`). Onze
  achados localizados, cinco frentes, acessibilidade medida.
- **Fase 2 — direção e ADR-19** (`docs/direcao-apresentacao.md`, `f6047ba`).
  Quatro conjuntos de token, seis objetos gráficos especificados, passkey
  decidido como aditivo.
- **Fase 3, etapa 1** (`b3b8356`) — acento vivo, `temas.css` com as quatro
  direções, `a11y` cobrindo as duas superfícies.
- **Fase 3, etapa 2** (`c583ae7`) — erro de API humanizado na apresentação,
  com guarda contra o laço de redirecionamento.
- **Fase 3, etapa 3** — a tela de `negociacao_b3`. Grid virtualizado,
  cadeia de opções com implícita e gregas, proveniência alcançável por clique.

## Em voo

Nada.

## Decidido, e por quê

- **Sem deploy em produção durante a execução noturna.** Tudo commitado no
  branch e verificado localmente. O Alex sobe depois de olhar.
- **Sem `vitest`.** O front não tem runner de teste e instalar um é
  dependência nova — decisão do Alex. A evidência das etapas 2 e 3 é captura de
  tela mais rede, não teste unitário. É a lacuna conhecida desta entrega.
- **O grid nasceu virtualizado**, como a auditoria exigiu: janela calculada do
  scroll, espaçador de altura total, só o visível no DOM.
- **A cadeia abre no primeiro vencimento com prazo real**, não no primeiro da
  lista. O vencimento do próprio pregão tem prazo zero e toda implícita sai
  nula — a tela abria com 43 contratos e nenhuma volatilidade, o que parece
  defeito e é aritmética.

## Próxima ação

Etapa 5 da ordem em `docs/direcao-apresentacao.md`: `SaudeClasse`, `Linhagem`,
`LinhaDoTempo` e `Serie` como objetos reutilizáveis, fechando os achados 2.1,
2.2 e 3.2 da auditoria. Depois a etapa 6, a camada de acesso aditiva.

Antes disso, duas decisões do Alex: instalar ou não um runner de teste no
front, e qual das quatro direções visuais fica.
