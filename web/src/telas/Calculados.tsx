import { useState } from "react";
import { api, type Dataset } from "../api";
import { Aviso, Botao, Campo, Carregando, Erro, Selo, Tabela, Vazio, useDados } from "../ui";

export function Calculados() {
  const { dados, erro, carregando } = useDados(() => api.datasets());
  const metricas = useDados(() => api.metricas());

  // Validação sem gravar: é o que dá retorno imediato no formulário.
  const [nome, setNome] = useState("");
  const [expressao, setExpressao] = useState("");
  const [origens, setOrigens] = useState("");
  const [alvo, setAlvo] = useState("");
  const [resultado, setResultado] = useState<{ ok: boolean; msg: string } | null>(null);
  const [validando, setValidando] = useState(false);

  async function validar(e: React.FormEvent) {
    e.preventDefault();
    const ds = dados?.dados.find((d: Dataset) => d.chave === alvo);
    if (!ds) return;
    setValidando(true);
    setResultado(null);
    try {
      const r = await api.validarDataset(ds.chave, {
        chave: ds.chave,
        fonte_chave: ds.fonte_chave,
        nome: ds.nome,
        padrao_arquivo: ds.padrao_arquivo,
        tabela_destino: ds.tabela_destino,
        chave_natural: ds.chave_natural.split(","),
        colunas: ds.colunas,
        calculados: [
          ...ds.calculados.map((c) => ({
            nome: c.nome,
            expressao: c.expressao,
            colunas_origem: c.colunas_origem.split(","),
            classe: c.classe,
            particao_por: c.particao_por ? c.particao_por.split(",") : null,
          })),
          {
            nome,
            expressao,
            colunas_origem: origens.split(",").map((s) => s.trim()).filter(Boolean),
          },
        ],
        regras: [],
      });
      setResultado({ ok: r.valido, msg: r.mensagem });
    } catch (e) {
      setResultado({ ok: false, msg: (e as Error).message });
    } finally {
      setValidando(false);
    }
  }

  if (carregando) return <Carregando oque="campos calculados" />;
  if (erro) return <Erro mensagem={erro} />;

  const todos = (dados?.dados ?? []).flatMap((d: Dataset) =>
    d.calculados.map((c) => ({ ...c, dataset: d.chave })),
  );

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_380px]">
      <div className="grid gap-6">
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
      </div>

      <section aria-labelledby="validar-calc">
        <h2 id="validar-calc" className="font-medium mb-3">
          Validar novo campo
        </h2>
        <form onSubmit={validar} className="border border-borda rounded p-4 bg-white">
          <div className="mb-4">
            <label htmlFor="alvo" className="block text-sm font-medium mb-1">
              Dataset
            </label>
            <select
              id="alvo"
              value={alvo}
              onChange={(e) => setAlvo(e.target.value)}
              className="w-full rounded border border-borda px-3 py-2 text-sm bg-white"
            >
              <option value="">Selecione…</option>
              {(dados?.dados ?? []).map((d: Dataset) => (
                <option key={d.chave} value={d.chave}>
                  {d.nome}
                </option>
              ))}
            </select>
          </div>
          <Campo rotulo="Nome do campo" valor={nome} aoMudar={setNome} monoespacado />
          <Campo
            rotulo="Expressão"
            valor={expressao}
            aoMudar={setExpressao}
            multilinha
            monoespacado
            ajuda="SQL de leitura. Sem DDL, sem ponto e vírgula."
          />
          <Campo
            rotulo="Colunas de origem"
            valor={origens}
            aoMudar={setOrigens}
            monoespacado
            ajuda="Separadas por vírgula. Campo que não declara a origem é recusado."
          />
          <Botao tipo="submit" variante="primario" carregando={validando}
                 desabilitado={!alvo || !nome || !expressao}>
            Validar
          </Botao>

          {resultado && (
            <p
              role="status"
              className={`mt-3 text-sm ${resultado.ok ? "text-ok" : "text-erro"}`}
            >
              {resultado.ok ? "✓ " : "✕ "}
              {resultado.msg}
            </p>
          )}
        </form>
      </section>
    </div>
  );
}
