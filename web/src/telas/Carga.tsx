import { useState } from "react";
import { api, type RelatorioCarga } from "../api";
import { Carregando, Erro, Selo, Tabela, Vazio, useDados } from "../ui";
import { Serie } from "../objetos";

/** Nulo não é zero.
 *
 * Bytes de disco só o Postgres responde; no DuckDB local a medida não existe.
 * Imprimir "0 MB" ali faria falta de medida parecer ausência de custo, que é
 * exatamente a leitura errada. O traço diz "não medido". */
function ouTraco(valor: number | null | undefined, formatar: (n: number) => string) {
  return valor === null || valor === undefined ? (
    <span className="text-tinta-suave" title="não medido">
      —
    </span>
  ) : (
    formatar(valor)
  );
}

const mb = (n: number) => `${(n / 1e6).toFixed(1)} MB`;
const gb = (n: number) => `${n.toFixed(2)} GB`;
const usd = (n: number) => `US$ ${n.toFixed(2)}`;
const brl = (n: number) => `R$ ${n.toFixed(2)}`;
const num = (n: number) => n.toLocaleString("pt-BR");
const seg = (n: number) => `${(n / 1000).toFixed(1)} s`;

function Cartao(props: { rotulo: string; valor: React.ReactNode; nota?: string }) {
  return (
    <div className="border border-borda rounded p-3">
      <p className="text-xs text-tinta-suave">{props.rotulo}</p>
      <p className="text-lg font-medium mt-1">{props.valor}</p>
      {props.nota && <p className="text-xs text-tinta-suave mt-1">{props.nota}</p>}
    </div>
  );
}

export function Carga() {
  const [dataset, setDataset] = useState("");
  const painel = useDados(() => api.carga(dataset || undefined), [dataset]);
  const datasets = useDados(() => api.datasets());

  if (painel.carregando) return <Carregando oque="relatório de carga" />;
  if (painel.erro) return <Erro mensagem={painel.erro} />;
  if (!painel.dados) return null;

  const { dados, resumo, tarifa, medicao } = painel.dados;

  return (
    <div className="grid gap-6">
      <section aria-labelledby="agora">
        <h2 id="agora" className="font-medium mb-3">
          Onde o hub está agora
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Cartao
            rotulo="Ocupado em disco"
            valor={ouTraco(resumo.gb_armazenados, gb)}
            nota="banco inteiro, com índices"
          />
          <Cartao
            rotulo="Custo por mês"
            valor={ouTraco(resumo.custo_mes_usd, usd)}
            // Faltam duas coisas diferentes e a nota tem de dizer qual: sem
            // medida de disco não há custo nenhum; com disco e sem câmbio há
            // dólar mas não real. Culpar o câmbio nos dois casos manda o
            // operador procurar no lugar errado.
            nota={
              resumo.custo_mes_brl !== null
                ? `${brl(resumo.custo_mes_brl)} — câmbio ${resumo.cambio_usd_brl}`
                : resumo.custo_mes_usd === null
                  ? "falta a medida de disco (só o Postgres a fornece)"
                  : "sem câmbio carregado para converter em real"
            }
          />
          <Cartao
            rotulo="Crescimento"
            valor={ouTraco(resumo.crescimento_gb_dia, (n) => `${n.toFixed(3)} GB/dia`)}
            nota="entre as duas últimas cargas do mesmo mapeamento"
          />
          <Cartao
            rotulo="Projeção 12 meses"
            valor={ouTraco(resumo.projecao_12m_gb, gb)}
            nota={
              resumo.projecao_12m_usd !== null
                ? `${usd(resumo.projecao_12m_usd)} por mês ao fim do período`
                : "precisa de duas cargas para projetar"
            }
          />
        </div>

        {/* Sem isto, o custo estimado se apresenta como medida — e é a
            diferença entre um número que decide e um número que engana. */}
        <div className="mt-3 border border-borda rounded p-3 text-sm grid gap-1">
          <p>
            <strong>Físico:</strong> {medicao.fisico}.
          </p>
          <p>
            <strong>Financeiro:</strong> {medicao.financeiro}
            {tarifa && (
              <>
                {" "}— {usd(Number(tarifa.preco_usd))} por {tarifa.unidade}, vigente
                desde {tarifa.vigente_desde}
                {tarifa.fonte && <> ({tarifa.fonte})</>}.
              </>
            )}
          </p>
          <p className="text-tinta-suave">{medicao.nao_coberto}</p>
        </div>
      </section>

      <section aria-labelledby="tempo" className="grid gap-3">
        <h2 id="tempo" className="font-medium">
          Como isso vem andando
        </h2>
        {/* Da carga mais antiga para a mais recente: `dados` vem em ordem
            decrescente, que é a certa para a tabela e a errada para o
            gráfico. */}
        <div className="grid gap-3 sm:grid-cols-3">
          {(() => {
            const cronologico = [...dados].reverse();
            const pontos = (campo: keyof RelatorioCarga) =>
              cronologico.map((r) => ({
                rotulo: r.gerado_em,
                valor: r[campo] as number | null,
              }));
            return (
              <>
                <Serie
                  titulo="Disco ocupado"
                  pontos={pontos("gb_armazenados")}
                  formatar={gb}
                  nota="banco inteiro ao fim de cada carga"
                />
                <Serie
                  titulo="Custo por mês"
                  pontos={pontos("custo_mes_usd")}
                  formatar={usd}
                  nota="tarifa vigente sobre o disco medido"
                />
                <Serie
                  titulo="Duração da carga"
                  pontos={pontos("duracao_ms")}
                  formatar={seg}
                  nota="do download à publicação"
                />
              </>
            );
          })()}
        </div>
      </section>

      <section aria-labelledby="hist">
        <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
          <h2 id="hist" className="font-medium">
            Carga a carga
          </h2>
          <label className="text-sm flex items-center gap-2">
            Mapeamento
            <select
              className="border border-borda rounded px-2 py-1"
              value={dataset}
              onChange={(e) => setDataset(e.target.value)}
            >
              <option value="">todos</option>
              {datasets.dados?.dados.map((d) => (
                <option key={d.chave} value={d.chave}>
                  {d.chave}
                </option>
              ))}
            </select>
          </label>
        </div>

        {dados.length === 0 ? (
          <Vazio
            titulo="Nenhuma carga relatada ainda"
            dica="O relatório é gravado ao fim de cada execução. Rode uma ingestão para vê-lo aqui."
          />
        ) : (
          <Tabela
            legenda="Relatório por execução: linhas, bytes e custo"
            colunas={[
              "Quando", "Mapeamento", "Janela", "Status", "Linhas",
              "Na classe", "Bronze +", "Disco", "Disco +", "Duração", "Custo/mês",
            ]}
          >
            {dados.map((r: RelatorioCarga) => (
              <tr key={r.id} className="border-t border-borda">
                <td className="px-3 py-2 whitespace-nowrap">
                  {new Date(r.gerado_em).toLocaleString("pt-BR")}
                </td>
                <td className="px-3 py-2">{r.dataset_chave}</td>
                <td className="px-3 py-2">{r.janela}</td>
                <td className="px-3 py-2">
                  <Selo texto={r.status} />
                </td>
                <td className="px-3 py-2 text-right">{ouTraco(r.linhas_carregadas, num)}</td>
                <td className="px-3 py-2 text-right">{ouTraco(r.linhas_classe, num)}</td>
                <td className="px-3 py-2 text-right">{ouTraco(r.bytes_capturados, mb)}</td>
                <td className="px-3 py-2 text-right">{ouTraco(r.bytes_banco, mb)}</td>
                <td className="px-3 py-2 text-right">{ouTraco(r.delta_bytes_banco, mb)}</td>
                <td className="px-3 py-2 text-right">{ouTraco(r.duracao_ms, seg)}</td>
                <td className="px-3 py-2 text-right">{ouTraco(r.custo_mes_usd, usd)}</td>
              </tr>
            ))}
          </Tabela>
        )}
      </section>
    </div>
  );
}
