import { useState } from "react";
import { LinhaDoTempo } from "../objetos";
import { api, type Dataset, type ResultadoExecucao } from "../api";
import {
  Aviso, Botao, Campo, Carregando, Confirmar, Erro, Selo, Tabela, Vazio, useDados,
} from "../ui";

export function Execucoes() {
  const execs = useDados(() => api.execucoes());
  const datasets = useDados(() => api.datasets());
  const pubs = useDados(() => api.publicacoes());

  const [alvo, setAlvo] = useState("");
  const [janela, setJanela] = useState(String(new Date().getFullYear() - 1));
  const [baixar, setBaixar] = useState(true);
  const [rodando, setRodando] = useState(false);
  const [saida, setSaida] = useState<ResultadoExecucao | null>(null);
  const [falha, setFalha] = useState<string | null>(null);
  const [confirmando, setConfirmando] = useState<number | null>(null);
  const [detalhe, setDetalhe] = useState<number | null>(null);

  async function disparar(e: React.FormEvent) {
    e.preventDefault();
    setRodando(true);
    setSaida(null);
    setFalha(null);
    try {
      const r = await api.disparar(alvo, janela, baixar);
      setSaida(r.dados);
      execs.recarregar();
      pubs.recarregar();
    } catch (e) {
      setFalha((e as Error).message);
    } finally {
      setRodando(false);
    }
  }

  async function reverter(versao: number) {
    setConfirmando(null);
    try {
      await api.reverter(versao);
      pubs.recarregar();
    } catch (e) {
      setFalha((e as Error).message);
    }
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_340px]">
      <div className="grid gap-6">
        <Frescor />

        <section aria-labelledby="hist">
          <h2 id="hist" className="font-medium mb-3">
            Histórico
          </h2>
          {execs.carregando && <Carregando oque="execuções" />}
          {execs.erro && <Erro mensagem={execs.erro} />}
          {execs.dados && execs.dados.dados.length === 0 && (
            <Vazio
              titulo="Nenhuma execução ainda"
              dica="Dispare a primeira carga ao lado."
            />
          )}
          {execs.dados && execs.dados.dados.length > 0 && (
            <Tabela
              legenda="Execuções de ingestão"
              colunas={["#", "Dataset", "Janela", "Status", "Linhas", "Δ", "Pub."]}
            >
              {execs.dados.dados.map((x) => (
                <tr key={x.id} className="border-b border-borda last:border-0 align-top">
                  <th scope="row" className="text-left px-3 py-2 font-mono text-xs">
                    <button
                      onClick={() => setDetalhe(detalhe === x.id ? null : x.id)}
                      aria-expanded={detalhe === x.id}
                      aria-label={`Fases da execução ${x.id}`}
                      className="underline decoration-dotted"
                    >
                      {x.id}
                    </button>
                    {detalhe === x.id && <Fases execucao={x.id} />}
                  </th>
                  <td className="px-3 py-2 font-mono text-xs">{x.dataset_chave}</td>
                  <td className="px-3 py-2">{x.janela}</td>
                  <td className="px-3 py-2">
                    <Selo texto={x.status} />
                    {x.erro && (
                      <span className="block text-xs text-erro mt-1 max-w-xs">
                        {x.erro}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 tabular-nums">{x.linhas_silver}</td>
                  <td className="px-3 py-2 tabular-nums">
                    {x.delta_linhas ?? "—"}
                  </td>
                  <td className="px-3 py-2">{x.publicacao ?? "—"}</td>
                </tr>
              ))}
            </Tabela>
          )}
        </section>

        <section aria-labelledby="pubs">
          <h2 id="pubs" className="font-medium mb-3">
            Publicações
          </h2>
          <Aviso>
            Publicar move o ponteiro de gold. Reverter volta o ponteiro para uma
            versão anterior — o dado não é apagado.
          </Aviso>
          {pubs.dados && (
            <Tabela
              legenda="Versões publicadas de gold"
              colunas={["Versão", "Publicada em", "Execução", "Ação"]}
            >
              {pubs.dados.dados.map((p) => (
                <tr key={p.versao} className="border-b border-borda last:border-0">
                  <th scope="row" className="text-left px-3 py-2">
                    v{p.versao}
                    {p.versao === pubs.dados!.atual && (
                      <span className="ml-2 text-xs text-ok">(no ar)</span>
                    )}
                  </th>
                  <td className="px-3 py-2 text-xs">{String(p.publicado_em)}</td>
                  <td className="px-3 py-2">{p.execucao_id ?? "—"}</td>
                  <td className="px-3 py-2">
                    {p.versao !== pubs.dados!.atual && (
                      <Botao aoClicar={() => setConfirmando(p.versao)}>
                        Reverter para v{p.versao}
                      </Botao>
                    )}
                  </td>
                </tr>
              ))}
            </Tabela>
          )}
        </section>
      </div>

      <section aria-labelledby="disparar">
        <h2 id="disparar" className="font-medium mb-3">
          Disparar carga
        </h2>
        <form onSubmit={disparar} className="border border-borda rounded p-4 bg-superficie">
          {falha && <Erro mensagem={falha} />}
          <div className="mb-4">
            <label htmlFor="ds" className="block text-sm font-medium mb-1">
              Dataset
            </label>
            <select
              id="ds"
              value={alvo}
              onChange={(e) => setAlvo(e.target.value)}
              className="w-full rounded border border-borda px-3 py-2 text-sm bg-superficie"
            >
              <option value="">Selecione…</option>
              {(datasets.dados?.dados ?? []).map((d: Dataset) => (
                <option key={d.chave} value={d.chave}>
                  {d.nome}
                </option>
              ))}
            </select>
          </div>
          <Campo
            rotulo="Janela"
            valor={janela}
            aoMudar={setJanela}
            ajuda="Ano para DFP/ITR; use 'atual' para o cadastro."
          />
          <div className="mb-4 flex items-start gap-2">
            <input
              id="baixar"
              type="checkbox"
              checked={baixar}
              onChange={(e) => setBaixar(e.target.checked)}
              className="mt-1"
            />
            <label htmlFor="baixar" className="text-sm">
              Baixar da fonte
              <span className="block text-xs text-tinta-suave">
                Desmarcado, faz replay do bronze já capturado — sem rede.
              </span>
            </label>
          </div>
          <Botao tipo="submit" variante="primario" carregando={rodando}
                 desabilitado={!alvo || !janela}>
            Executar
          </Botao>
        </form>

        {saida && (
          <div role="status" className="mt-4 border border-borda rounded p-4 bg-superficie text-sm">
            <p className="font-medium mb-2">
              Execução #{saida.execucao_id} — <Selo texto={saida.status} />
            </p>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
              <dt className="text-tinta-suave">Capturas</dt>
              <dd>{saida.capturas} ({saida.capturas_novas} novas)</dd>
              <dt className="text-tinta-suave">Linhas carregadas</dt>
              <dd className="tabular-nums">{saida.linhas_silver}</dd>
              <dt className="text-tinta-suave">Delta</dt>
              <dd className="tabular-nums">{saida.delta_linhas ?? "—"}</dd>
              <dt className="text-tinta-suave">Publicação</dt>
              <dd>{saida.publicacao ?? "não publicada"}</dd>
            </dl>
            {saida.violacoes.length > 0 && (
              <ul className="mt-3 text-xs list-disc pl-4">
                {saida.violacoes.map((v) => (
                  <li key={v.nome} className={v.severidade === "bloqueia" ? "text-erro" : "text-alerta"}>
                    {v.nome}: {v.linhas} linhas ({v.severidade})
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>

      <Confirmar
        aberto={confirmando !== null}
        titulo="Reverter publicação"
        objeto={`a versão v${confirmando}`}
        consequencia="O ponteiro de gold voltará para"
        aoConfirmar={() => reverter(confirmando!)}
        aoCancelar={() => setConfirmando(null)}
      />
    </div>
  );
}


// --------------------------------------------------------------------------
/** Frescor por classe: a primeira coisa que o operador precisa ver ao abrir
 *  a tela — o que está velho, antes de o que rodou. */
function Frescor() {
  const f = useDados(() => api.frescor());
  if (f.carregando) return <Carregando oque="frescor" />;
  if (f.erro) return <Erro mensagem={f.erro} />;
  const linhas = f.dados?.dados ?? [];
  if (linhas.length === 0) return null;

  return (
    <section aria-labelledby="fresc">
      <h2 id="fresc" className="font-medium mb-3">
        Frescor por classe
      </h2>
      <Tabela
        legenda="Idade do dado de cada classe contra o SLA declarado"
        colunas={["Classe", "Atualizada há", "SLA", "Situação", "Última falha"]}
      >
        {linhas.map((x) => (
          <tr key={x.classe} className="border-b border-borda last:border-0">
            <th scope="row" className="text-left px-3 py-2">
              {x.nome}
              <span className="block text-xs text-tinta-suave">
                {x.fontes.join(", ") || "sem fonte"}
              </span>
            </th>
            <td className="px-3 py-2 text-xs tabular-nums">
              {x.idade_horas === null ? "—" : `${Math.round(x.idade_horas)} h`}
            </td>
            <td className="px-3 py-2 text-xs tabular-nums">
              {x.sla_horas === null ? "—" : `${x.sla_horas} h`}
            </td>
            <td className="px-3 py-2">
              <Selo texto={x.situacao} />
            </td>
            <td className="px-3 py-2 text-xs text-alerta max-w-xs">
              {x.ultima_falha ? `#${x.ultima_falha.id} ${x.ultima_falha.status}` : "—"}
            </td>
          </tr>
        ))}
      </Tabela>
    </section>
  );
}

/** Onde a carga gastou o tempo. Sem isto sabe-se que demorou, não onde.
 *
 * A barra proporcional mora em `LinhaDoTempo`; aqui só a busca. Era esta a
 * duplicata: a mesma lista de fases desenhada de dois jeitos diferentes no
 * plano de controle e na apresentação. */
function Fases({ execucao }: { execucao: number }) {
  const f = useDados(() => api.fases(execucao), [execucao]);
  const linhas = f.dados?.dados ?? [];
  if (linhas.length === 0) return null;
  return (
    <div className="mt-2 font-normal">
      <LinhaDoTempo fases={linhas} />
    </div>
  );
}
