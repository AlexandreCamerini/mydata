// A companhia como ponto de partida: de onde se navega para tudo que existe
// sobre ela.
//
// A regra que governa esta tela: **porta que não abre é pior que porta
// ausente**. Cada família de dado só vira link depois que `/v1/…/resumo` diz
// que há linha, e traz quanto e de que período. O que não existe aparece
// mesmo assim, dizendo por que não existe — omitir em silêncio faria o
// usuário procurar num lugar onde não há nada.
//
// O dicionário de grupos da CVM (BPA, DRE, DFC_MI…) mora aqui, não na API:
// traduzir "BPA" para "balanço patrimonial" é conhecimento de uma fonte
// específica, e a API responde por todas.
import { Carregando, Erro, Selo, Vazio, useDados } from "../ui";
import { api, type Empresa as Companhia, type ResumoEmpresa } from "./api";

const fmt = new Intl.NumberFormat("pt-BR");

/** Como os grupos da CVM se juntam no que uma pessoa chama de demonstração. */
const FAMILIAS: { nome: string; sobre: string; grupos: string[] }[] = [
  {
    nome: "Balanço patrimonial",
    sobre: "O que a companhia tem e o que deve, na data de fechamento.",
    grupos: ["BPA", "BPP"],
  },
  {
    nome: "Resultado",
    sobre: "Receita, custo e lucro do exercício, e o resultado abrangente.",
    grupos: ["DRE", "DRA"],
  },
  {
    nome: "Fluxo de caixa",
    sobre: "De onde o dinheiro veio e para onde foi, pelos dois métodos.",
    grupos: ["DFC_MI", "DFC_MD"],
  },
  {
    nome: "Valor adicionado",
    sobre: "Quanto de riqueza a companhia gerou e como ela foi distribuída.",
    grupos: ["DVA"],
  },
  {
    nome: "Mutações do patrimônio líquido",
    sobre: "O que moveu o patrimônio dos sócios ao longo do exercício.",
    grupos: ["DMPL"],
  },
];

/** O que ainda não existe, com o motivo. Some quando a fonte entrar. */
const AUSENTES = [
  {
    nome: "Cotação",
    sobre: "Série de preço do papel em bolsa.",
    porque:
      "Nenhuma fonte cadastrada. Os termos de uso da B3 vedam redistribuição, " +
      "então o arquivo histórico dela não pode virar dado publicado aqui sem " +
      "autorização por escrito.",
  },
  {
    nome: "Opções",
    sobre: "Séries, strikes e vencimentos dos derivativos do papel.",
    porque:
      "Nenhuma fonte cadastrada. O cliente do brapi já está no repositório e " +
      "sabe pedir a cadeia de opções, mas brapi é agregador — entraria como " +
      "dado de terceiro, marcado, nunca como origem.",
  },
  {
    nome: "Proventos",
    sobre: "Dividendos e juros sobre capital próprio declarados.",
    porque:
      "Nenhuma fonte cadastrada. A CVM publica em documento separado, ainda " +
      "não mapeado.",
  },
];

function periodo(de: string, ate: string): string {
  const a = de.slice(0, 4);
  const b = ate.slice(0, 4);
  return a === b ? a : `${a}–${b}`;
}

function Cartao(props: {
  nome: string;
  sobre: string;
  href?: string;
  medida?: string;
  detalhe?: string;
  estado?: string;
  indisponivel?: string;
}) {
  const corpo = (
    <>
      <div className="flex items-baseline gap-2">
        <span className="font-medium">{props.nome}</span>
        {props.estado && <Selo texto={props.estado} />}
      </div>
      <p className="text-xs text-tinta-suave">{props.sobre}</p>
      {props.medida && (
        <p className="text-sm tabular-nums">
          {props.medida}
          {props.detalhe && (
            <span className="text-tinta-suave text-xs"> · {props.detalhe}</span>
          )}
        </p>
      )}
      {props.indisponivel && (
        <p className="text-xs text-tinta-suave">{props.indisponivel}</p>
      )}
    </>
  );

  const classe =
    "border border-borda rounded bg-white p-3 grid gap-1 content-start";

  if (!props.href) {
    // Indisponível é borda tracejada, não opacidade: opacidade derruba o
    // contraste do texto abaixo de 4.5:1 — a auditoria pegou exatamente estes
    // seis parágrafos — e ainda por cima é um sinal que ninguém lê como
    // "isto não existe".
    return (
      <div className={`${classe} border-dashed`}>
        {corpo}
      </div>
    );
  }
  return (
    <a
      href={props.href}
      className={`${classe} hover:border-tinta focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-1`}
    >
      {corpo}
    </a>
  );
}

export function Empresa({ cd_cvm }: { cd_cvm: number }) {
  const ficha = useDados(() => api.empresa(cd_cvm), [cd_cvm]);
  const resumo = useDados(() => api.resumo(cd_cvm), [cd_cvm]);

  if ((ficha.carregando && !ficha.dados) || (resumo.carregando && !resumo.dados))
    return <Carregando oque="a companhia" />;
  if (ficha.erro) return <Erro mensagem={ficha.erro} />;
  if (resumo.erro) return <Erro mensagem={resumo.erro} />;
  if (!ficha.dados || !resumo.dados)
    return <Vazio titulo="Companhia não encontrada" />;

  const e: Companhia = ficha.dados.dados;
  const r: ResumoEmpresa = resumo.dados.dados;

  // Uma família reúne mais de um grupo da CVM; a contagem é a soma deles, e o
  // período é a união. Consolidado e individual entram juntos aqui porque a
  // escolha entre os dois é da tela de demonstrações, não desta.
  const porFamilia = FAMILIAS.map((f) => {
    const linhas = r.demonstracoes.filter((d) => f.grupos.includes(d.grupo));
    return {
      ...f,
      total: linhas.reduce((s, d) => s + d.linhas, 0),
      de: linhas.map((d) => d.de).sort()[0] ?? "",
      ate: linhas.map((d) => d.ate).sort().slice(-1)[0] ?? "",
      // Abre no primeiro grupo declarado que tem dado. A ordem em FAMILIAS é
      // a ordem natural de leitura — ativo antes de passivo, resultado antes
      // do abrangente —, e não a de volume: o passivo tem mais linhas que o
      // ativo, e abrir o balanço pelo passivo é começar pelo fim.
      grupoAbrir:
        f.grupos.find((g) => linhas.some((d) => d.grupo === g)) ?? f.grupos[0],
    };
  });

  const comDado = porFamilia.filter((f) => f.total > 0);
  const semDado = porFamilia.filter((f) => f.total === 0);

  return (
    <div className="grid gap-6">
      <header className="grid gap-1">
        <p className="text-xs text-tinta-suave">
          <a href="#/" className="underline decoration-dotted">
            Companhias
          </a>{" "}
          / {e.cd_cvm}
        </p>
        <h1 className="text-xl font-semibold">
          {e.denom_social ?? `Companhia ${e.cd_cvm}`}
        </h1>
        <p className="text-sm text-tinta-suave flex flex-wrap gap-x-3 gap-y-1">
          {e.ticker && <span className="font-mono">{e.ticker}</span>}
          {e.cnpj && <span>{e.cnpj}</span>}
          {e.setor_atividade && <span>{e.setor_atividade}</span>}
          {e.segmento_listagem && <span>{e.segmento_listagem}</span>}
          {e.situacao && <Selo texto={e.situacao.toLowerCase()} />}
        </p>
      </header>

      {comDado.length > 0 && (
        <section aria-labelledby="tem" className="grid gap-2">
          <h2 id="tem" className="font-medium">
            O que existe sobre esta companhia
          </h2>
          <div className="grid gap-2 sm:grid-cols-2">
            {comDado.map((f) => (
              <Cartao
                key={f.nome}
                nome={f.nome}
                sobre={f.sobre}
                href={`#/empresa/${cd_cvm}/demonstracoes/${f.grupoAbrir}`}
                medida={`${fmt.format(f.total)} linhas`}
                detalhe={periodo(f.de, f.ate)}
              />
            ))}

            {r.trimestres && (
              <Cartao
                nome="Trimestres isolados"
                sobre="O ITR publica acumulado no ano; aqui o trimestre já vem separado."
                href={`#/empresa/${cd_cvm}/demonstracoes/DRE`}
                medida={`${fmt.format(r.trimestres.linhas)} linhas`}
                detalhe={periodo(r.trimestres.de, r.trimestres.ate)}
                estado="derivado"
              />
            )}

            {r.metricas.length > 0 && (
              <Cartao
                nome="Indicadores"
                sobre="Calculados a partir das contas, com as colunas de origem declaradas."
                href={`#/empresa/${cd_cvm}/indicadores`}
                medida={`${r.metricas.length} indicadores`}
                detalhe={r.metricas.slice(0, 3).join(", ")}
                estado="calculado"
              />
            )}

            <Cartao
              nome="Identificação e proveniência"
              sobre="Cadastro, registro na B3, e qual fonte venceu cada campo."
              href={`#/empresa/${cd_cvm}/ficha`}
              medida="Ficha completa"
            />

            {r.capturas.length > 0 && (
              <Cartao
                nome="Arquivos originais"
                sobre="Os documentos que a fonte publicou, como ela os publicou."
                href={`#/empresa/${cd_cvm}/arquivos`}
                medida={`${r.capturas.length} arquivos`}
                detalhe="com digital conferível"
              />
            )}
          </div>
        </section>
      )}

      {(semDado.length > 0 || AUSENTES.length > 0) && (
        <section aria-labelledby="nao-tem" className="grid gap-2">
          <h2 id="nao-tem" className="font-medium">
            O que não existe, e por quê
          </h2>
          <p className="text-xs text-tinta-suave">
            Aparece aqui em vez de sumir: saber que um dado não está no ar vale
            mais que procurá-lo num lugar onde ele nunca esteve.
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {semDado.map((f) => (
              <Cartao
                key={f.nome}
                nome={f.nome}
                sobre={f.sobre}
                indisponivel="Esta companhia não publicou este demonstrativo nos exercícios carregados."
              />
            ))}
            {AUSENTES.map((a) => (
              <Cartao
                key={a.nome}
                nome={a.nome}
                sobre={a.sobre}
                indisponivel={a.porque}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
