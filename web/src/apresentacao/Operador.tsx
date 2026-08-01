// O painel do operador: as três perguntas que a observabilidade já
// instrumentava e só saíam em JSON.
//
// 1. O que está desatualizado — frescor de cada classe contra o SLA dela.
// 2. O que quebrou — execuções com falha ou bloqueio, com a linha do tempo
//    por fase que vivia em log_fase.
// 3. De onde veio este número — a linhagem de um atributo: fontes na ordem
//    de precedência, coluna de origem, regras e capturas.
import { useState } from "react";
import { Botao, Caixa, Carregando, Erro, Selecao, Selo, Tabela, Vazio, useDados } from "../ui";
import { api, type Execucao, type Frescor, type Linhagem } from "./api";

function idade(f: Frescor): string {
  if (f.idade_horas === null) return "sem carga";
  if (f.idade_horas < 1) return `${Math.round(f.idade_horas * 60)} min`;
  if (f.idade_horas < 48) return `${Math.round(f.idade_horas)} h`;
  return `${Math.round(f.idade_horas / 24)} d`;
}

export function Operador() {
  return (
    <div className="grid gap-8">
      <header>
        <h1 className="text-xl font-semibold">Painel do operador</h1>
        <p className="text-sm text-tinta-suave">
          O que está desatualizado, o que quebrou, e de onde veio cada número.
        </p>
      </header>
      <SecaoFrescor />
      <SecaoExecucoes />
      <SecaoLinhagem />
    </div>
  );
}

// --------------------------------------------------------------------------
function SecaoFrescor() {
  const { dados, erro, carregando } = useDados(() => api.frescor());
  const lista = dados?.dados ?? [];
  const atrasadas = lista.filter((f) => f.situacao !== "em_dia");

  return (
    <section aria-labelledby="frescor">
      <h2 id="frescor" className="font-medium mb-1">
        O que está desatualizado
      </h2>
      <p className="text-sm text-tinta-suave mb-3">
        Idade da última publicação de cada classe, contra o SLA que ela
        declara.
      </p>
      {carregando && <Carregando oque="frescor" />}
      {erro && <Erro mensagem={erro} />}
      {dados && (
        <>
          <p role="status" className="text-sm mb-3">
            {atrasadas.length === 0 ? (
              <>Tudo dentro do SLA.</>
            ) : (
              <>
                <strong>{atrasadas.length}</strong>{" "}
                {atrasadas.length === 1 ? "classe precisa" : "classes precisam"}{" "}
                de atenção.
              </>
            )}
          </p>
          <Tabela
            legenda="Frescor por classe de informação"
            colunas={["Classe", "Fontes", "SLA", "Idade", "Situação", "Última falha"]}
          >
            {lista.map((f) => (
              <tr key={f.classe} className="border-b border-borda last:border-0 align-top">
                <th scope="row" className="text-left px-3 py-2">
                  {f.nome}
                  <span className="block text-xs text-tinta-suave font-mono">
                    {f.tabela}
                  </span>
                </th>
                <td className="px-3 py-2 text-xs font-mono">
                  {f.fontes.join(", ") || "—"}
                </td>
                <td className="px-3 py-2 text-xs">
                  {f.sla_horas ? `${f.sla_horas} h` : "sem SLA"}
                </td>
                <td className="px-3 py-2 text-xs">{idade(f)}</td>
                <td className="px-3 py-2">
                  <Selo texto={f.situacao} />
                </td>
                <td className="px-3 py-2 text-xs">
                  {f.ultima_falha ? (
                    <>
                      #{f.ultima_falha.id} · {f.ultima_falha.dataset_chave}{" "}
                      <Selo texto={f.ultima_falha.status} />
                    </>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </Tabela>
        </>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------
function SecaoExecucoes() {
  const [soProblemas, setSoProblemas] = useState(true);
  const { dados, erro, carregando } = useDados(
    () =>
      api.execucoes(
        soProblemas ? { status: "falha,bloqueada" } : { limite: 50 },
      ),
    [soProblemas],
  );
  const [aberta, setAberta] = useState<number | null>(null);
  const lista = dados?.dados ?? [];

  return (
    <section aria-labelledby="quebrou">
      <h2 id="quebrou" className="font-medium mb-1">
        O que quebrou
      </h2>
      <p className="text-sm text-tinta-suave mb-3">
        Execuções de carga. Bloqueada significa que o gate de qualidade
        segurou a publicação — o consumidor continuou vendo a última versão
        íntegra.
      </p>
      <Caixa
        rotulo="Só falhas e bloqueios"
        marcado={soProblemas}
        aoMudar={(v) => {
          setSoProblemas(v);
          setAberta(null);
        }}
      />
      {carregando && <Carregando oque="execuções" />}
      {erro && <Erro mensagem={erro} />}
      {dados && lista.length === 0 && (
        <Vazio
          titulo={soProblemas ? "Nenhuma falha registrada" : "Nenhuma execução"}
        />
      )}
      {lista.length > 0 && (
        <Tabela
          legenda="Execuções de carga"
          colunas={["#", "Dataset", "Janela", "Status", "Quando", "Linhas", "Erro"]}
        >
          {lista.map((e: Execucao) => (
            <>
              <tr key={e.id} className="border-b border-borda last:border-0 align-top">
                <th scope="row" className="text-left px-3 py-2">
                  <button
                    onClick={() => setAberta(aberta === e.id ? null : e.id)}
                    aria-expanded={aberta === e.id}
                    className="underline decoration-dotted tabular-nums"
                  >
                    {e.id}
                    <span className="sr-only"> — linha do tempo por fase</span>
                  </button>
                </th>
                <td className="px-3 py-2 text-xs font-mono">{e.dataset_chave}</td>
                <td className="px-3 py-2 text-xs">{e.janela}</td>
                <td className="px-3 py-2">
                  <Selo texto={e.status} />
                </td>
                <td className="px-3 py-2 text-xs whitespace-nowrap">
                  {(e.terminado_em ?? e.iniciado_em).slice(0, 16).replace("T", " ")}
                </td>
                <td className="px-3 py-2 text-xs text-right tabular-nums">
                  {e.linhas_silver ?? "—"}
                </td>
                <td className="px-3 py-2 text-xs max-w-sm break-words">
                  {e.erro ?? "—"}
                </td>
              </tr>
              {aberta === e.id && (
                <tr key={`${e.id}-fases`}>
                  <td colSpan={7} className="px-3 py-3 bg-gray-50">
                    <LinhaDoTempo execucao_id={e.id} />
                  </td>
                </tr>
              )}
            </>
          ))}
        </Tabela>
      )}
    </section>
  );
}

/** A linha do tempo de log_fase, que só existia em JSON: cada fase com a
 * duração em barra proporcional ao total da execução. */
function LinhaDoTempo({ execucao_id }: { execucao_id: number }) {
  const { dados, erro, carregando } = useDados(
    () => api.fases(execucao_id),
    [execucao_id],
  );
  if (carregando) return <Carregando oque="fases" />;
  if (erro) return <Erro mensagem={erro} />;
  const fases = dados?.dados ?? [];
  if (fases.length === 0)
    return <p className="text-sm text-tinta-suave">Sem fases registradas.</p>;
  const total = fases.reduce((s, f) => s + (f.duracao_ms ?? 0), 0) || 1;

  return (
    <div className="grid gap-1 max-w-2xl" role="img"
         aria-label={`Fases da execução ${execucao_id}: ${fases
           .map((f) => `${f.fase} ${f.duracao_ms ?? 0} ms`)
           .join(", ")}`}>
      {fases.map((f) => (
        <div key={f.fase} className="grid grid-cols-[120px_1fr_80px] gap-2 items-center text-xs">
          <span className="font-mono">{f.fase}</span>
          <span className="bg-white border border-borda rounded h-4 overflow-hidden">
            <span
              className="block h-full bg-tinta-suave"
              style={{ width: `${Math.max(1, (100 * (f.duracao_ms ?? 0)) / total)}%` }}
            />
          </span>
          <span className="text-right tabular-nums">
            {f.duracao_ms != null ? `${f.duracao_ms} ms` : "—"}
          </span>
        </div>
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------
function SecaoLinhagem() {
  const classes = useDados(() => api.classes());
  const [classe, setClasse] = useState("");
  const [atributo, setAtributo] = useState("");
  const [resultado, setResultado] = useState<Linhagem | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [buscando, setBuscando] = useState(false);

  const lista = classes.dados?.dados ?? [];
  const atributos =
    lista.find((c) => c.chave === classe)?.atributos.map((a) => a.nome) ?? [];

  async function perguntar() {
    if (!classe || !atributo) return;
    setBuscando(true);
    setErro(null);
    setResultado(null);
    try {
      const r = await api.linhagem(classe, atributo);
      setResultado(r.dados);
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setBuscando(false);
    }
  }

  return (
    <section aria-labelledby="linhagem">
      <h2 id="linhagem" className="font-medium mb-1">
        De onde veio este número
      </h2>
      <p className="text-sm text-tinta-suave mb-3">
        A cadeia inteira de um atributo: fontes na ordem de precedência,
        coluna do arquivo, regras que o vigiam e capturas recentes.
      </p>
      <div className="border border-borda rounded bg-white p-4 grid gap-x-6 sm:grid-cols-[minmax(0,240px)_minmax(0,240px)_auto] items-end">
        <Selecao
          rotulo="Classe"
          valor={classe}
          aoMudar={(v) => {
            setClasse(v);
            setAtributo("");
            setResultado(null);
          }}
          opcoes={[
            { valor: "", rotulo: "— escolha —" },
            ...lista.map((c) => ({ valor: c.chave, rotulo: c.nome })),
          ]}
        />
        <Selecao
          rotulo="Atributo"
          valor={atributo}
          aoMudar={(v) => {
            setAtributo(v);
            setResultado(null);
          }}
          opcoes={[
            { valor: "", rotulo: "— escolha —" },
            ...atributos.map((a) => ({ valor: a, rotulo: a })),
          ]}
        />
        <div className="mb-4">
          <Botao
            variante="primario"
            carregando={buscando}
            desabilitado={!classe || !atributo}
            aoClicar={perguntar}
          >
            Rastrear
          </Botao>
        </div>
      </div>

      {erro && <Erro mensagem={erro} />}
      {resultado && <ResultadoLinhagem l={resultado} />}
    </section>
  );
}

function ResultadoLinhagem({ l }: { l: Linhagem }) {
  return (
    <div className="border border-borda rounded bg-white p-4 mt-4 grid gap-4">
      <p className="text-sm">
        <span className="font-mono">{l.classe}.{l.atributo}</span>{" "}
        <span className="text-tinta-suave">({l.tipo})</span>
        {l.descricao && (
          <span className="block text-xs text-tinta-suave mt-1">
            {l.descricao}
          </span>
        )}
      </p>

      {l.disputado ? (
        <p className="text-sm">
          Atributo <strong>disputado</strong> — {l.origens.length} fontes o
          alimentam; vence a primeira com valor na ordem:{" "}
          <span className="font-mono">{l.precedencia.join(" › ")}</span>
        </p>
      ) : (
        <p className="text-sm text-tinta-suave">
          Sem disputa: {l.precedencia.length <= 1 ? "uma fonte alimenta este atributo" : "as fontes nunca produzem a mesma linha"}.
        </p>
      )}

      <ol className="grid gap-3 list-none p-0 m-0">
        {l.origens.map((o, i) => (
          <li key={o.dataset} className="border border-borda rounded p-3">
            <p className="text-sm font-medium">
              {i + 1}º <span className="font-mono">{o.dataset}</span>
              <span className="text-tinta-suave font-normal">
                {" "}
                · fonte {o.fonte.chave}
              </span>
            </p>
            <dl className="text-xs grid sm:grid-cols-2 gap-x-6 gap-y-1 mt-2">
              {o.coluna_de_origem && (
                <div>
                  <dt className="text-tinta-suave inline">Coluna do arquivo: </dt>
                  <dd className="inline font-mono">
                    {o.coluna_de_origem}
                    {o.formato && ` (${o.formato})`}
                  </dd>
                </div>
              )}
              {o.expressao && (
                <div className="sm:col-span-2">
                  <dt className="text-tinta-suave inline">Calculado por: </dt>
                  <dd className="inline font-mono">{o.expressao}</dd>
                  {o.colunas_que_usa.length > 0 && (
                    <span className="text-tinta-suave">
                      {" "}
                      — usa {o.colunas_que_usa.join(", ")}
                    </span>
                  )}
                </div>
              )}
              {o.fonte.url_template && (
                <div className="sm:col-span-2">
                  <dt className="text-tinta-suave inline">Origem oficial: </dt>
                  <dd className="inline font-mono break-all">
                    {o.fonte.url_template}
                  </dd>
                </div>
              )}
              <div className="sm:col-span-2">
                <dt className="text-tinta-suave inline">Regras que vigiam: </dt>
                <dd className="inline">
                  {o.regras.length === 0
                    ? "nenhuma"
                    : o.regras.map((r) => `${r.nome} (${r.severidade})`).join(", ")}
                </dd>
              </div>
              {o.capturas_recentes.length > 0 && (
                <div className="sm:col-span-2">
                  <dt className="text-tinta-suave inline">Última captura: </dt>
                  <dd className="inline font-mono break-all">
                    {o.capturas_recentes[0].nome_arquivo} ·{" "}
                    {o.capturas_recentes[0].capturado_em.slice(0, 16).replace("T", " ")}{" "}
                    · sha256 {o.capturas_recentes[0].sha256.slice(0, 12)}…
                  </dd>
                </div>
              )}
            </dl>
          </li>
        ))}
      </ol>

      <p className="text-xs text-tinta-suave">
        Publicado pelas vistas {l.vistas.join(", ") || "—"} · publicação atual
        v{l.publicacao_atual ?? "—"}.
      </p>
    </div>
  );
}
