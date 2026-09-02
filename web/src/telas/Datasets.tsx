import { useEffect, useState } from "react";
import {
  api,
  datasetParaEntrada,
  type Dataset,
  type DatasetPayload,
  type Execucao,
} from "../api";
import {
  Aviso,
  BadgeConexao,
  Botao,
  Carregando,
  Erro,
  Faixas,
  Selo,
  Tabela,
  Vazio,
  estadoDaConexao,
  useDados,
} from "../ui";
import { DatasetForm } from "./DatasetForm";

function contagem(n: number): string {
  if (n >= 1_000_000)
    return `${(n / 1_000_000).toLocaleString("pt-BR", { maximumFractionDigits: 2 })} mi`;
  if (n >= 1_000)
    return `${(n / 1_000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mil`;
  return n.toLocaleString("pt-BR");
}

function haQuanto(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const ms = Date.now() - new Date(iso).getTime();
  const h = ms / 3_600_000;
  if (h < 1) return `${Math.max(1, Math.round(ms / 60_000))} min`;
  if (h < 48) return `${Math.round(h)} h`;
  return `${Math.round(h / 24)} d`;
}

/** As últimas 6 execuções de cada conexão, para o estado e a faixa do card.
 * Um `GET` por conexão — direto do histórico bruto que `Execuções` já lê,
 * sem endpoint novo (é o que o mapeamento de viabilidade da "direção A"
 * achou: a agregação por classe em `/gestao` não serve, mas o histórico por
 * dataset em `/execucoes?dataset=` já tem tudo).
 *
 * `"erro"` é distinto de lista vazia — sessão caiu no meio da tela é falha
 * de carga, não "esta conexão nunca rodou". Misturar os dois faria o card
 * afirmar um fato que não é o real (achado 2.3: erro cru não vira estado). */
function useHistoricoPorConexao(
  datasets: Dataset[],
): Record<string, Execucao[] | "erro"> {
  const [historico, setHistorico] = useState<Record<string, Execucao[] | "erro">>({});
  const chaves = datasets.map((d) => d.chave).join(",");
  useEffect(() => {
    if (!chaves) return;
    let vivo = true;
    Promise.all(
      chaves
        .split(",")
        .map((chave) =>
          api
            .execucoes(chave, undefined, 6)
            .then((r) => [chave, r.dados] as const)
            .catch(() => [chave, "erro"] as const),
        ),
    ).then((pares) => vivo && setHistorico(Object.fromEntries(pares)));
    return () => {
      vivo = false;
    };
  }, [chaves]);
  return historico;
}

export function Datasets() {
  const { dados, erro, carregando, recarregar } = useDados(() => api.datasets());
  const fontes = useDados(() => api.fontes());
  const classes = useDados(() => api.classes());
  const historico = useHistoricoPorConexao(dados?.dados ?? []);
  const [aberto, setAberto] = useState<string | null>(null);
  // null = lista; {} = conexão nova; {inicial} = nova versão.
  const [editor, setEditor] = useState<{ inicial?: DatasetPayload } | null>(
    null,
  );

  if (editor) {
    return (
      <DatasetForm
        inicial={editor.inicial}
        fontes={(fontes.dados?.dados ?? []).map((f) => f.chave)}
        classes={(classes.dados?.dados ?? []).map((c) => c.chave)}
        aoSalvar={recarregar}
        aoFechar={() => setEditor(null)}
      />
    );
  }

  // Só na primeira carga: o recarregar pós-salvar não pode desmontar a tela.
  if (carregando && !dados) return <Carregando oque="conexões" />;
  if (erro) return <Erro mensagem={erro} />;

  if (!dados || dados.dados.length === 0)
    return (
      <div className="grid gap-4">
        <Vazio
          titulo="Nenhuma conexão configurada"
          dica="Cadastre uma fonte primeiro, depois a conexão arquivo → tabela."
        />
        <div>
          <Botao variante="primario" aoClicar={() => setEditor({})}>
            Nova conexão
          </Botao>
        </div>
      </div>
    );

  const abertaObj = dados.dados.find((d) => d.chave === aberto) ?? null;

  return (
    <div className="grid gap-4">
      <div>
        <Botao variante="primario" aoClicar={() => setEditor({})}>
          Nova conexão
        </Botao>
      </div>
      <Aviso>
        Colunas cujo nome de origem começa com <code>$</code> vêm dos grupos
        nomeados do padrão de arquivo, não do CSV. É assim que{" "}
        <code>tipo_doc</code>, <code>grupo</code> e <code>consolidado</code>{" "}
        entram sem código específico da fonte.
      </Aviso>

      <ul className="grid gap-3 sm:grid-cols-2 list-none p-0 m-0" aria-label="Conexões">
        {dados.dados.map((d: Dataset) => {
          const bruto = historico[d.chave];
          const falhouCarga = bruto === "erro";
          const h = Array.isArray(bruto) ? bruto : [];
          const ultima = h[0];
          const publicada = h.find((e) => e.status === "publicado");
          const estado = estadoDaConexao(d.ativo, ultima?.status);
          const idade = haQuanto(publicada?.terminado_em);
          return (
            <li key={d.chave}>
            <button
              onClick={() => setAberto(aberto === d.chave ? null : d.chave)}
              aria-expanded={aberto === d.chave}
              aria-controls={`painel-${d.chave}`}
              className={`w-full text-left border rounded bg-superficie p-3 grid gap-2 hover:border-acento ${
                aberto === d.chave ? "border-acento" : "border-borda"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="font-medium">{d.nome}</p>
                  <p className="text-xs text-tinta-suave">
                    {d.fonte_chave} → {d.classe_chave ?? "sem classe"}
                  </p>
                </div>
                {falhouCarga ? (
                  <span className="text-xs text-tinta-suave whitespace-nowrap">
                    estado indisponível
                  </span>
                ) : (
                  <BadgeConexao estado={estado} />
                )}
              </div>
              <div className="flex items-center gap-2 text-xs text-tinta-suave flex-wrap">
                {falhouCarga ? (
                  <span>Não deu para carregar o histórico agora.</span>
                ) : (
                  <>
                    <span>
                      {publicada ? `${contagem(publicada.linhas_silver)} linhas` : "sem carga"}
                    </span>
                    {idade && (
                      <>
                        <span aria-hidden="true">·</span>
                        <span>há {idade}</span>
                      </>
                    )}
                    <Faixas execucoes={[...h].reverse()} />
                  </>
                )}
              </div>
            </button>
            </li>
          );
        })}
      </ul>

      {abertaObj && (
        <div id={`painel-${abertaObj.chave}`} className="border border-borda rounded bg-superficie px-4 py-4 grid gap-4">
          <dl className="text-sm grid sm:grid-cols-2 gap-x-6 gap-y-1">
            <div>
              <dt className="text-tinta-suave inline">Chave: </dt>
              <dd className="inline font-mono text-xs">{abertaObj.chave}</dd>
            </div>
            <div>
              <dt className="text-tinta-suave inline">Classe: </dt>
              <dd className="inline font-mono text-xs">
                {abertaObj.classe_chave ?? "—"} ({abertaObj.tabela_destino})
              </dd>
            </div>
            <div>
              <dt className="text-tinta-suave inline">Fonte: </dt>
              <dd className="inline font-mono text-xs">{abertaObj.fonte_chave}</dd>
            </div>
            <div>
              <dt className="text-tinta-suave inline">Versão: </dt>
              <dd className="inline">
                v{abertaObj.versao} · {abertaObj.colunas.length} colunas ·{" "}
                {abertaObj.calculados.length} calculados ·{" "}
                {abertaObj.regras.length} regras
              </dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-tinta-suave inline">Padrão de arquivo: </dt>
              <dd className="inline font-mono text-xs break-all">
                {abertaObj.padrao_arquivo}
              </dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-tinta-suave inline">Chave natural: </dt>
              <dd className="inline font-mono text-xs">{abertaObj.chave_natural}</dd>
            </div>
          </dl>

          <Tabela
            legenda={`Colunas da conexão ${abertaObj.nome}`}
            colunas={["Origem", "Destino", "Tipo", "Formato", "Obrigatória"]}
          >
            {abertaObj.colunas.map((c) => (
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

          <div>
            <Botao
              aoClicar={() =>
                setEditor({ inicial: datasetParaEntrada(abertaObj) })
              }
            >
              Editar (nova versão)
            </Botao>
          </div>
        </div>
      )}
    </div>
  );
}
