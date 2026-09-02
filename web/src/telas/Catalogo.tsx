import { useState } from "react";
import { api } from "../api";
import { argumento } from "../App";
import { Carregando, Erro, Tabela, Vazio, useDados } from "../ui";

export function Catalogo() {
  const lista = useDados(() => api.catalogo());
  // Chegando de "Ver as linhas" na tela de Classes, a tabela vem na rota:
  // é o que faz a classe deixar de ser beco sem saída.
  const [alvo, setAlvo] = useState<string | null>(() => argumento("tabela"));
  const detalhe = useDados(
    () => (alvo ? api.tabela(alvo) : Promise.resolve(null)),
    [alvo],
  );

  if (lista.carregando) return <Carregando oque="catálogo" />;
  if (lista.erro) return <Erro mensagem={lista.erro} />;

  const tabelas = lista.dados?.dados ?? [];
  // Grupos por prefixo, nunca por nome de tabela: uma classe criada agora
  // pela interface precisa aparecer aqui sem ninguém editar esta lista.
  const controle = (t: string) => t.startsWith("cfg_") || t.startsWith("log_");
  const grupos = {
    "No ar (consumo)": tabelas.filter((t) => t.startsWith("gold_")),
    "Bastidores": tabelas.filter(
      (t) => !t.startsWith("gold_") && !controle(t),
    ),
    "Plano de controle": tabelas.filter(controle),
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
      <nav aria-label="Tabelas do catálogo" className="grid gap-4 content-start">
        {Object.entries(grupos).map(([grupo, itens]) => (
          <div key={grupo}>
            <h2 className="text-sm font-medium mb-2">{grupo}</h2>
            <ul className="grid gap-0.5">
              {itens.map((t) => (
                <li key={t}>
                  <button
                    onClick={() => setAlvo(t)}
                    aria-current={t === alvo ? "true" : undefined}
                    className={`w-full text-left px-2 py-1 rounded font-mono text-xs ${
                      t === alvo ? "bg-tinta text-white" : "hover:bg-gray-100"
                    }`}
                  >
                    {t}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <section aria-live="polite">
        {!alvo && (
          <Vazio
            titulo="Selecione uma tabela"
            dica="A amostra mostra as 10 primeiras linhas."
          />
        )}
        {alvo && detalhe.carregando && <Carregando oque={alvo} />}
        {alvo && detalhe.erro && <Erro mensagem={detalhe.erro} />}
        {alvo && detalhe.dados && (
          <div className="grid gap-4">
            <div>
              <h2 className="font-medium font-mono">{detalhe.dados.dados.tabela}</h2>
              <p className="text-sm text-tinta-suave">
                {detalhe.dados.dados.linhas.toLocaleString("pt-BR")} linhas ·{" "}
                {detalhe.dados.dados.colunas.length} colunas
              </p>
            </div>

            <Tabela
              legenda={`Colunas de ${detalhe.dados.dados.tabela}`}
              colunas={["Coluna", "Tipo"]}
            >
              {detalhe.dados.dados.colunas.map((c) => (
                <tr key={c.nome} className="border-b border-borda last:border-0">
                  <th scope="row" className="text-left px-3 py-1.5 font-mono text-xs">
                    {c.nome}
                  </th>
                  <td className="px-3 py-1.5 text-xs text-tinta-suave">{c.tipo}</td>
                </tr>
              ))}
            </Tabela>

            <div>
              <h3 className="text-sm font-medium mb-2">Amostra</h3>
              {detalhe.dados.dados.amostra.length === 0 ? (
                <Vazio titulo="Tabela vazia" />
              ) : (
                <Tabela
                  legenda={`Amostra de ${detalhe.dados.dados.tabela}`}
                  colunas={Object.keys(detalhe.dados.dados.amostra[0])}
                >
                  {detalhe.dados.dados.amostra.map((linha, i) => (
                    <tr key={i} className="border-b border-borda last:border-0">
                      {Object.values(linha).map((v, j) => (
                        <td key={j} className="px-3 py-1.5 text-xs whitespace-nowrap">
                          {v === null ? (
                            <span className="text-tinta-suave">—</span>
                          ) : (
                            String(v).slice(0, 60)
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </Tabela>
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
