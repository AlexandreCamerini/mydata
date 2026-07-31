import { useState } from "react";
import { api, datasetParaEntrada, type Dataset, type DatasetPayload } from "../api";
import {
  Aviso,
  Botao,
  Carregando,
  Erro,
  Selecao,
  Selo,
  Tabela,
  Vazio,
  useDados,
} from "../ui";
import {
  EditorRegras,
  ResultadoValidacao,
  useSalvarDataset,
} from "./DatasetForm";

export function Qualidade() {
  const { dados, erro, carregando, recarregar } = useDados(() => api.datasets());

  // Só na primeira carga: o recarregar pós-salvar não pode desmontar o editor.
  if (carregando && !dados) return <Carregando oque="regras de qualidade" />;
  if (erro) return <Erro mensagem={erro} />;

  const regras = (dados?.dados ?? []).flatMap((d: Dataset) =>
    d.regras.map((r) => ({ ...r, dataset: d.chave })),
  );

  return (
    <div className="grid gap-4">
      <Aviso>
        A expressão de uma regra <strong>seleciona as linhas erradas</strong>.
        Zero linhas significa aprovado. Severidade <code>bloqueia</code> impede
        a publicação: o dado carregado fica invisível para o consumidor, que
        continua vendo a última versão íntegra.
      </Aviso>

      {regras.length === 0 ? (
        <Vazio titulo="Nenhuma regra configurada" />
      ) : (
        <Tabela
          legenda="Regras de qualidade e sua severidade"
          colunas={["Regra", "Dataset", "Severidade", "Tolerância", "Expressão"]}
        >
          {regras.map((r) => (
            <tr
              key={`${r.dataset}.${r.nome}`}
              className="border-b border-borda last:border-0 align-top"
            >
              <th scope="row" className="text-left px-3 py-2 font-mono text-xs">
                {r.nome}
                {r.descricao && (
                  <span className="block font-sans text-tinta-suave">
                    {r.descricao}
                  </span>
                )}
              </th>
              <td className="px-3 py-2 font-mono text-xs">{r.dataset}</td>
              <td className="px-3 py-2">
                <Selo texto={r.severidade} />
              </td>
              <td className="px-3 py-2 tabular-nums">{r.tolerancia}</td>
              <td className="px-3 py-2 font-mono text-xs max-w-md break-words">
                {r.expressao_sql}
              </td>
            </tr>
          ))}
        </Tabela>
      )}

      <EditorDoDataset datasets={dados?.dados ?? []} aoSalvar={recarregar} />
    </div>
  );
}

/** Edita as regras de um dataset e salva como nova versão dele. O POST é o
 * dataset inteiro; o resto vai como está, só esta seção muda. */
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
      aria-labelledby="editar-regras"
      className="border border-borda rounded bg-white p-4"
    >
      <h2 id="editar-regras" className="font-medium mb-3">
        Editar regras de um dataset
      </h2>
      <Selecao
        rotulo="Dataset"
        valor={alvo}
        aoMudar={escolher}
        opcoes={[
          { valor: "", rotulo: "— escolha —" },
          ...datasets.map((d) => ({ valor: d.chave, rotulo: d.nome })),
        ]}
        ajuda="Salvar cria uma nova versão do dataset com as regras editadas; o resto fica como está."
      />
      {rascunho && (
        <>
          <EditorRegras
            regras={rascunho.regras}
            aoMudar={(regras) => setRascunho({ ...rascunho, regras })}
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
