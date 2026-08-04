# Fontes de terceiro

O MyData existe para servir dado da origem oficial. Uma fonte de terceiro entra
mesmo assim, sob regra estreita, porque há informação que a origem oficial não
publica — o ticker de negociação é o caso conhecido
([§14.1](arquitetura.md#14-questões-em-aberto)).

## A regra

Vem do [ADR-9](arquitetura.md#11-decisões-arquiteturais): terceiro entra "como
atalho validado contra ela". Na prática, quatro condições:

1. **Menor precedência.** Em qualquer atributo que a fonte oficial também
   preencha, o oficial vence — a declaração de precedência é por atributo
   ([ADR-13](arquitetura.md#11-decisões-arquiteturais)), então isso é
   configuração, não código.
2. **Marcado na resposta.** O consumidor vê em `proveniencia.por_atributo` que
   aquele campo veio de terceiro, e de qual.
3. **Nunca misturado ao oficial.** Um número derivado de terceiro não pode ser
   apresentado como se tivesse vindo do documento da CVM.
4. **Validado contra o oficial onde houver sobreposição.** Divergência é
   evento a investigar, não a acomodar.

O que essa regra protege: o produto é a proveniência auditável. Um agregador
republicando sem dizer de onde veio é exatamente o intermediário que o MyData
existe para dispensar.

## brapi.dev

Cliente em [`src/brapi_client/`](../src/brapi_client/), com a história vinda do
repositório `scrap`. Cobre as famílias que a API expõe: ações
(`quote`, `quote/list`, `available`), opções, criptomoedas, moedas, inflação e
taxa básica de juros.

O cliente é biblioteca de acesso, como `src/cvm_financas/`. Ele não é o caminho
de ingestão: quem ingere é o motor, por `cfg_fonte` + `cfg_dataset`, com bronze
imutável e gate de qualidade — nada disso o cliente tem. Ele serve para
exploração, para conferência pontual, e como catálogo verificado de quais
endpoints existem e com que parâmetros.

**brapi é agregador, não origem.** Cada família vem de uma fonte primária
diferente, com atraso próprio:

| Serviço | Fonte primária | Frescor |
|---|---|---|
| `quote` (preço) | B3 | atrasado por plano: grátis ~30min, startup ~15min, pro ~5min |
| `quote` fundamentos (BP/DRE/DFC/DVA) | CVM | trimestral, na cadência da própria CVM |
| índices financeiros | Yahoo Finance | não confirmado |
| moedas (FX) | awesomeapi + BCB | não confirmado |
| inflação, taxa básica | BCB | não confirmado — séries do BCB costumam ser D-1 |
| cripto | não confirmado | não confirmado |

**Confiança: média.** A tabela foi montada a partir de trechos indexados do FAQ
do brapi (`/faq/fonte-de-dados`, `/faq/qual-a-frequencia`), não de leitura
direta: o site responde 403 a busca automatizada. Reconfirmar antes de uma
decisão se apoiar nela.

Duas consequências que já decidem coisas:

- **Preço não vem daqui.** A linha `quote` é a B3 com atraso e sem o arquivo
  original. Série de preço para o MyData sai do arquivo oficial da B3, que é
  capturável em bronze com SHA-256. Usar o brapi como fonte de preço faria o
  MyData republicar um republicador.
- **Fundamentos, menos ainda.** Vêm da CVM, que o MyData já ingere na origem.

O que sobra como uso legítimo hoje: o mapa **ticker → empresa**, que a CVM não
publica, e macro (SELIC, IPCA) enquanto o BCB não entrar como fonte direta.

**Autenticação:** `BRAPI_TOKEN` no ambiente, ou `token=` no construtor. Quatro
tickers (PETR4, MGLU3, VALE3, ITUB4) respondem sem token; o resto exige, mesmo
no plano gratuito.

**Testes não tocam a rede** — `requests.Session.get` é mockado. Rodar a suíte
não pode queimar cota de plano gratuito.

## As cargas possíveis do brapi

A documentação oficial lista oito famílias de recurso. Passadas pela regra
acima e pelas decisões já registradas, quase nenhuma sobrevive — e o motivo é
bom: o que o brapi agrega, este hub já ingere na origem.

| Recurso | Endpoint | Fonte primária | Cabe aqui? |
|---|---|---|---|
| Cotação | `quote/{tickers}` | B3, atrasada por plano | **Não.** É a B3 sem o arquivo original, e os termos dela vedam redistribuição (§Q4 da pesquisa) |
| Histórico de preço | `quote/{t}?range=&interval=` | B3 | **Não**, mesmo motivo |
| Fundamentos | `quote/{t}?fundamental=true` | CVM | **Não.** Já ingerimos DFP e ITR na origem, com o ZIP guardado e conferível |
| Inflação | `v2/inflation` | BCB | **Não.** O SGS já entra direto desde a etapa 5 |
| Taxa de juros | `v2/prime-rate` | BCB | **Não**, idem — Selic e CDI são séries 432 e 4389 |
| Câmbio | `v2/currency` | awesomeapi + BCB | **Não**, idem — série 1 |
| Criptomoedas | `v2/crypto` | não confirmada | **Não.** Fora do escopo de um hub de companhias abertas |
| Dividendos | `quote/{t}?dividends=true` | não confirmada | **Talvez.** É a única lacuna real — "Proventos" aparece como ausente na tela da companhia |
| Lista de tickers | `quote/list`, `available` | B3 | **Talvez.** Segunda fonte para o mapa ticker↔empresa da [questão 1 do §14](arquitetura.md#14-questões-em-aberto), abaixo da B3 na precedência |
| Opções | `v2/options/*` | **não confirmada** | **Pendente.** Ver abaixo |

### O que a documentação não diz

A página de SDKs enumera os recursos suportados e **opções não está entre
eles** — aparecem ações, fundamentos, dividendos, histórico, cripto, inflação,
juros e câmbio. Os endpoints `v2/options/expirations`, `/strikes`, `/chain`,
`/analytics` existem no cliente que herdamos do repositório `scrap`, mas a
tabela de fonte primária que veio junto também não cobre opções.

Isso importa porque a origem decide a resposta: se a cadeia de opções vem da
B3, republicá-la esbarra nos mesmos termos que barraram o COTAHIST, e passar
por um agregador não muda a origem do dado — muda só de quem é o contrato.
Antes de ativar, é preciso confirmar isso.

### O custo, que também decide

O plano gratuito é de 15.000 requisições por mês e devolve 402 ao estourar.
A conta muda tudo:

| Carga | Requisições por execução | Diária dá em |
|---|---|---|
| `quote/list` | 1 | ~30/mês — cabe folgado |
| Dividendos por papel | 1 por ticker · 564 tickers | ~17.000/mês — **estoura** |
| Cadeia de opções por papel | 1 por ticker com opção | estoura mais rápido ainda |

Dividendos e opções só cabem no plano gratuito em cadência semanal, ou
restritos a um subconjunto de papéis. Isso é decisão de produto, não de
engenharia, e precisa ser tomada antes de a carga entrar.

### Como ativar uma delas

A fonte já está cadastrada, com `{recurso}` no template e credencial
declarada. Ativar é um mapeamento novo, sem código:

```
cfg_dataset
  fonte_chave      brapi
  parametros       {"recurso": "quote/list"}
  classe_chave     <a classe que ela alimenta>
  caminho_registros stocks
  colunas          stock → ticker, name → nome_pregao, …
```

E, no ambiente, `BRAPI_TOKEN` definido — o token não entra no banco.
