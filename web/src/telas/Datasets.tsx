import { useState } from "react";
import { api, type Dataset } from "../api";
import { Aviso, Carregando, Erro, Selo, Tabela, Vazio, useDados } from "../ui";

export function Datasets() {
  const { dados, erro, carregando } = useDados(() => api.datasets());
  const [aberto, setAberto] = useState<string | null>(null);

  if (carregando) return <Carregando oque="datasets" />;
  if (erro) return <Erro mensagem={erro} />;
  if (!dados || dados.dados.length === 0)
    return (
      <Vazio
        titulo="Nenhum dataset configurado"
        dica="Cadastre uma fonte primeiro, depois o mapeamento arquivo → tabela."
      />
    );

  return (
    <div className="grid gap-4">
      <Aviso>
        Colunas cujo nome de origem começa com <code>$</code> vêm dos grupos
        nomeados do padrão de arquivo, não do CSV. É assim que{" "}
        <code>tipo_doc</code>, <code>grupo</code> e <code>consolidado</code>{" "}
        entram sem código específico da fonte.
      </Aviso>

      {dados.dados.map((d: Dataset) => (
        <article key={d.chave} className="border border-borda rounded bg-white">
          <h2>
            <button
              onClick={() => setAberto(aberto === d.chave ? null : d.chave)}
              aria-expanded={aberto === d.chave}
              aria-controls={`painel-${d.chave}`}
              className="w-full text-left px-4 py-3 flex items-baseline justify-between gap-3"
            >
              <span>
                <span className="font-medium">{d.nome}</span>
                <span className="font-mono text-xs text-tinta-suave ml-2">
                  {d.chave}
                </span>
                {/* O mapeamento existe para alimentar uma classe: dizer qual
                    é a informação principal, não detalhe do painel. */}
                <span className="block text-xs text-tinta-suave">
                  {d.fonte_chave} → {d.classe_chave ?? "sem classe"}
                </span>
              </span>
              <span className="text-xs text-tinta-suave">
                v{d.versao} · {d.colunas.length} colunas ·{" "}
                {d.calculados.length} calculados · {d.regras.length} regras
              </span>
            </button>
          </h2>

          {aberto === d.chave && (
            <div id={`painel-${d.chave}`} className="px-4 pb-4 grid gap-4">
              <dl className="text-sm grid sm:grid-cols-2 gap-x-6 gap-y-1">
                <div>
                  <dt className="text-tinta-suave inline">Classe: </dt>
                  <dd className="inline font-mono text-xs">
                    {d.classe_chave ?? "—"} ({d.tabela_destino})
                  </dd>
                </div>
                <div>
                  <dt className="text-tinta-suave inline">Fonte: </dt>
                  <dd className="inline font-mono text-xs">{d.fonte_chave}</dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="text-tinta-suave inline">Padrão de arquivo: </dt>
                  <dd className="inline font-mono text-xs break-all">
                    {d.padrao_arquivo}
                  </dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="text-tinta-suave inline">Chave natural: </dt>
                  <dd className="inline font-mono text-xs">{d.chave_natural}</dd>
                </div>
              </dl>

              <Tabela
                legenda={`Colunas do dataset ${d.nome}`}
                colunas={["Origem", "Destino", "Tipo", "Formato", "Obrigatória"]}
              >
                {d.colunas.map((c) => (
                  <tr
                    key={c.nome_destino}
                    className="border-b border-borda last:border-0"
                  >
                    <th
                      scope="row"
                      className="text-left px-3 py-1.5 font-mono text-xs"
                    >
                      {c.nome_origem}
                    </th>
                    <td className="px-3 py-1.5 font-mono text-xs">
                      {c.nome_destino}
                    </td>
                    <td className="px-3 py-1.5">{c.tipo}</td>
                    <td className="px-3 py-1.5 text-tinta-suave">
                      {c.formato ?? "—"}
                    </td>
                    <td className="px-3 py-1.5">
                      {c.obrigatoria ? <Selo texto="obrigatória" /> : "—"}
                    </td>
                  </tr>
                ))}
              </Tabela>
            </div>
          )}
        </article>
      ))}
    </div>
  );
}
