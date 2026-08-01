// A ficha da companhia: o que a classe empresa sabe, e de onde cada pedaço
// veio. O diferencial do produto é a proveniência — se a tela a escondesse,
// o portal viraria mais um revendedor de dado.
import { Carregando, Erro, Selo, Tabela, useDados } from "../ui";
import { api, type Empresa, type MetaClasse } from "./api";

// Ordem e rótulo do que a ficha mostra. Os nomes técnicos ficam visíveis ao
// lado: são eles que o consumidor da API vai usar.
const CAMPOS: [keyof Empresa, string][] = [
  ["denom_social", "Razão social"],
  ["denom_comerc", "Nome comercial"],
  ["nome_pregao", "Nome de pregão"],
  ["cnpj", "CNPJ"],
  ["cd_cvm", "Código CVM"],
  ["ticker", "Ticker (raiz)"],
  ["segmento_listagem", "Segmento de listagem"],
  ["setor_atividade", "Setor (CVM)"],
  ["setor_b3", "Setor (B3)"],
  ["situacao", "Situação"],
  ["controle_acionario", "Controle acionário"],
  ["uf", "UF"],
  ["municipio", "Município"],
  ["dt_registro", "Registro na CVM"],
  ["dt_listagem", "Listagem na B3"],
];

export function Ficha({ cd_cvm }: { cd_cvm: number }) {
  const resp = useDados(() => api.empresa(cd_cvm), [cd_cvm]);
  const meta = useDados(() => api.classes());

  if (resp.carregando) return <Carregando oque={`companhia ${cd_cvm}`} />;
  if (resp.erro) return <Erro mensagem={resp.erro} />;
  const e = resp.dados!.dados;

  const classe = (meta.dados?.dados ?? []).find((c) => c.chave === "empresa");
  const porAtributo = e.proveniencia.por_atributo ?? {};

  return (
    <div className="grid gap-6">
      <nav aria-label="Voltar">
        <a href="#/" className="text-sm underline decoration-dotted">
          ← voltar à busca
        </a>
      </nav>

      <header>
        <h1 className="text-xl font-semibold">
          {e.denom_social ?? `Companhia ${e.cd_cvm}`}
        </h1>
        <p className="text-sm text-tinta-suave mt-1 flex flex-wrap gap-2 items-center">
          {e.listada_b3 ? (
            <>
              <Selo texto={e.segmento_listagem || "básico"} />
              <span className="font-mono">{e.ticker}</span>
              <span>negocia na B3</span>
            </>
          ) : (
            <span>sem registro de negociação na B3</span>
          )}
          {e.proveniencia.publicacao != null && (
            <span>· publicação v{e.proveniencia.publicacao}</span>
          )}
        </p>
        <p className="mt-2">
          <a
            href={`#/empresa/${e.cd_cvm}/demonstracoes`}
            className="text-sm font-medium underline decoration-dotted"
          >
            Demonstrações financeiras →
          </a>
        </p>
      </header>

      <section aria-labelledby="dados-cadastrais">
        <h2 id="dados-cadastrais" className="font-medium mb-3">
          O que o portal sabe
        </h2>
        <Tabela
          legenda="Atributos da companhia e a fonte que venceu cada um"
          colunas={["Atributo", "Valor", "Veio de"]}
        >
          {CAMPOS.map(([campo, rotulo]) => {
            const valor = e[campo];
            const origem = porAtributo[campo as string];
            return (
              <tr key={campo} className="border-b border-borda last:border-0">
                <th scope="row" className="text-left px-3 py-2">
                  {rotulo}
                  <span className="block text-xs text-tinta-suave font-mono">
                    {campo}
                  </span>
                </th>
                <td className="px-3 py-2">
                  {valor === null || valor === undefined || valor === "" ? (
                    <span className="text-tinta-suave">—</span>
                  ) : typeof valor === "boolean" ? (
                    valor ? "sim" : "não"
                  ) : (
                    String(valor)
                  )}
                </td>
                <td className="px-3 py-2 text-xs">
                  <Origem
                    atributo={campo as string}
                    origem={origem}
                    classe={classe}
                  />
                </td>
              </tr>
            );
          })}
        </Tabela>
      </section>

      <section
        aria-labelledby="proveniencia"
        className="border border-borda rounded bg-white p-4"
      >
        <h2 id="proveniencia" className="font-medium mb-2">
          Proveniência
        </h2>
        <dl className="text-sm grid sm:grid-cols-2 gap-x-6 gap-y-1">
          {e.proveniencia.fonte && (
            <div>
              <dt className="text-tinta-suave inline">Fonte da linha: </dt>
              <dd className="inline font-mono text-xs">{e.proveniencia.fonte}</dd>
            </div>
          )}
          {e.proveniencia.dt_captura && (
            <div>
              <dt className="text-tinta-suave inline">Capturado em: </dt>
              <dd className="inline">{e.proveniencia.dt_captura}</dd>
            </div>
          )}
          {e.proveniencia.publicacao != null && (
            <div>
              <dt className="text-tinta-suave inline">Publicação: </dt>
              <dd className="inline">v{e.proveniencia.publicacao}</dd>
            </div>
          )}
          {e.proveniencia.url && (
            <div className="sm:col-span-2">
              <dt className="text-tinta-suave inline">Arquivo oficial: </dt>
              <dd className="inline font-mono text-xs break-all">
                {e.proveniencia.url}
              </dd>
            </div>
          )}
        </dl>
        {classe && classe.resolucao === "precedencia" && (
          <p className="text-xs text-tinta-suave mt-3">
            A classe <strong>empresa</strong> é alimentada por{" "}
            {classe.fontes.join(", ")}. Onde as fontes discordam, vence a
            primeira da precedência declarada —{" "}
            <span className="font-mono">{classe.precedencia.join(" › ")}</span>{" "}
            — salvo atributo com precedência própria, indicada na coluna “Veio
            de”.
          </p>
        )}
      </section>
    </div>
  );
}

/** De onde o atributo veio. Disputado: a fonte que venceu (medida pela vista
 * resolvida) e a ordem declarada que explica por quê. Fonte única declarada:
 * a própria — sem disputa não há coluna de origem para medir. */
function Origem({
  atributo,
  origem,
  classe,
}: {
  atributo: string;
  origem: string | undefined;
  classe: MetaClasse | undefined;
}) {
  const meta = classe?.atributos.find((a) => a.nome === atributo);
  if (origem) {
    const ordem =
      meta && meta.precedencia.length > 0
        ? meta.precedencia
        : (classe?.precedencia ?? []);
    return (
      <>
        <span className="font-mono">{origem}</span>
        {ordem.length > 1 && (
          <span className="block text-tinta-suave">
            precedência: {ordem.join(" › ")}
          </span>
        )}
      </>
    );
  }
  if (meta?.origem === "calculado")
    return <span className="text-tinta-suave">calculado pelo portal</span>;
  if (meta && meta.precedencia.length === 1)
    return (
      <>
        <span className="font-mono">{meta.precedencia[0]}</span>
        <span className="block text-tinta-suave">fonte única declarada</span>
      </>
    );
  return <span className="text-tinta-suave">—</span>;
}
