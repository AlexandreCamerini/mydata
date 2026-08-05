// A tela que faltava. `negociacao_b3` é a maior classe do sistema — 384.875
// linhas em produção, das quais 329.262 contratos de opção — e não tinha
// nenhuma representação visual: busca por `ticker_objeto`, `hv21` ou
// `volatilidade` em `web/src/` não retornava nada.
//
// O que ela mostra é a comparação que a camada de opções existe para fazer:
// a volatilidade **implícita** do contrato ao lado da **realizada** do papel.
// Uma é o que o mercado está cobrando; a outra é o que o papel de fato fez.
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Cotacao, type Opcao, type Vencimento } from "./api";

const ALTURA_LINHA = 34;
const FOLGA = 8;

/** Nulo é fato, não zero.
 *
 * Cerca de 10% dos contratos não têm implícita porque o prêmio ficou fora do
 * que o modelo alcança — fechamento ilíquido de horas antes, às vezes abaixo
 * do valor intrínseco. Um traço mudo faria isso parecer defeito da tela. */
function ouNulo(
  valor: number | null | undefined,
  formatar: (n: number) => string,
  motivo = "sem valor",
) {
  if (valor === null || valor === undefined) {
    return (
      <span className="text-tinta-suave" title={motivo}>
        —
      </span>
    );
  }
  return <>{formatar(valor)}</>;
}

const brl = (n: number) => n.toFixed(2);
const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
const num3 = (n: number) => n.toFixed(3);
const int = (n: number) => n.toLocaleString("pt-BR");

export function Negociacao({ ticker: inicial }: { ticker: string }) {
  const [ticker, setTicker] = useState(inicial);
  const [busca, setBusca] = useState(inicial);
  const [vencs, setVencs] = useState<Vencimento[] | null>(null);
  const [venc, setVenc] = useState<string>("");
  const [tipo, setTipo] = useState<"" | "CALL" | "PUT">("");
  const [contratos, setContratos] = useState<Opcao[] | null>(null);
  const [cotacao, setCotacao] = useState<Cotacao | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(false);

  useEffect(() => {
    let vivo = true;
    setErro(null);
    setVencs(null);
    setContratos(null);
    Promise.all([
      api.vencimentos(ticker).then((r) => r.dados),
      api.cotacoes(ticker).then((r) => r.dados.at(-1) ?? null),
    ])
      .then(([v, c]) => {
        if (!vivo) return;
        setVencs(v);
        setCotacao(c);
        // Não o primeiro vencimento: o primeiro com prazo de verdade.
        //
        // A cadeia costuma abrir com o vencimento do próprio pregão, e ali o
        // prazo é zero — não existe sigma que resolva Black-Scholes sem tempo,
        // então *toda* implícita sai nula. A tela abria mostrando 43 contratos
        // e nenhuma volatilidade, o que parece defeito e é aritmética.
        const comPrazo = c
          ? v.find((x) => x.dt_vencimento > c.dt_pregao)
          : undefined;
        setVenc((comPrazo ?? v[0])?.dt_vencimento ?? "");
      })
      .catch((e) => vivo && setErro((e as Error).message));
    return () => {
      vivo = false;
    };
  }, [ticker]);

  useEffect(() => {
    if (!venc) return;
    let vivo = true;
    setCarregando(true);
    api
      .opcoes(ticker, { vencimento: venc, tipo: tipo || undefined })
      .then((r) => vivo && setContratos(r.dados))
      .catch((e) => vivo && setErro((e as Error).message))
      .finally(() => vivo && setCarregando(false));
    return () => {
      vivo = false;
    };
  }, [ticker, venc, tipo]);

  const comIV = useMemo(
    () => (contratos ?? []).filter((o) => o.volatilidade_implicita !== null),
    [contratos],
  );

  return (
    <div className="grid gap-6">
      <section aria-labelledby="t">
        <h1 id="t" className="text-2xl font-semibold">
          Negociação na B3
        </h1>
        <p className="text-sm text-tinta-suave mt-1">
          Cadeia de opções com volatilidade implícita e gregas, do pregão
          publicado. Implícita é o que o mercado cobra; realizada é o que o
          papel fez.
        </p>

        <form
          className="mt-4 flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            const t = busca.trim().toUpperCase();
            if (t) {
              setTicker(t);
              window.location.hash = `#/negociacao/${t}`;
            }
          }}
        >
          <label className="text-sm">
            <span className="block font-medium mb-1">Ativo-objeto</span>
            <input
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
              placeholder="PETR4"
              className="border border-borda rounded px-2 py-1 w-36 uppercase"
            />
          </label>
          <button
            type="submit"
            className="bg-acento text-papel rounded px-3 py-1.5 text-sm hover:opacity-90"
          >
            Ver cadeia
          </button>
        </form>
      </section>

      {erro && (
        <div role="alert" className="border border-erro bg-red-50 text-erro rounded p-3 text-sm">
          {erro}
        </div>
      )}

      {cotacao && (
        <section
          aria-labelledby="papel"
          className="grid gap-3 sm:grid-cols-4 border border-borda rounded p-3 bg-superficie"
        >
          <h2 id="papel" className="sr-only">
            O papel
          </h2>
          <Cartao rotulo="Pregão" valor={cotacao.dt_pregao} />
          <Cartao
            rotulo="Fechamento"
            valor={ouNulo(cotacao.preco_fechamento, brl)}
          />
          <Cartao
            rotulo="Volatilidade realizada (21)"
            valor={ouNulo(
              cotacao.hv21,
              pct,
              "precisa de 21 pregões carregados",
            )}
          />
          <Cartao
            rotulo="Volume"
            valor={ouNulo(cotacao.volume_financeiro, (n) =>
              `R$ ${(n / 1e6).toFixed(1)} mi`,
            )}
          />
        </section>
      )}

      {vencs && vencs.length > 0 && (
        <section aria-labelledby="venc" className="grid gap-2">
          <h2 id="venc" className="font-medium">
            Vencimentos
          </h2>
          <div className="flex flex-wrap gap-2">
            {vencs.map((v) => (
              <button
                key={v.dt_vencimento}
                onClick={() => setVenc(v.dt_vencimento)}
                aria-pressed={venc === v.dt_vencimento}
                className={`text-sm rounded border px-2.5 py-1 ${
                  venc === v.dt_vencimento
                    ? "border-acento bg-acento-suave text-acento font-medium"
                    : "border-borda hover:bg-acento-suave"
                }`}
              >
                {v.dt_vencimento}
                <span className="text-tinta-suave"> · {v.contratos}</span>
              </button>
            ))}
          </div>
          <div className="flex gap-2 mt-1">
            {(["", "CALL", "PUT"] as const).map((t) => (
              <button
                key={t || "todos"}
                onClick={() => setTipo(t)}
                aria-pressed={tipo === t}
                className={`text-xs rounded border px-2 py-1 ${
                  tipo === t
                    ? "border-acento bg-acento-suave text-acento"
                    : "border-borda"
                }`}
              >
                {t || "todos"}
              </button>
            ))}
          </div>
        </section>
      )}

      {vencs?.length === 0 && (
        <div className="py-10 text-center border border-dashed border-borda rounded">
          <p className="font-medium">{ticker} não tem opções no pregão publicado</p>
          <p className="text-sm text-tinta-suave mt-1">
            Nem todo papel tem cadeia. Tente PETR4, VALE3 ou ABCB4.
          </p>
        </div>
      )}

      {contratos && contratos.length > 0 && (
        <section aria-labelledby="cadeia" className="grid gap-2">
          <div className="flex items-baseline justify-between flex-wrap gap-2">
            <h2 id="cadeia" className="font-medium">
              Cadeia
            </h2>
            <p className="text-xs text-tinta-suave">
              {contratos.length} contratos · {comIV.length} com implícita
              {comIV.length < contratos.length && (
                <>
                  {" "}
                  · {contratos.length - comIV.length} sem, porque o prêmio ficou
                  fora do alcance do modelo
                </>
              )}
            </p>
          </div>
          <GridCadeia linhas={contratos} carregando={carregando} />
          <Proveniencia opcao={contratos[0]} />
        </section>
      )}
    </div>
  );
}

function Cartao({ rotulo, valor }: { rotulo: string; valor: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs text-tinta-suave">{rotulo}</p>
      <p className="text-lg numero mt-0.5">{valor}</p>
    </div>
  );
}

/** Grid virtualizado.
 *
 * Nasce virtualizado porque a auditoria mediu que nenhuma tabela da interface
 * era, e um pregão tem 15 mil linhas — a cadeia da PETR4 sozinha tem 748
 * contratos. Renderizar tudo funcionava só enquanto nenhuma tela mostrava mais
 * que dezenas de linhas.
 *
 * A janela é calculada do scroll: só as linhas visíveis (mais folga) existem
 * no DOM, e um espaçador de altura total mantém a barra de rolagem honesta. */
function GridCadeia({
  linhas,
  carregando,
}: {
  linhas: Opcao[];
  carregando: boolean;
}) {
  const caixa = useRef<HTMLDivElement>(null);
  const [topo, setTopo] = useState(0);
  const [altura, setAltura] = useState(480);

  useEffect(() => {
    const el = caixa.current;
    if (!el) return;
    const medir = () => setAltura(el.clientHeight);
    medir();
    const ro = new ResizeObserver(medir);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const primeira = Math.max(0, Math.floor(topo / ALTURA_LINHA) - FOLGA);
  const quantas = Math.ceil(altura / ALTURA_LINHA) + FOLGA * 2;
  const visiveis = linhas.slice(primeira, primeira + quantas);

  return (
    <div
      ref={caixa}
      onScroll={(e) => setTopo(e.currentTarget.scrollTop)}
      tabIndex={0}
      role="region"
      aria-label="Cadeia de opções, rolável"
      className={`border border-borda rounded overflow-auto bg-superficie ${
        carregando ? "opacity-60" : ""
      }`}
      style={{ maxHeight: 480 }}
    >
      <table className="w-full text-sm border-collapse">
        <caption className="sr-only">
          Contratos de opção com strike, prêmio, volatilidade implícita e gregas
        </caption>
        <thead className="sticky top-0 bg-superficie z-10">
          <tr className="text-left border-b border-borda">
            {[
              "Contrato",
              "Tipo",
              "Strike",
              "Prêmio",
              "Implícita",
              "Realizada",
              "Delta",
              "Gama",
              "Theta",
              "Negócios",
            ].map((c) => (
              <th key={c} scope="col" className="px-2 py-1.5 font-medium whitespace-nowrap">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {primeira > 0 && (
            <tr aria-hidden="true">
              <td colSpan={10} style={{ height: primeira * ALTURA_LINHA }} />
            </tr>
          )}
          {visiveis.map((o) => (
            <tr key={o.contrato} className="border-b border-borda/60">
              <td className="px-2 numero whitespace-nowrap">{o.contrato}</td>
              <td className="px-2">{o.tipo ?? "—"}</td>
              <td className="px-2 numero text-right">{ouNulo(o.strike, brl)}</td>
              <td className="px-2 numero text-right">{ouNulo(o.premio, brl)}</td>
              <td className="px-2 numero text-right">
                {ouNulo(
                  o.volatilidade_implicita,
                  pct,
                  "prêmio fora do alcance do modelo — sem sigma que resolva",
                )}
              </td>
              <td className="px-2 numero text-right text-tinta-suave">
                {ouNulo(o.hv21_objeto, pct, "precisa de 21 pregões carregados")}
              </td>
              <td className="px-2 numero text-right">{ouNulo(o.delta, num3)}</td>
              <td className="px-2 numero text-right">{ouNulo(o.gamma, num3)}</td>
              <td className="px-2 numero text-right">{ouNulo(o.theta, num3)}</td>
              <td className="px-2 numero text-right">
                {ouNulo(o.total_negocios, int)}
              </td>
            </tr>
          ))}
          {primeira + quantas < linhas.length && (
            <tr aria-hidden="true">
              <td
                colSpan={10}
                style={{
                  height: (linhas.length - primeira - quantas) * ALTURA_LINHA,
                }}
              />
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/** A promessa central do produto parava um clique antes do fim: toda resposta
 * carrega `proveniencia.arquivo_em`, um caminho para o ZIP como a fonte
 * publicou, e nenhuma tela o alcançava. */
function Proveniencia({ opcao }: { opcao: Opcao }) {
  const p = opcao.proveniencia;
  if (!p) return null;
  return (
    <details className="text-xs border border-borda rounded p-2 bg-superficie">
      <summary className="cursor-pointer">De onde vem este número</summary>
      <dl className="mt-2 grid gap-1 sm:grid-cols-2">
        <div>
          <dt className="text-tinta-suave">Arquivo</dt>
          <dd className="numero">{p.arquivo}</dd>
        </div>
        <div>
          <dt className="text-tinta-suave">Capturado em</dt>
          <dd className="numero">{p.dt_captura?.slice(0, 19).replace("T", " ")}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-tinta-suave">sha256</dt>
          <dd className="numero break-all">{p.sha256}</dd>
        </div>
      </dl>
      {p.arquivo_em && (
        <p className="mt-2">
          <a href={p.arquivo_em} className="text-acento underline">
            Baixar o arquivo original
          </a>
          <span className="text-tinta-suave">
            {" "}
            — confira o sha256 e verá byte a byte o que a B3 publicou.
          </span>
        </p>
      )}
    </details>
  );
}
