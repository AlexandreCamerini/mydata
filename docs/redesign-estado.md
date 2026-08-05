# Estado do redesenho

Leia este arquivo antes de qualquer outra coisa. Reescreva-o ao fim de cada
etapa concluída.

**Atualizado:** 05/08/2026, manhã — fim da etapa 5 da fase 3.

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
- **Fase 3, etapa 3** (`270d42a`) — a tela de `negociacao_b3`. Grid
  virtualizado, cadeia de opções com implícita e gregas, proveniência
  alcançável por clique.
- **Runner de teste** (`7df22e4`) — `vitest`, e os dois defeitos da noite
  virados regressão.
- **Fase 3, etapa 5** — `SaudeClasse`, `Linhagem`, `LinhaDoTempo` e `Serie` em
  `web/src/objetos.tsx`, fechando os achados 2.1, 2.2, 3.2 e 2.4.

## Em voo

Nada.

## Decidido, e por quê

- **Sem deploy em produção durante a execução noturna.** Tudo commitado no
  branch e verificado localmente. O Alex sobe depois de olhar.
- **O grid nasceu virtualizado**, como a auditoria exigiu.
- **A cadeia abre no primeiro vencimento com prazo real**, não no primeiro da
  lista — sem prazo não existe implícita, e a tela parecia quebrada.
- **Objeto recebe dado por prop; quem busca é a tela.** Há dois módulos `api`
  neste front, um por bundle. Um objeto que buscasse sozinho teria de escolher
  um deles e deixaria de ser reutilizável na fronteira que existe para
  atravessar.
- **Linhagem e correlações ganharam espelho em `/admin/api`.** As rotas de
  `/v1` respondem o mesmo; o que muda é quem pode chamar. Tentei antes
  presumir sessão de dono quando `PORTAL_ADMIN_TOKEN` não existe, e o teste
  `test_sem_chave_recusa_com_codigo_estavel` mostrou que aquilo abriria `/v1`
  em qualquer instalação sem token de admin — não só em desenvolvimento.
- **A decoração de proveniência saiu de `main` para `app/api/proveniencia.py`.**
  As duas superfícies decoram; com o código em `main`, o plano de controle
  teria de importar quem já o importa.
- **`/v1/capturas/{id}/arquivo` continua sendo o endereço do arquivo**, também
  no plano de controle. É o que a própria API publica em `proveniencia.
  arquivo_em` de toda resposta; um segundo endereço para os mesmos bytes seria
  pior que o 401 que ele dá localmente sem token configurado.
- **O gate de acessibilidade cobre seis superfícies**, não duas. Foi ele que
  pegou o `p` solto dentro do `dl` da tela de gestão — invisível a olho.

## Verificado nesta etapa

- Da classe `negociacao_b3` ao atributo `volatilidade_implicita`, dele à
  expressão do núcleo, às colunas que usa, às três regras que o vigiam, à URL
  oficial da B3 e ao arquivo capturado. `COTAHIST_D31072026.ZIP` baixado pela
  rota: 402.103 bytes, sha256 `0a5e23de292b…`, idêntico ao que a tela exibe.
- Travessia `empresa_demonstracoes` executada pela interface, com proveniência
  decorada — sem `captura_id` nem `publicado_em_versao` posando de atributo.
- 418 testes Python, 35 no front, `tsc` limpo, `axe` com zero violação nas
  seis superfícies.

## Próxima ação

Etapa 6: a camada de acesso aditiva do
[ADR-19](arquitetura.md#adr-19--passkey-entra-ao-lado-do-token-não-no-lugar).
Passkey ao lado do token, nunca no lugar — `PORTAL_ACESSO_LEGADO` é a saída de
emergência e já está documentada em `deploy-railway.md`.

Duas decisões do Alex continuam abertas: qual das quatro direções visuais fica,
e quando subir (o branch está à frente de `origin/main`).
