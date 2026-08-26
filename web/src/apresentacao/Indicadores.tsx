// Os indicadores calculados — que existiam, tinham fórmula declarada e
// colunas de origem, e nenhuma tela chamava.
//
// O que os diferencia de qualquer site de fundamentos: a fórmula fica à
// vista e diz de quais contas o número saiu. Um indicador que não consegue
// declarar suas colunas de origem é recusado na validação, não na carga —
// então o que aparece aqui é sempre rastreável até a conta.
import { useState } from "react";
import { Carregando, Erro, Selecao, Tabela, Vazio, useDados } from "../ui";
import { api } from "./api";

const fmt = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });

export function Indicadores({ cd_cvm }: { cd_cvm: number }) {
  const [consolidado, setConsolidado] = useState(true);
  const { dados, erro, carregando } = useDados(
    () => api.metricas(cd_cvm, consolidado),
    [cd_cvm, consolidado],
  );

  if (carregando && !dados) return <Carregando oque="os indicadores" />;
  if (erro) return <Erro mensagem={erro} />;

  const periodos = dados?.dados ?? [];
  // As definições vêm repetidas em cada período; a primeira basta para montar
  // a legenda das fórmulas.
  const definicoes = periodos[0]?.definicoes ?? {};
  const chaves = Object.keys(definicoes);

  return (
    <div className="grid gap-4">
      <header className="grid gap-1">
        <p className="text-xs text-tinta-suave">
          <a href={`#/empresa/${cd_cvm}`} className="underline decoration-dotted">
            ← Companhia {cd_cvm}
          </a>
        </p>
        <h1 className="text-xl font-semibold">Indicadores</h1>
        <p className="text-sm text-tinta-suave max-w-2xl">
          Calculados sobre as contas publicadas. A fórmula de cada um está
          abaixo da tabela, com as contas que ela usa — o número é rastreável
          até a linha do documento oficial.
        </p>
      </header>

      <Selecao
        rotulo="Escopo"
        valor={consolidado ? "con" : "ind"}
        opcoes={[
          { valor: "con", rotulo: "Consolidado" },
          { valor: "ind", rotulo: "Individual" },
        ]}
        aoMudar={(v) => setConsolidado(v === "con")}
      />

      {periodos.length === 0 ? (
        <Vazio
          titulo="Nenhum indicador calculável"
          dica="As contas que as fórmulas usam não estão publicadas para este escopo."
        />
      ) : (
        <>
          <Tabela
            legenda="Indicadores por período de referência"
            colunas={["Período", "Documento", ...chaves.map((k) => definicoes[k].nome)]}
          >
            {periodos.map((p) => (
              <tr
                key={`${p.dt_refer}-${p.tipo_doc}`}
                className="border-b border-borda last:border-0"
              >
                <th scope="row" className="text-left px-3 py-1.5">
                  {p.dt_refer}
                </th>
                <td className="px-3 py-1.5 text-xs">{p.tipo_doc}</td>
                {chaves.map((k) => (
                  <td key={k} className="px-3 py-1.5 text-right tabular-nums">
                    {p.metricas[k] != null ? fmt.format(p.metricas[k]) : "—"}
                  </td>
                ))}
              </tr>
            ))}
          </Tabela>

          <section aria-labelledby="formulas" className="grid gap-2">
            <h2 id="formulas" className="font-medium text-sm">
              De onde cada número saiu
            </h2>
            <dl className="grid gap-2">
              {chaves.map((k) => (
                <div
                  key={k}
                  className="border border-borda rounded bg-superficie px-3 py-2 grid gap-1"
                >
                  <dt className="font-medium text-sm">
                    {definicoes[k].nome}
                    {definicoes[k].unidade && (
                      <span className="text-tinta-suave font-normal">
                        {" "}
                        ({definicoes[k].unidade})
                      </span>
                    )}
                  </dt>
                  <dd className="text-xs text-tinta-suave grid gap-1">
                    {definicoes[k].descricao && <span>{definicoes[k].descricao}</span>}
                    <span>
                      Contas usadas:{" "}
                      <code className="font-mono">
                        {definicoes[k].contas.join(", ")}
                      </code>
                    </span>
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        </>
      )}
    </div>
  );
}
