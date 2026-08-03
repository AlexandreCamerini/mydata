# Fundação de dados

Esta é a regra de onde cada dado mora, e ela vale para todo sistema construído
aqui — os que existem hoje e os que ainda não foram escritos. Quando uma
decisão de arquitetura tocar em dado, é este documento que decide.

Você provavelmente chegou aqui sem ter participado de nenhuma das conversas
que produziram o MyData. Não precisa: o que segue é auto-contido, e o teste da
§2 responde sozinho.

## 1. A tese, e a assimetria

**Dado que o mercado publicou é de um lugar só.** Ele é capturado uma vez,
guardado intacto, e servido a quem precisar. Não há segunda cópia, não há
segunda verdade, e não há um app que "também tem" a demonstração financeira da
Petrobras.

Esse lugar é o MyData. Existe para o dado vir da origem oficial em vez de um
intermediário que apenas atravessa a informação e cobra por isso — e por
consequência, para que a resposta a *"de onde veio esse número?"* seja um
arquivo com hash, não um nome de fornecedor.

**Dado que o seu app produziu é do seu app.** A carteira do usuário, o que ele
clicou, a classificação que o app inventou, a preferência que ele salvou: nada
disso é de mercado, nada disso tem fonte oficial, e nada disso pertence ao
MyData.

A dependência entre os dois é **assimétrica, e isso é propriedade de projeto,
não acaso**:

> O app depende do MyData. O MyData não depende de app nenhum.

O MyData sobe, ingere, publica e responde sem que nenhum consumidor exista. No
dia em que ele precisar de código de um consumidor para funcionar, a
independência acabou — e com ela a garantia de que o dado continua no ar quando
um app quebra.

## 2. O teste de decisão

Quatro perguntas encadeadas. Cada uma tem resposta determinística; a primeira
que fechar decide.

**P1. Quem produziu o dado?**

- O seu app — o usuário digitou, o app observou, o app escolheu → **é do app.**
  Fim.
- Uma fonte fora dos seus sistemas → siga para P2.

**P2. É o número que a fonte publicou, ou uma conclusão sobre ele?**

- O número publicado → **é do MyData**, como classe de informação. Fim.
- Uma conclusão → siga para P3.

**P3. A conclusão é reproduzível por qualquer um, a partir do dado publicado e
de uma regra escrita, sem depender de juízo seu?**

- Sim → **é do MyData**, como campo calculado ou métrica declarada. A regra vai
  para o catálogo, declarando as colunas de origem que usa.
- Não — embute peso, modelo, escolha editorial ou preferência do usuário →
  **é do app.**

**P4. Você está guardando uma cópia de algo que o MyData já publica?**

- Então é **cache**, com validade declarada e revalidação contra
  `GET /v1/meta/frescor`. Cache nunca é fonte: não é o que o app cita quando
  alguém pergunta de onde veio o número, e não é servido adiante como se fosse
  dado próprio.

E uma regra que não é pergunta, porque não admite caso a caso:

**R5. Quantos consumidores um dado tem não entra na conta.** Dado de mercado que
hoje só um app lê continua sendo do MyData. Se a demanda interna decidisse, o
primeiro consumidor de cada classe teria de guardá-la em casa — e na segunda vez
que alguém precisasse, existiriam duas cópias livres para divergir.

### Os cinco casos, resolvidos

| Caso | Percurso | Onde mora |
|---|---|---|
| **P/L da Petrobras** — indicador calculado sobre dado-verdade | P1 fonte externa → P2 conclusão → P3 sim: P/L é convenção pública, a regra cabe numa linha e não embute juízo | **MyData**, campo calculado declarando lucro e preço como origem |
| **Score de qualidade do BolsIA** — classificação proprietária | P1 fonte externa → P2 conclusão → P3 não: os pesos são escolha do app | **App.** Os insumos continuam vindo do MyData por `/v1`; o app lê e calcula, não guarda cópia |
| **Calendário de dividendos**, hoje só o BolsIA usa | P1 fonte externa → P2 número publicado | **MyData.** R5: um consumidor só não muda a resposta |
| **Cópia local da classe `empresa`** para não chamar a API a cada tela | P4 | **Cache**, com validade declarada. O app não pode citá-lo como origem nem servi-lo adiante |
| **CNPJ das companhias com registro cancelado**, pedido por um terceiro público que não é app do Alex | P1 fonte externa → P2 número publicado | **MyData.** O critério é a fonte, não a demanda interna — "nenhum app meu usa" deixou de ser motivo para não publicar |

O quinto caso é o que o teste ganhou quando o MyData passou a ter consumidor
fora da casa. Ele não muda nenhuma resposta anterior; só torna explícito que a
fronteira sempre foi sobre **origem**, nunca sobre uso.

## 3. Como o consumidor lê

**Uma porta.** `GET /v1`, com chave de API. Nenhum app abre conexão com o
Postgres do MyData, e nenhum app replica uma classe para banco próprio como
fonte.

**Escopo por classe.** A chave declara quais classes de informação ele lê —
"este app lê Empresa e Demonstração Financeira". Rota é detalhe de
implementação; classe é o que o consumidor entende, e app novo é chave nova, não
código novo.

**Proveniência acompanha todo número.** Fonte, `sha256` da captura, versão do
documento e publicação vêm na resposta. Onde mais de uma fonte disputa o mesmo
atributo, `proveniencia.por_atributo` diz qual venceu cada campo.

**O que o consumidor nunca faz:** tratar cache como fonte; apresentar número
derivado de terceiro como se fosse do documento oficial; guardar dado de mercado
como propriedade sua; ou depender de um endereço fixo em código — a URL vive numa
variável de configuração, de um lado e do outro.

## 4. O invariante do original

O arquivo que a fonte publicou é gravado intacto, com SHA-256, URL e timestamp
de captura, e nunca é reescrito nem apagado. A imutabilidade é imposta por
trigger, não por convenção
([ADR-10](arquitetura.md#adr-10--bronze-em-tabela-não-em-volume)).

Tudo o que se deriva dele — tipagem, campos calculados, vistas publicadas — é
descartável por construção. Dropar e recomputar do original é a rotina normal de
correção, não um último recurso.

**O que se perde quando um projeto guarda "o dado já tratado":** a capacidade de
descobrir que o tratamento estava errado. Um bug de normalização em cima do
arquivo original é um recomputo; o mesmo bug em cima de uma cópia já tratada é
permanente e invisível, porque não sobrou nada com que comparar. E a URL da
origem costuma ser endereço mutável — reapresentado, regerado, movido —, então
"baixar de novo" não reproduz a captura de antes.

É por isso que o original é a única coisa aqui que não se pode reconstruir, e a
única que nunca se toca.

## 5. Como esta lei se aplica

O mecanismo, não a intenção:

1. **O ponteiro é global.** `~/.claude/CLAUDE.md` aponta para este documento, e
   é carregado em toda sessão de todo projeto. É o que faz "obrigatório" ser
   mecânico em vez de aspiracional.
2. **Discordar é permitido; discordar em silêncio não.** Uma decisão que
   contrarie este documento vira ADR novo **aqui**, com contexto, alternativa
   descartada e consequência, antes de virar código lá. O registro fica em
   [arquitetura.md § 11](arquitetura.md#11-decisões-arquiteturais).
3. **A fronteira atravessada vira item de contrato.** O que um consumidor precisa
   do MyData entra em
   [contrato-consumidor.md](contrato-consumidor.md) para ser negociado entre os
   dois projetos — nunca editando o repositório do outro lado.

## 6. O que este documento não resolve

**Multi-tenant.** O escopo por classe decide *quais* classes um app lê. Não
decide isolamento de linha dentro da classe: se um dia dois consumidores
precisarem ver linhas diferentes da mesma classe, o modelo não suporta e a
decisão é nova. Continua aberto como
[questão 2 do §14](arquitetura.md#14-questões-em-aberto).

**Autenticação de usuário final.** O MyData autentica consumidor — um app, um
serviço —, não a pessoa que usa o app. Quem é o usuário é assunto de quem o
atende.

**Correção de número.** O portal publica o que a fonte disse. Um número errado
no documento oficial é errado no MyData, e corrigi-lo é assunto da origem: o
portal registra a reapresentação quando ela vier, e mostra qual versão está no
ar.
