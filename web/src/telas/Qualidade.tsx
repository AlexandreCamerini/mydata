import { api, type Dataset } from "../api";
import { Aviso, Carregando, Erro, Selo, Tabela, Vazio, useDados } from "../ui";

export function Qualidade() {
  const { dados, erro, carregando } = useDados(() => api.datasets());

  if (carregando) return <Carregando oque="regras de qualidade" />;
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
              <th scope="row" className="text-left px-3 py-2">
                {r.nome}
                {r.descricao && (
                  <span className="block text-xs text-tinta-suave font-normal">
                    {r.descricao}
                  </span>
                )}
              </th>
              <td className="px-3 py-2 font-mono text-xs">{r.dataset}</td>
              <td className="px-3 py-2">
                <Selo texto={r.severidade === "bloqueia" ? "bloqueada" : r.severidade} />
              </td>
              <td className="px-3 py-2">{r.tolerancia}</td>
              <td className="px-3 py-2 font-mono text-xs max-w-lg break-words">
                {r.expressao_sql}
              </td>
            </tr>
          ))}
        </Tabela>
      )}
    </div>
  );
}
