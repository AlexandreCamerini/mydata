// Os objetos de observabilidade da etapa 5 de docs/direcao-apresentacao.md.
//
// Todos recebem dado por prop e nenhum busca nada. A razão é concreta: existem
// dois bundles — `src/` (plano de controle) e `src/apresentacao/` — com dois
// módulos `api` diferentes. Um objeto que buscasse por conta própria teria de
// escolher um dos dois, e deixaria de ser reutilizável exatamente na fronteira
// que ele existe para atravessar. Quem busca é a tela; o objeto desenha.
//
// A aritmética de cada um sai como função pura exportada, para caber em teste
// sem navegador — foi assim que os dois defeitos da noite anterior viraram
// regressão.
import { type ReactNode, useState } from "react";
import { Selo, Tabela } from "./ui";

const fmt = new Intl.NumberFormat("pt-BR");

/** Data absoluta ao lado da relativa.
 *
 * "Atualizada há 5 h" é bom para leitura rápida e péssimo para conferência —
 * achado 2.4 da auditoria. O relativo continua visível; o absoluto entra no
 * `title`, que é onde ele não atrapalha a varredura. */
export function instante(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("pt-BR");
}

export function bytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n < 1024) return `${n} B`;
  const unidades = ["kB", "MB", "GB", "TB"];
  let valor = n / 1024;
  let i = 0;
  while (valor >= 1024 && i < unidades.length - 1) {
    valor /= 1024;
    i += 1;
  }
  return `${valor.toFixed(valor < 10 ? 1 : 0)} ${unidades[i]}`;
}

// ---------------------------------------------------------------------------
// 3.2 · SaudeClasse
// ---------------------------------------------------------------------------

export type SaudeDaClasse = {
  chave: string;
  nome: string;
  tabela: string;
  fontes: string[];
  // Volume é opcional porque nem toda origem o conhece: `/v1/meta/frescor`
  // responde idade e situação, e a contagem por tabela só existe em
  // `/admin/api/gestao`. Ausente some da tela; imprimir zero faria "não sei"
  // parecer "nenhuma linha", que é a leitura errada.
  linhas?: number | null;
  linhas_publicadas?: number | null;
  retidas_no_gate?: number | null;
  sla_horas: number | null;
  idade_horas: number | null;
  situacao: string | null;
  ultima_publicacao: { id: number; terminado_em: string | null } | null;
  ultima_falha: {
    id: number;
    dataset_chave: string;
    status: string;
    erro: string | null;
    terminado_em: string | null;
  } | null;
};

/** Quanto do SLA a classe já consumiu, entre 0 e 1 (satura em 1).
 *
 * Sem SLA declarado não há fração: devolve `null`, e a barra não é desenhada.
 * Inventar 100% para "sem SLA" faria classe sem prazo parecer classe vencida. */
export function fracaoDoSla(
  idadeHoras: number | null | undefined,
  slaHoras: number | null | undefined,
): number | null {
  if (idadeHoras == null || !slaHoras) return null;
  return Math.min(1, Math.max(0, idadeHoras / slaHoras));
}

/** Idade em texto, na unidade que a magnitude pede. */
export function idadeTexto(horas: number | null | undefined): string {
  if (horas == null) return "sem carga";
  if (horas < 1) return `${Math.round(horas * 60)} min`;
  if (horas < 48) return `${Math.round(horas)} h`;
  return `${Math.round(horas / 24)} d`;
}

/** Painel de saúde de uma classe.
 *
 * A publicação e a falha aparecem **lado a lado**, não uma no lugar da outra:
 * uma classe pode estar em dia e ter quebrado ontem, e ver só a primeira faz
 * a segunda desaparecer. Foi o que a auditoria pediu no achado 3.2 da direção. */
export function SaudeClasse({
  c,
  acao,
}: {
  c: SaudeDaClasse;
  acao?: ReactNode;
}) {
  const fracao = fracaoDoSla(c.idade_horas, c.sla_horas);
  const vencido = fracao !== null && fracao >= 1;

  return (
    <section
      aria-labelledby={`saude-${c.chave}`}
      className="border border-borda rounded bg-superficie p-4 grid gap-3"
    >
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 id={`saude-${c.chave}`} className="font-medium">
            {c.nome}
          </h3>
          <p className="text-xs text-tinta-suave font-mono">{c.tabela}</p>
        </div>
        <div className="flex items-center gap-2">
          <Selo texto={c.situacao ?? "sem_carga"} />
          {acao}
        </div>
      </div>

      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
        {c.linhas_publicadas != null && (
          <div>
            <dt className="text-xs text-tinta-suave">Publicadas</dt>
            <dd className="numero">{fmt.format(c.linhas_publicadas)}</dd>
          </div>
        )}
        {c.retidas_no_gate != null && (
          <div>
            <dt className="text-xs text-tinta-suave">Retidas no gate</dt>
            <dd className="numero">
              {c.retidas_no_gate ? fmt.format(c.retidas_no_gate) : "—"}
            </dd>
          </div>
        )}
        <div>
          <dt className="text-xs text-tinta-suave">Fontes</dt>
          <dd className="text-xs">{c.fontes.join(", ") || "—"}</dd>
        </div>
        <div>
          <dt className="text-xs text-tinta-suave">Idade</dt>
          <dd
            className="text-xs"
            title={instante(c.ultima_publicacao?.terminado_em) || undefined}
          >
            {idadeTexto(c.idade_horas)}
            {/* "sem carga de 960 h" não quer dizer nada: o prazo se conta a
                partir de uma publicação que nunca houve. */}
            {c.sla_horas && c.idade_horas != null ? (
              <span className="text-tinta-suave"> de {c.sla_horas} h</span>
            ) : null}
          </dd>
        </div>
      </dl>

      {fracao !== null && (
        <div
          role="img"
          aria-label={`${Math.round(fracao * 100)}% do SLA de ${c.sla_horas} horas consumido`}
          className="h-1.5 rounded bg-borda overflow-hidden"
        >
          <div
            className={`h-full ${vencido ? "bg-erro" : "bg-acento"}`}
            style={{ width: `${Math.max(2, fracao * 100)}%` }}
          />
        </div>
      )}

      {/* Duas colunas, sempre as duas. */}
      <div className="grid sm:grid-cols-2 gap-3 text-xs">
        <p>
          <span className="text-tinta-suave">Última publicação: </span>
          {c.ultima_publicacao ? (
            <span title={instante(c.ultima_publicacao.terminado_em) || undefined}>
              #{c.ultima_publicacao.id}
              {c.ultima_publicacao.terminado_em && (
                <> · {c.ultima_publicacao.terminado_em.slice(0, 16).replace("T", " ")}</>
              )}
            </span>
          ) : (
            <span className="text-tinta-suave">nenhuma</span>
          )}
        </p>
        <p>
          <span className="text-tinta-suave">Última falha: </span>
          {c.ultima_falha ? (
            <span className="text-alerta">
              #{c.ultima_falha.id} · {c.ultima_falha.dataset_chave} ·{" "}
              {c.ultima_falha.status}
              {c.ultima_falha.erro && (
                <span className="block break-words">{c.ultima_falha.erro}</span>
              )}
            </span>
          ) : (
            <span className="text-tinta-suave">nenhuma</span>
          )}
        </p>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// 3.3 · Linhagem
// ---------------------------------------------------------------------------

export type CapturaLinhagem = {
  id: number;
  nome_arquivo: string;
  url: string | null;
  sha256: string;
  capturado_em: string;
  tamanho_bytes: number | null;
};

export type OrigemDeLinhagem = {
  dataset: string;
  fonte: { chave: string; url_template: string | null };
  coluna_de_origem: string | null;
  formato: string | null;
  expressao: string | null;
  colunas_que_usa: string[];
  capturas_recentes: CapturaLinhagem[];
  regras: { nome: string; severidade: string; descricao: string | null }[];
};

export type LinhagemDeAtributo = {
  classe: string;
  atributo: string;
  tipo: string;
  descricao: string | null;
  disputado: boolean;
  precedencia: string[];
  origens: OrigemDeLinhagem[];
  vistas: string[];
  publicacao_atual: number | null;
};

/** O endereço do arquivo como a fonte publicou.
 *
 * A auditoria mediu que `arquivo_em` aparecia zero vezes no front (achado
 * 3.3): a promessa de proveniência auditável parava um clique antes do fim.
 * A rota existe desde sempre — o que faltava era alguém apontar para ela. */
export function arquivoDaCaptura(id: number): string {
  return `/v1/capturas/${id}/arquivo`;
}

/** A cadeia de um atributo até o arquivo original. */
export function Linhagem({ l }: { l: LinhagemDeAtributo }) {
  return (
    <div className="border border-borda rounded bg-superficie p-4 grid gap-4">
      <p className="text-sm">
        <span className="font-mono">
          {l.classe}.{l.atributo}
        </span>{" "}
        <span className="text-tinta-suave">({l.tipo})</span>
        {l.descricao && (
          <span className="block text-xs text-tinta-suave mt-1">{l.descricao}</span>
        )}
      </p>

      {l.disputado ? (
        <p className="text-sm">
          Atributo <strong>disputado</strong> — {l.origens.length} fontes o
          alimentam; vence a primeira com valor na ordem:{" "}
          <span className="font-mono">{l.precedencia.join(" › ")}</span>
        </p>
      ) : (
        <p className="text-sm text-tinta-suave">
          Sem disputa:{" "}
          {l.precedencia.length <= 1
            ? "uma fonte alimenta este atributo"
            : "as fontes nunca produzem a mesma linha"}
          .
        </p>
      )}

      <ol className="grid gap-3 list-none p-0 m-0">
        {l.origens.map((o, i) => (
          <li key={o.dataset} className="border border-borda rounded p-3">
            <p className="text-sm font-medium">
              {i + 1}º <span className="font-mono">{o.dataset}</span>
              <span className="text-tinta-suave font-normal"> · fonte {o.fonte.chave}</span>
            </p>
            <dl className="text-xs grid sm:grid-cols-2 gap-x-6 gap-y-1 mt-2">
              {o.coluna_de_origem && (
                <div>
                  <dt className="text-tinta-suave inline">Coluna do arquivo: </dt>
                  <dd className="inline font-mono">
                    {o.coluna_de_origem}
                    {o.formato && ` (${o.formato})`}
                  </dd>
                </div>
              )}
              {o.expressao && (
                <div className="sm:col-span-2">
                  <dt className="text-tinta-suave inline">Calculado por: </dt>
                  <dd className="inline font-mono">{o.expressao}</dd>
                  {o.colunas_que_usa.length > 0 && (
                    <span className="text-tinta-suave">
                      {" "}
                      — usa {o.colunas_que_usa.join(", ")}
                    </span>
                  )}
                </div>
              )}
              {o.fonte.url_template && (
                <div className="sm:col-span-2">
                  <dt className="text-tinta-suave inline">Origem oficial: </dt>
                  <dd className="inline font-mono break-all">{o.fonte.url_template}</dd>
                </div>
              )}
              <div className="sm:col-span-2">
                <dt className="text-tinta-suave inline">Regras que vigiam: </dt>
                <dd className="inline">
                  {o.regras.length === 0
                    ? "nenhuma"
                    : o.regras
                        .map((r) => `${r.nome} (${r.severidade})`)
                        .join(", ")}
                </dd>
              </div>
            </dl>

            {o.capturas_recentes.length > 0 && (
              <div className="mt-3">
                <p className="text-xs text-tinta-suave mb-1">
                  Capturas recentes — o arquivo como a fonte publicou, conferível
                  pelo sha256:
                </p>
                <Tabela
                  legenda={`Capturas de ${o.dataset}`}
                  colunas={["Arquivo", "Quando", "Tamanho", "sha256", ""]}
                >
                  {o.capturas_recentes.map((cap) => (
                    <tr key={cap.id} className="border-b border-borda last:border-0">
                      <th scope="row" className="text-left px-3 py-1.5 font-mono text-xs break-all">
                        {cap.nome_arquivo}
                      </th>
                      <td
                        className="px-3 py-1.5 text-xs whitespace-nowrap"
                        title={instante(cap.capturado_em)}
                      >
                        {cap.capturado_em.slice(0, 16).replace("T", " ")}
                      </td>
                      <td className="px-3 py-1.5 text-xs numero text-right">
                        {bytes(cap.tamanho_bytes)}
                      </td>
                      <td className="px-3 py-1.5 text-xs font-mono" title={cap.sha256}>
                        {cap.sha256.slice(0, 12)}…
                      </td>
                      <td className="px-3 py-1.5 text-xs">
                        <a
                          className="text-acento underline"
                          href={arquivoDaCaptura(cap.id)}
                          download={cap.nome_arquivo}
                        >
                          Baixar o original
                          <span className="sr-only"> de {cap.nome_arquivo}</span>
                        </a>
                      </td>
                    </tr>
                  ))}
                </Tabela>
              </div>
            )}
          </li>
        ))}
      </ol>

      <p className="text-xs text-tinta-suave">
        Publicado pelas vistas {l.vistas.join(", ") || "—"} · publicação atual v
        {l.publicacao_atual ?? "—"}.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 3.4 · LinhaDoTempo
// ---------------------------------------------------------------------------

export type Fase = {
  fase: string;
  iniciado_em: string;
  terminado_em: string | null;
  duracao_ms: number | null;
};

/** Cada fase com sua fatia do total, do mais caro para o mais barato na
 * leitura — mas na ordem cronológica, que é a que explica o encadeamento.
 *
 * Foi olhando a proporção que os 119 s da fase `calcular` apareceram: a lista
 * de números dizia "119500 ms" com a mesma tipografia com que dizia "12 ms". */
export function proporcoes(
  fases: Pick<Fase, "fase" | "duracao_ms">[],
): { fase: string; ms: number; fracao: number }[] {
  const total = fases.reduce((s, f) => s + (f.duracao_ms ?? 0), 0);
  return fases.map((f) => ({
    fase: f.fase,
    ms: f.duracao_ms ?? 0,
    fracao: total > 0 ? (f.duracao_ms ?? 0) / total : 0,
  }));
}

export function LinhaDoTempo({ fases }: { fases: Fase[] }) {
  if (fases.length === 0)
    return <p className="text-sm text-tinta-suave">Sem fases registradas.</p>;

  const linhas = proporcoes(fases);
  const total = linhas.reduce((s, l) => s + l.ms, 0);
  const maior = linhas.reduce((a, b) => (b.fracao > a.fracao ? b : a), linhas[0]);

  return (
    <div className="grid gap-2 max-w-2xl">
      <div
        role="img"
        aria-label={`Fases da execução: ${linhas
          .map((l) => `${l.fase} ${l.ms} ms`)
          .join(", ")}. Total ${total} ms.`}
        className="grid gap-1"
      >
        {linhas.map((l) => (
          <div
            key={l.fase}
            className="grid grid-cols-[110px_1fr_110px] gap-2 items-center text-xs"
          >
            <span className="font-mono truncate">{l.fase}</span>
            <span className="bg-papel border border-borda rounded h-4 overflow-hidden">
              <span
                className={`block h-full ${l === maior ? "bg-acento" : "bg-tinta-suave"}`}
                style={{ width: `${Math.max(1, l.fracao * 100)}%` }}
              />
            </span>
            <span className="text-right numero">
              {l.ms} ms
              <span className="text-tinta-suave"> · {Math.round(l.fracao * 100)}%</span>
            </span>
          </div>
        ))}
      </div>
      <p className="text-xs text-tinta-suave">
        Total {total} ms. A fase mais cara é <strong>{maior.fase}</strong>, com{" "}
        {Math.round(maior.fracao * 100)}% do tempo.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 3.5 · Serie
// ---------------------------------------------------------------------------

export type Ponto = { rotulo: string; valor: number | null };

/** Os pontos em coordenadas do viewBox, com os nulos preservados como nulos.
 *
 * Nulo aqui não é zero: bytes de disco só o Postgres responde, e no DuckDB
 * local a medida não existe. Uma série que desenhasse zero faria falta de
 * medida parecer ausência de custo — a mesma leitura errada que o traço da
 * tela de carga já evita. O caminho é quebrado no nulo, e o buraco fica
 * visível. */
export function caminho(
  pontos: Ponto[],
  largura: number,
  altura: number,
): { d: string; min: number; max: number } {
  const valores = pontos
    .map((p) => p.valor)
    .filter((v): v is number => v !== null && Number.isFinite(v));
  if (valores.length === 0) return { d: "", min: 0, max: 0 };

  const max = Math.max(...valores);
  // A escala nasce no zero, não no mínimo. Um eixo que começa no mínimo
  // transforma variação de 1% em montanha — é a forma mais barata de mentir
  // com um gráfico honesto.
  const min = 0;
  const amplitude = max - min || 1;
  const passo = pontos.length > 1 ? largura / (pontos.length - 1) : 0;

  let d = "";
  let caneta = false;
  pontos.forEach((p, i) => {
    if (p.valor === null || !Number.isFinite(p.valor)) {
      caneta = false;
      return;
    }
    const x = i * passo;
    const y = altura - ((p.valor - min) / amplitude) * altura;
    d += `${caneta ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)} `;
    caneta = true;
  });
  return { d: d.trim(), min, max };
}

/** Uma série no tempo, em SVG próprio.
 *
 * Sem biblioteca de gráfico: são quatro séries simples, e uma dependência de
 * runtime para desenhar uma polilinha custaria mais do que a polilinha. */
export function Serie({
  titulo,
  pontos,
  formatar,
  nota,
}: {
  titulo: string;
  pontos: Ponto[];
  formatar: (n: number) => string;
  nota?: string;
}) {
  const L = 320;
  const A = 64;
  const { d, max } = caminho(pontos, L, A);
  const medidos = pontos.filter((p) => p.valor !== null);
  const ultimo = medidos.at(-1)?.valor ?? null;
  const primeiro = medidos.at(0)?.valor ?? null;

  return (
    <figure className="border border-borda rounded bg-superficie p-3 m-0 grid gap-2">
      <figcaption className="text-xs text-tinta-suave">{titulo}</figcaption>
      {d === "" ? (
        <p className="text-sm text-tinta-suave">Sem medida nesta janela.</p>
      ) : (
        <>
          <svg
            viewBox={`0 0 ${L} ${A}`}
            preserveAspectRatio="none"
            className="w-full h-16"
            role="img"
            aria-label={`${titulo}: de ${primeiro !== null ? formatar(primeiro) : "sem medida"} a ${
              ultimo !== null ? formatar(ultimo) : "sem medida"
            }, máximo ${formatar(max)}, em ${medidos.length} de ${pontos.length} cargas medidas.`}
          >
            <path
              d={d}
              fill="none"
              stroke="var(--color-acento)"
              strokeWidth="1.5"
              vectorEffect="non-scaling-stroke"
            />
          </svg>
          <p className="text-sm numero">
            {ultimo !== null ? formatar(ultimo) : "—"}
            <span className="text-xs text-tinta-suave">
              {" "}
              · máx {formatar(max)}
              {medidos.length < pontos.length && (
                <> · {pontos.length - medidos.length} sem medida</>
              )}
            </span>
          </p>
        </>
      )}
      {nota && <p className="text-xs text-tinta-suave">{nota}</p>}
    </figure>
  );
}

// ---------------------------------------------------------------------------
// Um auxiliar de tela que não é objeto gráfico, mas mora com eles: o
// desdobrável que só busca quando abre. Linhagem por atributo em `Classes` são
// quarenta chamadas se todas dispararem na montagem.
// ---------------------------------------------------------------------------
export function AoAbrir({
  rotulo,
  children,
}: {
  rotulo: ReactNode;
  children: () => ReactNode;
}) {
  const [aberto, setAberto] = useState(false);
  return (
    <>
      <button
        onClick={() => setAberto((v) => !v)}
        aria-expanded={aberto}
        className="text-left underline decoration-dotted"
      >
        {rotulo}
      </button>
      {aberto && <div className="mt-3">{children()}</div>}
    </>
  );
}
