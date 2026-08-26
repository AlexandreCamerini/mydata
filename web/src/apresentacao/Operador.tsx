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
import { LinhaDoTempo, Linhagem, SaudeClasse } from "../objetos";
import { api, type Execucao, type LinhagemDeAtributo } from "./api";

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
          <div className="grid gap-3 lg:grid-cols-2">
            {lista.map((f) => (
              // `/v1/meta/frescor` chama de `classe` o que o resto do sistema
              // chama de `chave`. Renomear a resposta seria mudar contrato
              // público por conveniência de tela.
              <SaudeClasse key={f.classe} c={{ ...f, chave: f.classe }} />
            ))}
          </div>
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
                    <FasesDe execucao_id={e.id} />
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

/** Busca as fases e entrega ao objeto. O objeto não busca: são dois bundles
 * com dois módulos `api`, e quem sabe qual deles vale é a tela. */
function FasesDe({ execucao_id }: { execucao_id: number }) {
  const { dados, erro, carregando } = useDados(
    () => api.fases(execucao_id),
    [execucao_id],
  );
  if (carregando) return <Carregando oque="fases" />;
  if (erro) return <Erro mensagem={erro} />;
  return <LinhaDoTempo fases={dados?.dados ?? []} />;
}

// --------------------------------------------------------------------------
function SecaoLinhagem() {
  const classes = useDados(() => api.classes());
  const [classe, setClasse] = useState("");
  const [atributo, setAtributo] = useState("");
  const [resultado, setResultado] = useState<LinhagemDeAtributo | null>(null);
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
      <div className="border border-borda rounded bg-superficie p-4 grid gap-x-6 sm:grid-cols-[minmax(0,240px)_minmax(0,240px)_auto] items-end">
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
      {resultado && (
        <div className="mt-4">
          <Linhagem l={resultado} />
        </div>
      )}
    </section>
  );
}
