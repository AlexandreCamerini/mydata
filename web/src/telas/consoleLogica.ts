// A lógica pura da tela Console: o que ela afirma sobre cada origem.
//
// Separada do componente pelo mesmo motivo de objetos.ts: cada função aqui
// decide uma frase da tela. Classificar "não configurada" como falha pinta de
// vermelho uma origem que o dono desligou de propósito; um "há 3 min" calculado
// sobre data sem fuso desloca o relógio em horas. Nada aqui toca em DOM, fetch
// ou relógio global — `agora` sempre entra por parâmetro.
import type { ConsoleDeploy, ConsoleMetrica, ConsoleSituacao } from "../api";

// --------------------------------------------------------------------------
// Semáforo da origem

/** Quatro estados, não três: "sem coleta" (a origem está configurada mas
 * ainda não rodou) não é sucesso nem falha, e chamá-la de qualquer um dos dois
 * seria afirmar o que não se mediu. É neutro, como "não configurada". */
export type EstadoOrigem = "ok" | "falha" | "nao_configurada" | "sem_coleta";

export function classificarOrigem(
  s: Pick<ConsoleSituacao, "configurada" | "ok" | "ultima_coleta">,
): EstadoOrigem {
  // `configurada` vem primeiro: uma origem desligada por configuração tem
  // `ok=false` na última linha de console_coleta, e olhar `ok` antes a
  // faria parecer falha.
  if (!s.configurada) return "nao_configurada";
  if (s.ultima_coleta === null || s.ok === null || s.ok === undefined) {
    return "sem_coleta";
  }
  return s.ok ? "ok" : "falha";
}

export const ROTULO_ORIGEM: Record<EstadoOrigem, string> = {
  ok: "ok",
  falha: "falha",
  nao_configurada: "não configurada",
  sem_coleta: "sem coleta",
};

// --------------------------------------------------------------------------
// Tempo

/** ISO do backend -> Date. O backend pode mandar "2026-09-28 10:00:00" (sem
 * fuso, separador de espaço) conforme o banco; tudo em console_* é gravado em
 * UTC, então ausência de fuso significa UTC, não hora local. */
export function parseInstante(bruto: string | null | undefined): Date | null {
  if (!bruto) return null;
  let t = bruto.trim().replace(" ", "T");
  if (/^\d{4}-\d{2}-\d{2}$/.test(t)) t += "T00:00:00";
  if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(t)) t += "Z";
  const d = new Date(t);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "agora há pouco", "há 3 min", "há 2 h", "há 4 d". Nulo/ilegível -> "—":
 * nunca inventa um instante. Futuro (relógios levemente fora de sincronia) é
 * tratado como "agora há pouco" em vez de um "há -2 min". */
export function haTempo(
  bruto: string | null | undefined,
  agora: Date = new Date(),
): string {
  const d = parseInstante(bruto);
  if (!d) return "—";
  const seg = Math.floor((agora.getTime() - d.getTime()) / 1000);
  if (seg < 60) return "agora há pouco";
  const min = Math.floor(seg / 60);
  if (min < 60) return `há ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `há ${h} h`;
  return `há ${Math.floor(h / 24)} d`;
}

const doisDigitos = (n: number) => String(n).padStart(2, "0");

/** "14:32" no mesmo dia; "27/09 14:32" em outro. Hora local de quem olha. */
export function horaOuData(
  bruto: string | null | undefined,
  agora: Date = new Date(),
): string {
  const d = parseInstante(bruto);
  if (!d) return "—";
  const hora = `${doisDigitos(d.getHours())}:${doisDigitos(d.getMinutes())}`;
  const mesmoDia =
    d.getFullYear() === agora.getFullYear() &&
    d.getMonth() === agora.getMonth() &&
    d.getDate() === agora.getDate();
  return mesmoDia
    ? hora
    : `${doisDigitos(d.getDate())}/${doisDigitos(d.getMonth() + 1)} ${hora}`;
}

// --------------------------------------------------------------------------
// Números

/** Duração de coleta: "—" quando não medida (nulo não é zero), "850 ms" abaixo
 * de um segundo, "1,3 s" acima. */
export function formatarDuracao(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toLocaleString("pt-BR", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })} s`;
}

/** Latência da própria console (p50/p95). Sem amostra o backend devolve nulo,
 * e o traço diz "sem medida" — zero diria "instantâneo". */
export function formatarMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "—";
  return `${ms.toLocaleString("pt-BR", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
  })} ms`;
}

/** Sete primeiros caracteres do SHA, como o git abrevia. */
export function commitCurto(sha: string | null | undefined): string {
  const s = (sha ?? "").trim();
  return s ? s.slice(0, 7) : "—";
}

// --------------------------------------------------------------------------
// Métricas do dia

export type SituacaoEnvelope = "ok" | "atencao" | "critico";

export type MetricasDoSistema = {
  sistema: string;
  /** O dia (YYYY-MM-DD) mais recente entre as métricas exibidas. */
  dia: string;
  situacao: SituacaoEnvelope | null;
  /** `null` = a métrica não veio; nunca vira 0. */
  alertasAtivos: number | null;
  alertasCriticos: number | null;
  /** Fontes distintas, para o rodapé/tooltip. */
  fontes: string[];
};

function inteiro(valor: string | undefined): number | null {
  if (valor === undefined || valor.trim() === "") return null;
  const n = Number(valor);
  return Number.isInteger(n) && n >= 0 ? n : null;
}

/** Uma linha por sistema com o valor MAIS RECENTE de cada métrica na janela.
 * O endpoint devolve a janela inteira (`dias=7`) ordenada por dia decrescente;
 * aqui vale o primeiro valor visto de cada (sistema, métrica) — não depende da
 * ordem de entrada, compara `dia` explicitamente. */
export function agruparMetricas(linhas: ConsoleMetrica[]): MetricasDoSistema[] {
  const maisRecente = new Map<string, ConsoleMetrica>();
  for (const l of linhas) {
    const chave = `${l.sistema}\u0000${l.metrica}`;
    const atual = maisRecente.get(chave);
    if (!atual || l.dia > atual.dia) maisRecente.set(chave, l);
  }

  const porSistema = new Map<string, Map<string, ConsoleMetrica>>();
  for (const l of maisRecente.values()) {
    const m = porSistema.get(l.sistema) ?? new Map();
    m.set(l.metrica, l);
    porSistema.set(l.sistema, m);
  }

  return [...porSistema.entries()]
    .map(([sistema, m]) => {
      const sit = m.get("situacao")?.valor;
      const situacao: SituacaoEnvelope | null =
        sit === "ok" || sit === "atencao" || sit === "critico" ? sit : null;
      const usadas = ["situacao", "alertas_ativos", "alertas_criticos"]
        .map((k) => m.get(k))
        .filter((x): x is ConsoleMetrica => x !== undefined);
      return {
        sistema,
        dia: usadas.map((u) => u.dia).sort().at(-1) ?? "",
        situacao,
        alertasAtivos: inteiro(m.get("alertas_ativos")?.valor),
        alertasCriticos: inteiro(m.get("alertas_criticos")?.valor),
        fontes: [...new Set(usadas.map((u) => u.fonte).filter(Boolean))],
      };
    })
    .sort((a, b) => a.sistema.localeCompare(b.sistema));
}

export const ROTULO_SITUACAO: Record<SituacaoEnvelope, string> = {
  ok: "ok",
  atencao: "atenção",
  critico: "crítico",
};

// --------------------------------------------------------------------------
// Deploys

export type TomDeploy = "ok" | "erro" | "andamento" | "neutro";

/** Status do Railway (SUCCESS, FAILED, CRASHED, BUILDING…) -> tom visual. O
 * texto exibido continua sendo o status original: o tom é só reforço. */
export function tomDoDeploy(status: string | null | undefined): TomDeploy {
  switch ((status ?? "").toUpperCase()) {
    case "SUCCESS":
      return "ok";
    case "FAILED":
    case "CRASHED":
      return "erro";
    case "BUILDING":
    case "DEPLOYING":
    case "INITIALIZING":
    case "QUEUED":
    case "WAITING":
    case "NEEDS_APPROVAL":
      return "andamento";
    default:
      return "neutro";
  }
}

/** Mais recentes primeiro, no máximo `limite`. Não confia na ordem do backend
 * (que pode mudar) e põe deploy sem data por último em vez de escondê-lo. */
export function deploysRecentes(
  linhas: ConsoleDeploy[],
  limite = 15,
): ConsoleDeploy[] {
  const t = (d: ConsoleDeploy) => parseInstante(d.quando)?.getTime() ?? -Infinity;
  // Comparação explícita: -Infinity - -Infinity é NaN e quebraria o sort.
  return [...linhas]
    .sort((a, b) => (t(a) === t(b) ? 0 : t(b) > t(a) ? 1 : -1))
    .slice(0, limite);
}
