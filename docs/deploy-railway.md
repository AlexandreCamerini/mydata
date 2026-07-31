# Deploy no Railway — `acamerini.app`

Um serviço só, ocupando a raiz do domínio:

| Caminho | O quê |
|---|---|
| `/` | interface do plano de controle (build estático) |
| `/v1` | API pública consumida pelos apps |
| `/admin/api` | plano de controle sobre HTTP |
| `/health` | healthcheck do Railway, sem tocar no banco |
| `/docs`, `/openapi.json` | contrato |

Os apps consumidores vivem em subdomínios próprios (`bolsia.acamerini.app`,
`app.acamerini.app`) e chamam `/v1` com a chave de API deles.

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
   `acamerini.app`. O Railway devolve um CNAME; ele entra no DNS do
   registrador. O certificado é emitido pela borda do Railway, e o
   redirecionamento de `http` para `https` é dela também — não há nada a
   fazer no app.
3. **Definir as variáveis** no serviço:

   | Variável | Valor |
   |---|---|
   | `PORTAL_URL_PUBLICA` | `https://acamerini.app` |
   | `PORTAL_ORIGENS` | os subdomínios dos apps, separados por vírgula |
   | `PORTAL_ADMIN_TOKEN` | segredo gerado no painel; sem ele o `/admin/api` fica aberto |

   `PORTAL_URL_PUBLICA` é o que faz o OpenAPI anunciar o domínio real. Sem
   ela, o cliente gerado a partir do schema aponta para `localhost`.

   `PORTAL_ORIGENS` vazio nega toda origem cruzada. É negar por omissão de
   propósito: liberar `*` "só em dev" é o tipo de default que chega em
   produção.

4. **Agendar o cron.** Um serviço de cron no mesmo projeto, comando
   `python -m app.cli agendados`. Ele lê `cfg_agendamento` e roda o que
   estiver vencido — DFP anual, ITR trimestral, cadastro semanal.

5. **Emitir a chave de cada app**, com o escopo dele:

   ```
   python -m app.cli chave bolsia --classe demonstracao_financeira --classe empresa
   python -m app.cli chave watchlist --classe empresa
   ```

   A chave completa aparece uma única vez. No banco fica só o hash.

## Verificação depois do DNS propagar

```bash
curl -sI https://acamerini.app/health
curl -s https://acamerini.app/openapi.json | head -c 300
curl -s -H "X-API-Key: $CHAVE" https://acamerini.app/v1/meta/frescor
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
