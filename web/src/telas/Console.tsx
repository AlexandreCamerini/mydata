// Console central, nível gerencial (ADR-25; spec-console-central §3).
//
// A pergunta: "o que está no ar, o que falhou e desde quando" — respondida com
// o que o coletor gravou, sem número que ele não gravou.
//
// Degradação por seção: cada bloco tem a própria chamada e o próprio estado.
// Uma rota que falha mostra o erro NAQUELE bloco (com o último dado bom, se
// houver, marcado como defasado) e não toca nos outros. É o mesmo princípio do
// backend, onde uma origem fora do ar não afeta as outras quatro.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, type ConsoleSituacao } from "../api";
import { Botao, Carregando, Erro, Tabela, Vazio, useDados } from "../ui";
import {
  ROTULO_ORIGEM,
  ROTULO_SITUACAO,
  agruparMetricas,
  classificarOrigem,
  commitCurto,
  deploysRecentes,
  formatarDuracao,
  formatarMs,
  haTempo,
  horaOuData,
  tomDoDeploy,
  type EstadoOrigem,
  type SituacaoEnvelope,
  type TomDeploy,
} from "./consoleLogica";

const RECARGA_MS = 60_000;

// Tom -> classes de token. Nada de valor cru: tudo vem de temas.css.
const ORIGEM_VISUAL: Record<EstadoOrigem, { texto: string; ponto: string }> = {
  ok: { texto: "text-ok", ponto: "bg-ok border-ok" },
  falha: { texto: "text-erro", ponto: "bg-erro border-erro" },
  // Vazado, não preenchido: "desligada" não pode ler como "aceso".
  nao_configurada: { texto: "text-tinta-suave", ponto: "border-tinta-suave" },
  sem_coleta: { texto: "text-tinta-suave", ponto: "border-tinta-suave" },
};

const SITUACAO_VISUAL: Record<SituacaoEnvelope, string> = {
  ok: "bg-ok-suave text-ok border-ok",
  atencao: "bg-alerta-suave text-alerta border-alerta",
  critico: "bg-erro-suave text-erro border-erro",
};

const DEPLOY_VISUAL: Record<TomDeploy, string> = {
  ok: "bg-ok-suave text-ok border-ok",
  erro: "bg-erro-suave text-erro border-erro",
  andamento: "bg-acento-suave text-acento border-acento",
  neutro: "bg-superficie text-tinta-suave border-borda",
};

/** Bloco com título, erro próprio e aviso de dado defasado. */
function Secao(props: {
  id: string;
  titulo: string;
  nota?: string;
  erro: string | null;
  temDados: boolean;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={props.id}>
      <h2 id={props.id} className="font-medium">
        {props.titulo}
      </h2>
      {props.nota && <p className="rotulo mb-3">{props.nota}</p>}
      {!props.nota && <div className="mb-3" />}
      {props.erro && (
        <Erro
          mensagem={
            props.temDados
              ? `Não foi possível atualizar esta seção (${props.erro}). Abaixo, o último dado recebido.`
              : `Esta seção não carregou: ${props.erro}`
          }
        />
      )}
      {props.children}
    </section>
  );
}

// --------------------------------------------------------------------------
function CartaoOrigem({ s, agora }: { s: ConsoleSituacao; agora: Date }) {
  const estado = classificarOrigem(s);
  const v = ORIGEM_VISUAL[estado];
  return (
    <li
      className={`border rounded p-3 bg-superficie ${
        estado === "falha" ? "border-erro" : "border-borda"
      }`}
    >
      <p className="flex items-center gap-2 font-medium">
        <span
          aria-hidden="true"
          className={`inline-block w-2.5 h-2.5 rounded-full border ${v.ponto}`}
        />
        {s.origem}
      </p>
      <p className={`text-sm font-medium mt-1 ${v.texto}`}>
        {ROTULO_ORIGEM[estado]}
      </p>

      {estado === "nao_configurada" ? (
        <p className="rotulo mt-2">
          Sem credencial ou endereço definidos. Desligada por configuração, não
          é falha.
        </p>
      ) : estado === "sem_coleta" ? (
        <p className="rotulo mt-2">Ainda não coletou.</p>
      ) : (
        <dl className="mt-2 grid gap-1 text-sm">
          <div className="flex justify-between gap-2">
            <dt className="rotulo">última coleta</dt>
            <dd
              className="numero text-right"
              title={s.ultima_coleta ?? undefined}
            >
              {haTempo(s.ultima_coleta, agora)}
            </dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="rotulo">duração</dt>
            <dd className="numero text-right">
              {formatarDuracao(s.duracao_ms)}
            </dd>
          </div>
        </dl>
      )}

      {estado === "falha" && (
        <div className="mt-2 text-sm">
          <p className="text-erro">
            {s.indisponivel_desde
              ? `indisponível desde ${horaOuData(s.indisponivel_desde, agora)}`
              : "falhou na última coleta"}
          </p>
          {s.erro && (
            <p className="rotulo mt-1 break-words" title={s.erro}>
              {s.erro.length > 120 ? `${s.erro.slice(0, 120)}…` : s.erro}
            </p>
          )}
        </div>
      )}
    </li>
  );
}

function Saude({ agora, dados }: { agora: Date; dados: ConsoleSituacao[] }) {
  if (dados.length === 0) {
    return <Vazio titulo="Nenhuma origem reportada" />;
  }
  return (
    <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      {dados.map((s) => (
        <CartaoOrigem key={s.origem} s={s} agora={agora} />
      ))}
    </ul>
  );
}

// --------------------------------------------------------------------------
function Metricas({ linhas }: { linhas: Parameters<typeof agruparMetricas>[0] }) {
  const sistemas = agruparMetricas(linhas);
  if (sistemas.length === 0) {
    return (
      <Vazio
        titulo="Sem métricas nos últimos 7 dias"
        dica="O coletor só grava métricas de uma origem quando ela responde."
      />
    );
  }
  return (
    <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {sistemas.map((s) => {
        const fonte = s.fontes.join(" · ");
        return (
          <li
            key={s.sistema}
            className="border border-borda rounded p-3 bg-superficie flex flex-col"
          >
            <div className="flex items-center justify-between gap-2">
              <p className="font-medium">{s.sistema}</p>
              {s.situacao ? (
                <span
                  className={`inline-block rounded border px-2 py-0.5 text-xs ${SITUACAO_VISUAL[s.situacao]}`}
                >
                  {ROTULO_SITUACAO[s.situacao]}
                </span>
              ) : (
                <span className="rotulo">situação n/d</span>
              )}
            </div>
            <dl className="mt-2 grid gap-1 text-sm">
              <div className="flex justify-between gap-2">
                <dt className="rotulo">alertas ativos</dt>
                <dd className="numero">{s.alertasAtivos ?? "—"}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="rotulo">críticos</dt>
                <dd
                  className={`numero ${
                    (s.alertasCriticos ?? 0) > 0 ? "text-erro font-medium" : ""
                  }`}
                >
                  {s.alertasCriticos ?? "—"}
                </dd>
              </div>
            </dl>
            {/* A fonte fica visível, não escondida em tooltip: número sem
                procedência é o que este console existe para não mostrar. */}
            <p className="rotulo mt-auto pt-2 break-all" title={fonte}>
              dia {s.dia || "—"}
              {fonte && <> · fonte: {fonte}</>}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

// --------------------------------------------------------------------------
function Deploys({ linhas, agora }: { linhas: Parameters<typeof deploysRecentes>[0]; agora: Date }) {
  if (linhas.length === 0) {
    return (
      <Vazio
        titulo="Nenhum deploy registrado"
        dica="Vêm do Railway; sem CONSOLE_RAILWAY_TOKEN a origem fica não configurada."
      />
    );
  }
  const recentes = deploysRecentes(linhas);
  return (
    <>
      <Tabela
        legenda="Deploys recentes por sistema"
        colunas={["Sistema", "Ambiente", "Status", "Commit", "Quando"]}
      >
        {recentes.map((d, i) => (
          <tr key={d.deploy_id ?? i} className="border-b border-borda last:border-0">
            <td className="px-3 py-2 whitespace-nowrap">{d.sistema}</td>
            <td className="px-3 py-2 whitespace-nowrap">{d.ambiente ?? "—"}</td>
            <td className="px-3 py-2 whitespace-nowrap">
              {d.status ? (
                <span
                  className={`inline-block rounded border px-2 py-0.5 text-xs ${DEPLOY_VISUAL[tomDoDeploy(d.status)]}`}
                >
                  {d.status.toLowerCase()}
                </span>
              ) : (
                "—"
              )}
            </td>
            <td
              className="px-3 py-2 numero whitespace-nowrap"
              title={d.commit_sha ?? undefined}
            >
              {commitCurto(d.commit_sha)}
            </td>
            <td
              className="px-3 py-2 whitespace-nowrap"
              title={d.quando ?? undefined}
            >
              {haTempo(d.quando, agora)}
            </td>
          </tr>
        ))}
      </Tabela>
      {linhas.length > recentes.length && (
        <p className="rotulo mt-2">
          Mostrando {recentes.length} de {linhas.length}.
        </p>
      )}
    </>
  );
}

// --------------------------------------------------------------------------
function CartaoNumero(props: { rotulo: string; valor: string; nota?: string }) {
  return (
    <div className="border border-borda rounded p-3 bg-superficie">
      <p className="rotulo">{props.rotulo}</p>
      <p className="text-lg font-medium mt-1 numero">{props.valor}</p>
      {props.nota && <p className="rotulo mt-1">{props.nota}</p>}
    </div>
  );
}

// --------------------------------------------------------------------------
export function Console() {
  const situacao = useDados(() => api.consoleSituacao());
  const metricas = useDados(() => api.consoleMetricas(7));
  const deploys = useDados(() => api.consoleDeploys());
  const latencia = useDados(() => api.consoleLatencia());

  const [coletando, setColetando] = useState(false);
  const [erroColeta, setErroColeta] = useState<string | null>(null);
  const [avisoColeta, setAvisoColeta] = useState<string | null>(null);

  // `recarregar` é uma função nova a cada render; o intervalo lê a versão
  // corrente por ref para não ser recriado (e o relógio zerado) a cada tique.
  const recarregarTudo = () => {
    situacao.recarregar();
    metricas.recarregar();
    deploys.recarregar();
    latencia.recarregar();
  };
  const ref = useRef(recarregarTudo);
  ref.current = recarregarTudo;

  useEffect(() => {
    const id = window.setInterval(() => ref.current(), RECARGA_MS);
    return () => window.clearInterval(id);
  }, []);

  const coletarAgora = async () => {
    setColetando(true);
    setErroColeta(null);
    setAvisoColeta(null);
    try {
      await api.consoleColetar();
      setAvisoColeta(`Coleta disparada às ${horaOuData(new Date().toISOString())}.`);
      recarregarTudo();
    } catch (e) {
      setErroColeta(e instanceof Error ? e.message : String(e));
    } finally {
      setColetando(false);
    }
  };

  const agora = new Date();

  return (
    <div className="grid gap-8">
      <div className="flex flex-wrap items-center gap-3">
        <Botao variante="primario" aoClicar={coletarAgora} carregando={coletando}>
          Coletar agora
        </Botao>
        <p className="rotulo">Recarrega sozinho a cada 60 s.</p>
      </div>
      {avisoColeta && (
        <p role="status" className="text-sm -mt-5">
          {avisoColeta}
        </p>
      )}
      {erroColeta && (
        <div className="-mt-5">
          <Erro mensagem={`A coleta não foi disparada: ${erroColeta}`} />
        </div>
      )}

      <Secao
        id="saude"
        titulo="Saúde das origens"
        nota="Resultado da última coleta de cada origem. Não configurada é neutro: a origem está desligada, não caiu."
        erro={situacao.erro}
        temDados={!!situacao.dados}
      >
        {situacao.carregando && !situacao.dados ? (
          <Carregando oque="origens" />
        ) : situacao.dados ? (
          <Saude agora={agora} dados={situacao.dados.dados} />
        ) : null}
      </Secao>

      <Secao
        id="metricas"
        titulo="Métricas do dia por sistema"
        nota="Valor mais recente dos últimos 7 dias, do envelope de observabilidade de cada sistema."
        erro={metricas.erro}
        temDados={!!metricas.dados}
      >
        {metricas.carregando && !metricas.dados ? (
          <Carregando oque="métricas" />
        ) : metricas.dados ? (
          <Metricas linhas={metricas.dados.dados} />
        ) : null}
      </Secao>

      <Secao
        id="deploys"
        titulo="Deploys recentes"
        erro={deploys.erro}
        temDados={!!deploys.dados}
      >
        {deploys.carregando && !deploys.dados ? (
          <Carregando oque="deploys" />
        ) : deploys.dados ? (
          <Deploys linhas={deploys.dados.dados} agora={agora} />
        ) : null}
      </Secao>

      <Secao
        id="latencia"
        titulo="Latência da própria console"
        nota="Rotas de /admin/api/console/*, desde o último início do processo. O p95 é o critério objetivo para extrair a console (spec §1, §9)."
        erro={latencia.erro}
        temDados={!!latencia.dados}
      >
        {latencia.carregando && !latencia.dados ? (
          <Carregando oque="latência" />
        ) : latencia.dados ? (
          <div className="grid gap-3 grid-cols-1 sm:grid-cols-3">
            <CartaoNumero rotulo="p50" valor={formatarMs(latencia.dados.dados.p50_ms)} />
            <CartaoNumero rotulo="p95" valor={formatarMs(latencia.dados.dados.p95_ms)} />
            <CartaoNumero
              rotulo="chamadas medidas"
              valor={latencia.dados.dados.contagem.toLocaleString("pt-BR")}
              nota={
                latencia.dados.dados.contagem === 0
                  ? "sem amostra ainda: p50 e p95 ficam em branco"
                  : undefined
              }
            />
          </div>
        ) : null}
      </Secao>

      {/* Sem número: as duas fontes ainda não existem. Mostrar zero ou um
          valor de exemplo aqui faria falta de medida parecer medida. */}
      <section aria-labelledby="construir">
        <h2 id="construir" className="font-medium">
          A construir
        </h2>
        <p className="rotulo mb-3">
          Blocos da spec que ainda não têm fonte de dados. Nenhum número é
          exibido até existirem.
        </p>
        <ul className="grid gap-3 sm:grid-cols-2">
          <li className="border border-dashed border-borda rounded p-3">
            <p className="font-medium">Custo do mês e tendência (§3b)</p>
            <p className="text-sm text-tinta-suave mt-1">
              Infra: o Railway MCP não expõe fatura; depende de habilitar
              usage/estimatedUsage ou export manual (§10.2). Tokens: depende da
              série do Boris+ e, para o valor real, da Admin API da Anthropic
              (§10.2). Até lá, sem fatura e sem estimativa.
            </p>
          </li>
          <li className="border border-dashed border-borda rounded p-3">
            <p className="font-medium">Recomendações de economia (§3e)</p>
            <p className="text-sm text-tinta-suave mt-1">
              Lê a fila <span className="numero">console_recomendacao</span>,
              produzida pelo motor de §7. O motor e a fila ainda não estão
              expostos nesta tela.
            </p>
          </li>
        </ul>
      </section>
    </div>
  );
}
