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
   | `PORTAL_ACESSO_LEGADO` | `1` reabilita o formulário de token depois de o passkey entrar. **É a saída de emergência** ([ADR-19](arquitetura.md#adr-19--passkey-entra-ao-lado-do-token-não-no-lugar)): se o autenticador se perder, defina esta variável no painel e entre com o token de novo |

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
   disparos do agendamento mais frequente — hoje o do COTAHIST, às 23:59, com
   o cadastro de instrumentos meia hora antes.

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

## Primeiro acesso, e o passkey

A camada de acesso é aditiva: o token continua sendo o que abre a porta, e é
por ele que o primeiro autenticador entra.

1. Abra `https://mydata.acamerini.app/` e entre com `PORTAL_ADMIN_TOKEN`.
2. Vá em **Acesso** no `/admin` e registre um autenticador, com rótulo.
3. **Registre um segundo, em outro aparelho.** É a saída mais barata do risco
   desta decisão, e a tela avisa enquanto houver só um.

A partir do primeiro registro, o formulário de token some da tela de entrada —
o campo de segredo digitado era a queixa que motivou a mudança. O que **não**
muda:

- `X-Admin-Token` continua valendo sempre, para `curl` e script. Quem opera
  por terminal nunca fica trancado, e é por ele que se revoga um autenticador
  que não se tem mais em mãos.
- A chave de API por consumidor em `/v1` não é tocada. São mecanismos
  diferentes para públicos diferentes.

Perdeu todos os autenticadores e não quer usar o terminal: defina
`PORTAL_ACESSO_LEGADO=1` no painel, entre com o token, revogue o que se
perdeu, registre outro, e desligue a variável.

**A credencial fica presa ao domínio.** O `rp_id` sai de `PORTAL_URL_PUBLICA`;
trocar o endereço público invalida os passkeys registrados no anterior, e o
caminho de volta é o mesmo `PORTAL_ACESSO_LEGADO=1`.

## Conferir a compressão do bronze, depois da primeira captura nova

O [ADR-21](arquitetura.md#adr-21--bronze-volta-a-ser-comprimido-pelo-postgres-e-não-pela-aplicação)
religou a compressão do TOAST na coluna do payload. `STORAGE` vale para valor
**novo**, então o efeito só aparece depois de uma captura posterior ao deploy —
as antigas continuam como estão, byte a byte, e é assim que tem de ser.

```sql
SELECT pg_size_pretty(sum(octet_length(payload)))   AS arquivo,
       pg_size_pretty(sum(pg_column_size(payload))) AS em_disco
FROM bronze_captura WHERE dataset_chave = 'b3_instrumentos';
```

Medido em laboratório, um CSV como esse comprime uma ordem de grandeza. Se o
`pglz` render menos de 4×, o ADR-21 diz o que fazer — e a alternativa do gzip na
aplicação volta à mesa com número em vez de suposição.

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
python -m app.cli ingerir b3_instrumentos 2026-08-04   # o cadastro de hoje
python -m app.cli verificar
```

O cadastro de instrumentos merece um parágrafo à parte, porque ele é o mais
caro em bronze de tudo que este hub ingere: ~33 MB por pregão contra ~0,5 MB do
COTAHIST. Carregar dias antigos **acumula**, não substitui — a identidade é o
ticker, e cada dia antigo insere as séries que já saíram do cadastro atual sem
sobrescrever o estado de hoje. Isso é o que dá estilo de exercício às cadeias
retroativas, e é também o que multiplica o bronze. Decida quantos dias você
quer antes de carregá-los.

Depois disso, `python -m app.cli recomputar` reconstrói todo o derivado do
bronze e compara a digital antes e depois. É o caminho de volta de qualquer
correção — e o comando devolve código 3 se o recomputo não reproduzir o
estado, o que significa que algo entrou no banco por fora do pipeline.
