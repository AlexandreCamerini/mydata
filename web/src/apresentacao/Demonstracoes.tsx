// As demonstrações: balanço, resultado e fluxo em série de anos, e o
// trimestre isolado do ITR que só existia em JSON.
//
// Três armadilhas do dado ficam VISÍVEIS, nunca corrigidas em silêncio:
// - consolidado × individual é escolha do usuário, não default escondido;
// - reapresentação: o ano diz qual versão do documento está no ar;
// - escala: a CVM publica em milhares; a tela mostra reais (vl_conta_norm)
//   com o valor original do arquivo ao lado, não no lugar.
import { useEffect, useId, useState } from "react";
import { Carregando, Erro, Selecao, Selo, Tabela, Vazio, useDados } from "../ui";
import { api, type Conta, type Trimestre } from "./api";

const GRUPOS = [
  { valor: "BPA", rotulo: "Balanço — ativo (BPA)" },
  { valor: "BPP", rotulo: "Balanço — passivo (BPP)" },
  { valor: "DRE", rotulo: "Resultado (DRE)" },
  { valor: "DFC_MI", rotulo: "Fluxo de caixa — indireto (DFC_MI)" },
  { valor: "DFC_MD", rotulo: "Fluxo de caixa — direto (DFC_MD)" },
  { valor: "DVA", rotulo: "Valor adicionado (DVA)" },
  { valor: "DRA", rotulo: "Resultado abrangente (DRA)" },
];

const fmtReais = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });

function ano(dt_refer: string): string {
  return dt_refer.slice(0, 4);
}

/** A cadeia até o arquivo oficial: quais capturas originaram esta série.
 *
 * O número na tabela acima é derivado; este painel é o que permite conferi-lo
 * contra o que a fonte publicou. Uma captura costuma cobrir vários anos — o
 * ZIP anual da CVM traz o exercício e os comparativos —, então as linhas são
 * agrupadas por digital, e não repetidas por ano. */
function ProvaDoOriginal({ serie }: { serie: Conta[] }) {
  const porHash = new Map<string, { anos: string[]; p: Conta["proveniencia"] }>();
  for (const c of serie) {
    const hash = c.proveniencia?.sha256;
    if (!hash) continue;
    const atual = porHash.get(hash) ?? { anos: [], p: c.proveniencia };
    atual.anos.push(ano(c.dt_refer));
    porHash.set(hash, atual);
  }
  const capturas = [...porHash.entries()];
  if (capturas.length === 0) return null;

  return (
    <div>
      <h3 className="font-medium text-sm mb-2">O arquivo original</h3>
      <p className="text-xs text-tinta-suave mb-2">
        Cada número acima foi derivado de um arquivo que a fonte publicou e que
        está guardado aqui intacto. A digital SHA-256 é o que permite conferir
        que o guardado é byte a byte o que ela publicou.
      </p>
      <Tabela
        legenda="Capturas que originaram a série, com digital do arquivo oficial"
        colunas={["Anos", "Arquivo", "SHA-256", "Capturado em", "Publicação"]}
      >
        {capturas.map(([hash, { anos, p }]) => (
          <tr key={hash} className="border-b border-borda last:border-0">
            <th scope="row" className="text-left px-3 py-1.5 whitespace-nowrap">
              {[...new Set(anos)].sort().join(", ")}
            </th>
            <td className="px-3 py-1.5 text-xs">
              {p?.url ? (
                <a
                  href={p.url}
                  className="underline decoration-dotted"
                  rel="noreferrer noopener"
                >
                  {p?.arquivo ?? p.url}
                </a>
              ) : (
                (p?.arquivo ?? "—")
              )}
            </td>
            <td className="px-3 py-1.5">
              <code className="text-[11px] break-all">{hash}</code>
            </td>
            <td className="px-3 py-1.5 text-xs whitespace-nowrap">
              {p?.dt_captura?.slice(0, 19).replace("T", " ") ?? "—"}
            </td>
            <td className="px-3 py-1.5 text-xs">
              {p?.publicacao != null ? `v${p.publicacao}` : "—"}
            </td>
          </tr>
        ))}
      </Tabela>
    </div>
  );
}

export function Demonstracoes({
  cd_cvm,
  grupoInicial,
}: {
  cd_cvm: number;
  grupoInicial?: string;
}) {
  const empresa = useDados(() => api.empresa(cd_cvm), [cd_cvm]);
  // O grupo vem do endereço quando ele o traz. Trocar de grupo reescreve o
  // endereço, e não só o estado: é o que torna o recorte citável e o que faz
  // o botão "voltar" do navegador significar alguma coisa aqui.
  const [grupo, setGrupoEstado] = useState(
    (grupoInicial ?? "BPA").toUpperCase(),
  );
  function setGrupo(novo: string) {
    setGrupoEstado(novo);
    window.location.hash = `#/empresa/${cd_cvm}/demonstracoes/${novo}`;
  }
  useEffect(() => {
    if (grupoInicial && grupoInicial.toUpperCase() !== grupo) {
      setGrupoEstado(grupoInicial.toUpperCase());
    }
  }, [grupoInicial]);
  const [consolidado, setConsolidado] = useState(true);
  const [linhas, setLinhas] = useState<Conta[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [contaAberta, setContaAberta] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    setLinhas(null);
    setErro(null);
    api
      .demonstracoes(cd_cvm, { tipo: "DFP", grupo, consolidado })
      .then((d) => vivo && setLinhas(d))
      .catch((e) => vivo && setErro((e as Error).message));
    return () => {
      vivo = false;
    };
  }, [cd_cvm, grupo, consolidado]);

  const nome = empresa.dados?.dados.denom_social ?? `Companhia ${cd_cvm}`;

  // Pivô: anos nas colunas, contas nas linhas. A versão do documento por ano
  // vem junto — é ela que denuncia reapresentação.
  const anos = [...new Set((linhas ?? []).map((l) => ano(l.dt_refer)))].sort();
  const versaoPorAno = new Map<string, number>();
  for (const l of linhas ?? []) {
    const a = ano(l.dt_refer);
    versaoPorAno.set(a, Math.max(versaoPorAno.get(a) ?? 0, l.versao));
  }
  const contas = new Map<string, { ds: string | null; porAno: Map<string, Conta> }>();
  for (const l of linhas ?? []) {
    if (!contas.has(l.cd_conta))
      contas.set(l.cd_conta, { ds: l.ds_conta, porAno: new Map() });
    contas.get(l.cd_conta)!.porAno.set(ano(l.dt_refer), l);
  }
  const ordenadas = [...contas.entries()].sort(([a], [b]) =>
    a.localeCompare(b, "pt-BR", { numeric: true }),
  );

  return (
    <div className="grid gap-5">
      <nav aria-label="Voltar">
        <a
          href={`#/empresa/${cd_cvm}`}
          className="text-sm underline decoration-dotted"
        >
          ← a companhia
        </a>
      </nav>

      <header>
        <h1 className="text-xl font-semibold">{nome}</h1>
        <p className="text-sm text-tinta-suave">
          Demonstrações anuais (DFP), valores em reais — a CVM publica em
          milhares; o original de cada conta fica disponível ao abri-la.
        </p>
      </header>

      <section
        aria-labelledby="recorte"
        className="border border-borda rounded bg-superficie p-4 grid gap-x-6 sm:grid-cols-[minmax(0,320px)_auto] items-end"
      >
        <h2 id="recorte" className="sr-only">
          Recorte da demonstração
        </h2>
        <Selecao
          rotulo="Demonstração"
          valor={grupo}
          aoMudar={(v) => {
            setGrupo(v);
            setContaAberta(null);
          }}
          opcoes={GRUPOS}
        />
        <EscolhaConsolidado valor={consolidado} aoMudar={(v) => {
          setConsolidado(v);
          setContaAberta(null);
        }} />
      </section>

      {erro && <Erro mensagem={erro} />}
      {!linhas && !erro && <Carregando oque="demonstrações" />}
      {linhas && linhas.length === 0 && (
        <Vazio
          titulo="Nada publicado neste recorte"
          dica="Troque a demonstração ou alterne consolidado/individual — nem toda companhia publica os dois."
        />
      )}

      {linhas && linhas.length > 0 && (
        <>
          {[...versaoPorAno.values()].some((v) => v > 1) && (
            <p className="text-xs text-tinta-suave">
              Ano com <Selo texto={`v2+`} /> foi <strong>reapresentado</strong>:
              a coluna diz qual versão do documento está no ar — a anterior não
              é apagada, deixa de ser a última.
            </p>
          )}
          <Tabela
            legenda={`${grupo} de ${nome}, ${consolidado ? "consolidado" : "individual"}, por ano`}
            colunas={[
              "Conta",
              ...anos.map((a) => {
                const v = versaoPorAno.get(a) ?? 1;
                return v > 1 ? `${a} · v${v}` : a;
              }),
            ]}
          >
            {ordenadas.map(([cd, info]) => (
              <tr
                key={cd}
                className="border-b border-borda last:border-0 align-top"
              >
                <th scope="row" className="text-left px-3 py-1.5">
                  <button
                    onClick={() =>
                      setContaAberta(contaAberta === cd ? null : cd)
                    }
                    aria-expanded={contaAberta === cd}
                    className="text-left underline decoration-dotted"
                  >
                    <span className="font-mono text-xs">{cd}</span>{" "}
                    <span className="text-xs">{info.ds ?? ""}</span>
                  </button>
                </th>
                {anos.map((a) => {
                  const c = info.porAno.get(a);
                  return (
                    <td
                      key={a}
                      className="px-3 py-1.5 text-right tabular-nums text-xs whitespace-nowrap"
                    >
                      {c?.vl_conta_norm != null
                        ? fmtReais.format(c.vl_conta_norm)
                        : "—"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </Tabela>

          {contaAberta && contas.has(contaAberta) && (
            <PainelConta
              cd_cvm={cd_cvm}
              cd_conta={contaAberta}
              ds_conta={contas.get(contaAberta)!.ds}
              serie={anos
                .map((a) => contas.get(contaAberta)!.porAno.get(a))
                .filter((c): c is Conta => Boolean(c))}
              consolidado={consolidado}
            />
          )}
        </>
      )}
    </div>
  );
}

/** Consolidado × individual: os dois existem e dizem coisas diferentes —
 * a escolha é de quem lê, nunca um default silencioso. */
function EscolhaConsolidado({
  valor,
  aoMudar,
}: {
  valor: boolean;
  aoMudar: (v: boolean) => void;
}) {
  const id = useId();
  return (
    <fieldset className="mb-4">
      <legend className="block text-sm font-medium mb-1">
        Escopo dos números
      </legend>
      <div className="flex gap-4">
        <label htmlFor={`${id}-con`} className="inline-flex items-center gap-2 text-sm">
          <input
            id={`${id}-con`}
            type="radio"
            name={id}
            checked={valor}
            onChange={() => aoMudar(true)}
          />
          consolidado (grupo econômico)
        </label>
        <label htmlFor={`${id}-ind`} className="inline-flex items-center gap-2 text-sm">
          <input
            id={`${id}-ind`}
            type="radio"
            name={id}
            checked={!valor}
            onChange={() => aoMudar(false)}
          />
          individual (só a controladora)
        </label>
      </div>
    </fieldset>
  );
}

/** A conta aberta: série no gráfico, valores exatos (reais e original) na
 * tabela, e o trimestre isolado do ITR quando existir. */
function PainelConta({
  cd_cvm,
  cd_conta,
  ds_conta,
  serie,
  consolidado,
}: {
  cd_cvm: number;
  cd_conta: string;
  ds_conta: string | null;
  serie: Conta[];
  consolidado: boolean;
}) {
  const tri = useDados(
    () => api.trimestres(cd_cvm, { conta: cd_conta, consolidado }),
    [cd_cvm, cd_conta, consolidado],
  );
  // O filtro da API é por prefixo (propósito: puxar a subárvore); aqui a
  // conta é uma só.
  const trimestres = (tri.dados?.dados ?? []).filter(
    (t) => t.cd_conta === cd_conta,
  );

  return (
    <section
      aria-labelledby="painel-conta"
      className="border border-borda rounded bg-superficie p-4 grid gap-4"
    >
      <h2 id="painel-conta" className="font-medium">
        <span className="font-mono text-sm">{cd_conta}</span>{" "}
        {ds_conta ?? "(sem descrição)"}
      </h2>

      <GraficoSerie
        titulo={`${cd_conta} ${ds_conta ?? ""}`}
        pontos={serie
          .filter((c) => c.vl_conta_norm != null)
          .map((c) => ({ rotulo: ano(c.dt_refer), valor: c.vl_conta_norm! }))}
      />

      <Tabela
        legenda={`Série anual da conta ${cd_conta}, em reais e no original do arquivo`}
        colunas={["Ano", "Em reais (vl_conta_norm)", "Original do arquivo", "Escala declarada", "Versão"]}
      >
        {serie.map((c) => (
          <tr key={c.dt_refer} className="border-b border-borda last:border-0">
            <th scope="row" className="text-left px-3 py-1.5">
              {ano(c.dt_refer)}
            </th>
            <td className="px-3 py-1.5 text-right tabular-nums">
              {c.vl_conta_norm != null ? fmtReais.format(c.vl_conta_norm) : "—"}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums">
              {c.vl_conta != null ? fmtReais.format(c.vl_conta) : "—"}
            </td>
            <td className="px-3 py-1.5 text-xs">
              {c.escala_moeda ?? "—"}
              {c.moeda && ` · ${c.moeda}`}
            </td>
            <td className="px-3 py-1.5 text-xs">
              v{c.versao}
              {c.versao > 1 && (
                <span className="text-tinta-suave"> · reapresentado</span>
              )}
            </td>
          </tr>
        ))}
      </Tabela>

      <ProvaDoOriginal serie={serie} />

      <div>
        <h3 className="font-medium text-sm mb-2">
          Trimestres isolados (ITR)
        </h3>
        {tri.carregando && <Carregando oque="trimestres" />}
        {tri.erro && <Erro mensagem={tri.erro} />}
        {!tri.carregando && trimestres.length === 0 && (
          <p className="text-sm text-tinta-suave">
            Sem ITR para esta conta — balanço patrimonial não acumula no ano;
            o trimestre isolado só existe para resultado e fluxo.
          </p>
        )}
        {trimestres.length > 0 && (
          <Tabela
            legenda={`Trimestres da conta ${cd_conta}: acumulado publicado e trimestre isolado`}
            colunas={["Trimestre", "Acumulado no ano (publicado)", "Trimestre isolado (derivado)"]}
          >
            {trimestres.map((t: Trimestre) => (
              <tr key={t.dt_refer} className="border-b border-borda last:border-0">
                <th scope="row" className="text-left px-3 py-1.5">
                  {t.dt_refer}
                </th>
                <td className="px-3 py-1.5 text-right tabular-nums">
                  {t.vl_acumulado != null ? fmtReais.format(t.vl_acumulado) : "—"}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">
                  {t.vl_trimestre != null ? fmtReais.format(t.vl_trimestre) : "—"}
                </td>
              </tr>
            ))}
          </Tabela>
        )}
      </div>
    </section>
  );
}

/** Gráfico de linha em SVG puro. A série anual tem meia dúzia de pontos —
 * biblioteca de gráfico custaria mais em bytes do que entrega. Os valores
 * exatos ficam na tabela ao lado; o SVG é a forma, não o registro. */
function GraficoSerie({
  titulo,
  pontos,
}: {
  titulo: string;
  pontos: { rotulo: string; valor: number }[];
}) {
  if (pontos.length < 2) return null;
  const L = 640;
  const A = 200;
  const margem = { esq: 8, dir: 8, topo: 14, base: 26 };
  const valores = pontos.map((p) => p.valor);
  const min = Math.min(...valores, 0);
  const max = Math.max(...valores, 0);
  const amplitude = max - min || 1;
  const x = (i: number) =>
    margem.esq + (i * (L - margem.esq - margem.dir)) / (pontos.length - 1);
  const y = (v: number) =>
    margem.topo + ((max - v) * (A - margem.topo - margem.base)) / amplitude;
  const caminho = pontos
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.valor).toFixed(1)}`)
    .join(" ");
  const fmtCurto = new Intl.NumberFormat("pt-BR", {
    notation: "compact",
    maximumFractionDigits: 1,
  });

  return (
    <figure>
      <svg
        viewBox={`0 0 ${L} ${A}`}
        role="img"
        aria-label={`Série de ${titulo}: ${pontos
          .map((p) => `${p.rotulo} ${fmtCurto.format(p.valor)}`)
          .join(", ")}`}
        className="w-full max-w-2xl border border-borda rounded bg-superficie"
      >
        {min < 0 && max > 0 && (
          <line
            x1={margem.esq}
            x2={L - margem.dir}
            y1={y(0)}
            y2={y(0)}
            stroke="currentColor"
            strokeOpacity="0.2"
            strokeDasharray="4 4"
          />
        )}
        <path d={caminho} fill="none" stroke="currentColor" strokeWidth="2" />
        {pontos.map((p, i) => (
          <g key={p.rotulo}>
            <circle cx={x(i)} cy={y(p.valor)} r="3.5" fill="currentColor" />
            <text
              x={x(i)}
              y={A - 8}
              textAnchor="middle"
              className="text-[11px]"
              fill="currentColor"
            >
              {p.rotulo}
            </text>
            <text
              x={x(i)}
              y={y(p.valor) - 8}
              textAnchor={i === 0 ? "start" : i === pontos.length - 1 ? "end" : "middle"}
              className="text-[10px]"
              fill="currentColor"
              fillOpacity="0.7"
            >
              {fmtCurto.format(p.valor)}
            </text>
          </g>
        ))}
      </svg>
      <figcaption className="text-xs text-tinta-suave mt-1">
        Valores em reais; rótulos abreviados. Os números exatos estão na
        tabela abaixo.
      </figcaption>
    </figure>
  );
}
