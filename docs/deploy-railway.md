# Deploy no Railway — `mydata.acamerini.app`

O MyData é sistema independente: serve vários consumidores e por isso tem
endereço próprio. **Não reivindicar o ápice `acamerini.app`** — ele pertence a
outro sistema, e um domínio customizado no Railway aponta para um serviço só,
então tomá-lo tiraria aquele sistema do ar.

A URL pública sai de `PORTAL_URL_PUBLICA` e de lugar nenhum mais. Se um dia o
MyData ganhar domínio registrado à parte, migrar é trocar essa variável e o
DNS, sem tocar em código.

Um serviço só, ocupando a raiz do **seu** domínio:

| Caminho | O quê |
|---|---|
| `/` | interface do plano de controle (build estático) |
| `/v1` | API pública consumida pelos apps |
| `/admin/api` | plano de controle sobre HTTP |
| `/health` | healthcheck do Railway, sem tocar no banco |
| `/docs`, `/openapi.json` | contrato |

Cada consumidor chama `/v1` com a chave de API dele, e o escopo da chave diz
quais classes de informação pode ler. O que cada um precisa informar para ser
integrado está em [contrato-consumidor.md](contrato-consumidor.md).

## O que já está no repositório

- `railway.json` — builder Docker, healthcheck em `/health`, e o boot roda
  `python -m app.cli migrar --seed` antes de servir. O seed é idempotente por
  digest: reaplicar configuração idêntica não cria versão nova.
- `Dockerfile` — build do front e da API na mesma imagem, usuário não-root,
  porta vinda de `$PORT`.
- `.env.example` — toda variável que o código lê. Há um teste que falha se
  aparecer variável nova sem documentação.

## O que depende do painel (não dá para automatizar daqui)

1. **Provisionar o Postgres do projeto.** O Railway injeta `DATABASE_URL`
   sozinho; o código escolhe Postgres quando ela existe e DuckDB quando não.
2. **Apontar o domínio.** Settings → Networking → Custom Domain →
   `mydata.acamerini.app` — **não** o ápice. O Railway devolve um CNAME; ele
   entra no DNS do registrador como um registro a mais, sem mexer no que já
   estiver apontando para outro sistema. O certificado é emitido pela borda do Railway, e o
   redirecionamento de `http` para `https` é dela também — não há nada a
   fazer no app.
3. **Definir as variáveis** no serviço:

   | Variável | Valor |
   |---|---|
   | `PORTAL_URL_PUBLICA` | `https://mydata.acamerini.app` |
   | `PORTAL_ORIGENS` | as origens dos consumidores, separadas por vírgula |
   | `PORTAL_ADMIN_TOKEN` | segredo do dono. Gere com `python -c "import secrets; print(secrets.token_urlsafe(32))"` — o painel do Railway não tem gerador para isto. Sem a variável, `/admin/api` fica aberto (modo de desenvolvimento local) |
   | `PORTAL_ACESSO_LEGADO` | `1` reabilita o caminho do token depois de o passkey entrar. **É a saída de emergência** ([ADR-19](arquitetura.md#adr-19--passkey-entra-ao-lado-do-token-não-no-lugar)): se o autenticador se perder, defina esta variável no painel e entre com o token de novo |

   `PORTAL_URL_PUBLICA` é o que faz o OpenAPI anunciar o domínio real. Sem
   ela, o cliente gerado a partir do schema aponta para `localhost`.

   `PORTAL_ORIGENS` vazio nega toda origem cruzada. É negar por omissão de
   propósito: liberar `*` "só em dev" é o tipo de default que chega em
   produção.

4. **Agendar o cron.** Um serviço de cron no mesmo projeto, comando
   `python -m app.cli agendados`. Ele lê `cfg_agendamento` e roda o que
   estiver vencido — DFP anual, ITR trimestral, cadastro semanal, pregão
   diário.

   **A frequência do painel não é o horário das cargas.** O painel só acorda
   o processo; quem decide o que roda é `cfg_agendamento`. Acordar de hora em
   hora é suficiente e barato: cada invocação que não tem nada vencido sai em
   milissegundos. O que importa é acordar pelo menos uma vez entre dois
   disparos do agendamento mais frequente — hoje o do COTAHIST, às 23:59.

   **O horário declarado vale no fuso declarado.** Até 04/08/2026 a coluna
   `cfg_agendamento.timezone` era gravada e nunca lida, e todo cron era
   avaliado em UTC: o `0 6` da DFP disparava às 03:00 de Brasília. Agora
   `59 23` em `America/Sao_Paulo` é 23:59 em São Paulo. Se você tinha algum
   horário calibrado contra o comportamento antigo, ele mudou em três horas.

5. **Emitir a chave de cada app**, com o escopo dele:

   ```
   python -m app.cli chave bolsia --classe demonstracao_financeira --classe empresa
   python -m app.cli chave watchlist --classe empresa
   ```

   A chave completa aparece uma única vez. No banco fica só o hash.

## Verificação depois do DNS propagar

```bash
curl -sI https://mydata.acamerini.app/health
curl -s https://mydata.acamerini.app/openapi.json | head -c 300
curl -s -H "X-API-Key: $CHAVE" https://mydata.acamerini.app/v1/meta/frescor
```

O primeiro tem de dar 200; o segundo tem de trazer `"servers"` com a URL
pública; o terceiro diz se alguma classe está fora do SLA.

## Primeira carga

O bronze é a única coisa não reconstruível, então a primeira ingestão é o que
importa preservar:

```bash
python -m app.cli ingerir cvm_dfp 2023
python -m app.cli ingerir cvm_cadastro atual
python -m app.cli verificar
```

Depois disso, `python -m app.cli recomputar` reconstrói todo o derivado do
bronze e compara a digital antes e depois. É o caminho de volta de qualquer
correção — e o comando devolve código 3 se o recomputo não reproduzir o
estado, o que significa que algo entrou no banco por fora do pipeline.
