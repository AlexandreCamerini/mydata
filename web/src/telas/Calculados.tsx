import { useState } from "react";
import { api, datasetParaEntrada, type Dataset, type DatasetPayload } from "../api";
import {
  Aviso,
  Botao,
  Campo,
  Carregando,
  Erro,
  Selecao,
  Selo,
  Tabela,
  Vazio,
  useDados,
} from "../ui";
import {
  EditorCalculados,
  ResultadoValidacao,
  useSalvarDataset,
} from "./DatasetForm";

export function Calculados() {
  const { dados, erro, carregando, recarregar } = useDados(() => api.datasets());
  const metricas = useDados(() => api.metricas());

  // Só na primeira carga: o recarregar pós-salvar não pode desmontar o editor.
  if (carregando && !dados) return <Carregando oque="campos calculados" />;
  if (erro) return <Erro mensagem={erro} />;

  const todos = (dados?.dados ?? []).flatMap((d: Dataset) =>
    d.calculados.map((c) => ({ ...c, dataset: d.chave })),
  );

  return (
    <div className="grid gap-8">
      <section aria-labelledby="lista-calc">
        <h2 id="lista-calc" className="font-medium mb-3">
          Campos calculados por dataset
        </h2>
        <Aviso>
          Campo de classe <strong>janela</strong> tem partição que pode cruzar
          janelas de carga — <code>is_latest</code> é o caso: reingerir um ano
          antigo pode rebaixar documento de outro ano, então ele é recomputado
          sobre a tabela inteira.
        </Aviso>
        {todos.length === 0 ? (
          <Vazio titulo="Nenhum campo calculado" />
        ) : (
          <Tabela
            legenda="Campos calculados e sua linhagem"
            colunas={["Nome", "Classe", "Expressão", "Colunas de origem"]}
          >
            {todos.map((c) => (
              <tr
                key={`${c.dataset}.${c.nome}`}
                className="border-b border-borda last:border-0 align-top"
              >
                <th scope="row" className="text-left px-3 py-2 font-mono text-xs">
                  {c.nome}
                  <span className="block text-tinta-suave">{c.dataset}</span>
                </th>
                <td className="px-3 py-2">
                  <Selo texto={c.classe} />
                </td>
                <td className="px-3 py-2 font-mono text-xs max-w-md break-words">
                  {c.expressao}
                  {c.descricao && (
                    <span className="block font-sans text-tinta-suave mt-1">
                      {c.descricao}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 font-mono text-xs">
                  {c.colunas_origem}
                </td>
              </tr>
            ))}
          </Tabela>
        )}
      </section>

      <EditorDoDataset datasets={dados?.dados ?? []} aoSalvar={recarregar} />

      <section aria-labelledby="lista-metricas">
        <h2 id="lista-metricas" className="font-medium mb-3">
          Indicadores de nível empresa
        </h2>
        {metricas.carregando && <Carregando oque="indicadores" />}
        {metricas.dados && (
          <Tabela
            legenda="Indicadores fundamentalistas configurados"
            colunas={["Indicador", "Fórmula", "Unidade"]}
          >
            {metricas.dados.dados.map((m) => (
              <tr key={m.chave} className="border-b border-borda last:border-0">
                <th scope="row" className="text-left px-3 py-2">
                  {m.nome}
                  {m.descricao && (
                    <span className="block text-xs text-tinta-suave">
                      {m.descricao}
                    </span>
                  )}
                </th>
                <td className="px-3 py-2 font-mono text-xs">{m.formula}</td>
                <td className="px-3 py-2">{m.unidade}</td>
              </tr>
            ))}
          </Tabela>
        )}
      </section>

      <FormMetrica aoSalvar={() => metricas.recarregar()} />
    </div>
  );
}

/** Edita os calculados de um dataset e salva como nova versão dele. O POST é
 * o dataset inteiro; o resto vai como está, só esta seção muda. */
function EditorDoDataset({
  datasets,
  aoSalvar,
}: {
  datasets: Dataset[];
  aoSalvar: () => void;
}) {
  const [alvo, setAlvo] = useState("");
  const [rascunho, setRascunho] = useState<DatasetPayload | null>(null);
  const { ocupado, resultado, validar, salvar, limpar } =
    useSalvarDataset(aoSalvar);

  function escolher(chave: string) {
    setAlvo(chave);
    limpar();
    const d = datasets.find((x) => x.chave === chave);
    setRascunho(d ? datasetParaEntrada(d) : null);
  }

  return (
    <section
      aria-labelledby="editar-calc"
      className="border border-borda rounded bg-white p-4"
    >
      <h2 id="editar-calc" className="font-medium mb-3">
        Editar calculados de um dataset
      </h2>
      <Selecao
        rotulo="Dataset"
        valor={alvo}
        aoMudar={escolher}
        opcoes={[
          { valor: "", rotulo: "— escolha —" },
          ...datasets.map((d) => ({ valor: d.chave, rotulo: d.nome })),
        ]}
        ajuda="Salvar cria uma nova versão do dataset com os calculados editados; o resto fica como está."
      />
      {rascunho && (
        <>
          <EditorCalculados
            calculados={rascunho.calculados}
            aoMudar={(calculados) => setRascunho({ ...rascunho, calculados })}
          />
          <ResultadoValidacao resultado={resultado} />
          <div className="flex gap-2">
            <Botao carregando={ocupado} aoClicar={() => validar(rascunho)}>
              Só validar
            </Botao>
            <Botao
              variante="primario"
              carregando={ocupado}
              aoClicar={() => salvar(rascunho)}
            >
              Validar e salvar nova versão
            </Botao>
          </div>
        </>
      )}
    </section>
  );
}

function FormMetrica({ aoSalvar }: { aoSalvar: () => void }) {
  const [form, setForm] = useState({
    chave: "",
    nome: "",
    formula: "",
    unidade: "razao",
    descricao: "",
  });
  const [erros, setErros] = useState<Record<string, string>>({});
  const [salvando, setSalvando] = useState(false);
  const [contas, setContas] = useState<string[] | null>(null);

  async function salvar(e: React.FormEvent) {
    e.preventDefault();
    const p: Record<string, string> = {};
    if (!form.chave.trim()) p.chave = "Informe uma chave.";
    else if (!/^[a-z0-9_]+$/.test(form.chave.trim()))
      p.chave = "Use apenas letras minúsculas, números e underscore.";
    if (!form.nome.trim()) p.nome = "Informe um nome.";
    if (!form.formula.trim()) p.formula = "Informe a fórmula.";
    setErros(p);
    if (Object.keys(p).length) return;

    setSalvando(true);
    setContas(null);
    try {
      const r = await api.salvarMetrica({
        chave: form.chave.trim(),
        nome: form.nome.trim(),
        formula: form.formula.trim(),
        unidade: form.unidade,
        descricao: form.descricao.trim() || null,
      });
      setContas(r.dados.contas_referenciadas);
      setForm({ ...form, chave: "", nome: "", formula: "", descricao: "" });
      aoSalvar();
    } catch (e) {
      setErros({ geral: (e as Error).message });
    } finally {
      setSalvando(false);
    }
  }

  return (
    <section aria-labelledby="nova-metrica">
      <h2 id="nova-metrica" className="font-medium mb-3">
        Nova versão de indicador
      </h2>
      <form
        onSubmit={salvar}
        className="border border-borda rounded p-4 bg-white max-w-2xl"
      >
        {erros.geral && <Erro mensagem={erros.geral} />}
        {contas && (
          <p role="status" className="text-sm text-ok mb-3">
            Indicador salvo. Contas referenciadas: {contas.join(", ") || "nenhuma"}.
          </p>
        )}
        <Campo
          rotulo="Chave"
          valor={form.chave}
          aoMudar={(v) => setForm({ ...form, chave: v })}
          erro={erros.chave}
          ajuda="Salvar sobre uma chave existente cria uma nova versão."
          obrigatorio
          monoespacado
        />
        <Campo
          rotulo="Nome"
          valor={form.nome}
          aoMudar={(v) => setForm({ ...form, nome: v })}
          erro={erros.nome}
          obrigatorio
        />
        <Campo
          rotulo="Fórmula"
          valor={form.formula}
          aoMudar={(v) => setForm({ ...form, formula: v })}
          erro={erros.formula}
          ajuda="Contas como c('1.01'): ex. c('1.01') / c('2.01'). As referências são conferidas ao salvar."
          obrigatorio
          monoespacado
          multilinha
        />
        <Selecao
          rotulo="Unidade"
          valor={form.unidade}
          aoMudar={(v) => setForm({ ...form, unidade: v })}
          opcoes={[
            { valor: "razao", rotulo: "razão" },
            { valor: "percentual", rotulo: "percentual" },
            { valor: "moeda", rotulo: "moeda" },
          ]}
        />
        <Campo
          rotulo="Descrição"
          valor={form.descricao}
          aoMudar={(v) => setForm({ ...form, descricao: v })}
          multilinha
        />
        <Botao tipo="submit" variante="primario" carregando={salvando}>
          Salvar indicador
        </Botao>
      </form>
    </section>
  );
}
