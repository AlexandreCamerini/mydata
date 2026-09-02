// Primitivas acessíveis. Escritas à mão em vez de uma biblioteca de
// componentes: são poucas, os requisitos de acessibilidade são o critério de
// aceite (então precisam ser explícitos, não herdados), e cada dependência a
// menos é build mais rápido e imagem menor.
import {
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";

// --------------------------------------------------------------------------
export function Campo(props: {
  rotulo: string;
  valor: string;
  aoMudar: (v: string) => void;
  erro?: string | null;
  ajuda?: string;
  tipo?: string;
  placeholder?: string;
  obrigatorio?: boolean;
  monoespacado?: boolean;
  multilinha?: boolean;
}) {
  const id = useId();
  const idErro = `${id}-erro`;
  const idAjuda = `${id}-ajuda`;
  const descritores = [props.ajuda ? idAjuda : null, props.erro ? idErro : null]
    .filter(Boolean)
    .join(" ");

  const comum = {
    id,
    value: props.valor,
    onChange: (e: { target: { value: string } }) => props.aoMudar(e.target.value),
    "aria-invalid": props.erro ? true : undefined,
    "aria-describedby": descritores || undefined,
    "aria-required": props.obrigatorio || undefined,
    placeholder: props.placeholder,
    className: `w-full rounded border px-3 py-2 text-sm bg-superficie ${
      props.erro ? "border-erro" : "border-borda"
    } ${props.monoespacado ? "font-mono" : ""}`,
  };

  return (
    <div className="mb-4">
      <label htmlFor={id} className="block text-sm font-medium mb-1">
        {props.rotulo}
        {props.obrigatorio && (
          <span className="text-erro ml-1" aria-hidden="true">
            *
          </span>
        )}
      </label>
      {props.multilinha ? (
        <textarea {...comum} rows={3} />
      ) : (
        <input {...comum} type={props.tipo ?? "text"} />
      )}
      {props.ajuda && (
        <p id={idAjuda} className="text-xs text-tinta-suave mt-1">
          {props.ajuda}
        </p>
      )}
      {/* O erro fica ao lado do campo que o causou, não num toast distante. */}
      {props.erro && (
        <p id={idErro} className="text-sm text-erro mt-1" role="alert">
          {props.erro}
        </p>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
export function Selecao(props: {
  rotulo: string;
  valor: string;
  aoMudar: (v: string) => void;
  opcoes: { valor: string; rotulo: string }[];
  ajuda?: string;
}) {
  const id = useId();
  const idAjuda = `${id}-ajuda`;
  return (
    <div className="mb-4">
      <label htmlFor={id} className="block text-sm font-medium mb-1">
        {props.rotulo}
      </label>
      <select
        id={id}
        value={props.valor}
        onChange={(e) => props.aoMudar(e.target.value)}
        aria-describedby={props.ajuda ? idAjuda : undefined}
        className="w-full rounded border border-borda px-3 py-2 text-sm bg-superficie"
      >
        {props.opcoes.map((o) => (
          <option key={o.valor} value={o.valor}>
            {o.rotulo}
          </option>
        ))}
      </select>
      {props.ajuda && (
        <p id={idAjuda} className="text-xs text-tinta-suave mt-1">
          {props.ajuda}
        </p>
      )}
    </div>
  );
}

export function Caixa(props: {
  rotulo: string;
  marcado: boolean;
  aoMudar: (v: boolean) => void;
  ajuda?: string;
}) {
  const id = useId();
  const idAjuda = `${id}-ajuda`;
  return (
    <div className="mb-2">
      <label htmlFor={id} className="inline-flex items-center gap-2 text-sm">
        <input
          id={id}
          type="checkbox"
          checked={props.marcado}
          onChange={(e) => props.aoMudar(e.target.checked)}
          aria-describedby={props.ajuda ? idAjuda : undefined}
          className="rounded border-borda"
        />
        {props.rotulo}
      </label>
      {props.ajuda && (
        <p id={idAjuda} className="text-xs text-tinta-suave mt-0.5 ml-6">
          {props.ajuda}
        </p>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
export function Botao(props: {
  children: ReactNode;
  aoClicar?: () => void;
  variante?: "primario" | "secundario" | "destrutivo";
  tipo?: "button" | "submit";
  desabilitado?: boolean;
  carregando?: boolean;
}) {
  const estilos = {
    // O acento existe para dizer "isto aqui é a ação". Antes era tinta —
    // mesma cor do texto —, e por isso nada competia pela atenção.
    primario: "bg-acento text-papel hover:opacity-90",
    secundario: "bg-superficie text-tinta border border-borda hover:bg-acento-suave",
    destrutivo: "bg-erro text-papel hover:opacity-90",
  }[props.variante ?? "secundario"];

  return (
    <button
      type={props.tipo ?? "button"}
      onClick={props.aoClicar}
      disabled={props.desabilitado || props.carregando}
      aria-busy={props.carregando || undefined}
      className={`rounded px-3 py-2 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed ${estilos}`}
    >
      {props.carregando ? "Processando…" : props.children}
    </button>
  );
}

// --------------------------------------------------------------------------
export function Carregando({ oque }: { oque: string }) {
  return (
    <div role="status" className="py-8 text-center text-tinta-suave text-sm">
      <span className="inline-block animate-pulse">Carregando {oque}…</span>
    </div>
  );
}

export function Vazio({ titulo, dica }: { titulo: string; dica?: string }) {
  return (
    <div className="py-10 text-center border border-dashed border-borda rounded">
      <p className="font-medium">{titulo}</p>
      {dica && <p className="text-sm text-tinta-suave mt-1">{dica}</p>}
    </div>
  );
}

export function Erro({ mensagem }: { mensagem: string }) {
  return (
    <div
      role="alert"
      className="border border-erro bg-erro-suave text-erro rounded p-3 text-sm mb-4"
    >
      {mensagem}
    </div>
  );
}

export function Aviso({ children }: { children: ReactNode }) {
  return (
    <div className="border border-borda bg-superficie rounded p-3 text-sm mb-4">
      {children}
    </div>
  );
}

// --------------------------------------------------------------------------
export function Tabela(props: {
  colunas: string[];
  legenda: string;
  children: ReactNode;
}) {
  return (
    // tabIndex + role: um container que rola precisa receber foco, senão quem
    // navega por teclado não alcança o conteúdo que ficou fora da viewport.
    // (axe: scrollable-region-focusable)
    <div
      className="overflow-x-auto border border-borda rounded bg-superficie"
      tabIndex={0}
      role="region"
      aria-label={props.legenda}
    >
      <table className="w-full text-sm">
        <caption className="sr-only">{props.legenda}</caption>
        <thead>
          <tr className="border-b border-borda bg-gray-50">
            {props.colunas.map((c) => (
              <th
                key={c}
                scope="col"
                className="text-left font-medium px-3 py-2 whitespace-nowrap"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{props.children}</tbody>
      </table>
    </div>
  );
}

export function Selo({ texto }: { texto: string }) {
  const cor =
    {
      publicado: "bg-ok-suave text-ok border-ok",
      em_dia: "bg-ok-suave text-ok border-ok",
      bloqueada: "bg-alerta-suave text-alerta border-alerta",
      atrasada: "bg-alerta-suave text-alerta border-alerta",
      falha: "bg-erro-suave text-erro border-erro",
      sem_carga: "bg-superficie text-tinta-suave border-borda",
    }[texto] ?? "bg-superficie text-tinta-suave border-borda";
  // O rótulo textual carrega o significado; a cor é reforço, não a
  // informação — daí "em dia" escrito, e não só um ponto verde.
  const legivel = texto.replace(/_/g, " ");
  return (
    <span className={`inline-block rounded border px-2 py-0.5 text-xs ${cor}`}>
      {legivel}
    </span>
  );
}

// --------------------------------------------------------------------------
/** Os cinco estados de uma conexão, sempre a mesma cor e o mesmo ponto em
 * toda a interface — "direção A" do redesenho. Não é o mesmo vocabulário do
 * `Selo` (que descreve frescor de dado publicado); este descreve se a
 * conexão em si está funcionando. */
export type EstadoConexao =
  | "no_ar"
  | "falhou"
  | "atualizando"
  | "pausada"
  | "nunca_rodou";

const CONEXAO: Record<EstadoConexao, { rotulo: string; texto: string; ponto: string }> = {
  no_ar: { rotulo: "No ar", texto: "text-ok", ponto: "bg-ok" },
  falhou: { rotulo: "Falhou", texto: "text-erro", ponto: "bg-erro" },
  atualizando: { rotulo: "Atualizando", texto: "text-acento", ponto: "bg-acento" },
  pausada: { rotulo: "Pausada", texto: "text-tinta-suave", ponto: "bg-tinta-suave" },
  nunca_rodou: { rotulo: "Nunca rodou", texto: "text-tinta-suave", ponto: "bg-borda" },
};

/** Deriva o estado de uma conexão do status da execução mais recente e da
 * flag `ativo` — não existe coluna própria para isto (achado do mapeamento
 * de viabilidade: `ativo` hoje só controla se o agendamento dispara). */
export function estadoDaConexao(
  ativo: boolean,
  ultimoStatus: string | undefined,
): EstadoConexao {
  if (!ativo) return "pausada";
  if (!ultimoStatus) return "nunca_rodou";
  if (ultimoStatus === "publicado") return "no_ar";
  if (ultimoStatus === "falha" || ultimoStatus === "bloqueada") return "falhou";
  return "atualizando";
}

export function BadgeConexao({ estado }: { estado: EstadoConexao }) {
  const e = CONEXAO[estado];
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium whitespace-nowrap ${e.texto}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${e.ponto}`} aria-hidden="true" />
      {e.rotulo}
    </span>
  );
}

/** As últimas execuções em barrinhas — decorativo: o estado e a contagem já
 * dizem o essencial em texto, isto só dá o padrão dos últimos N eventos. */
export function Faixas({ execucoes }: { execucoes: { status: string }[] }) {
  if (execucoes.length === 0) return null;
  return (
    <span className="inline-flex items-end gap-px h-3" aria-hidden="true">
      {execucoes.map((e, i) => (
        <span
          key={i}
          className={`w-0.5 h-full rounded-sm ${
            e.status === "publicado"
              ? "bg-ok"
              : e.status === "falha" || e.status === "bloqueada"
                ? "bg-erro"
                : "bg-borda"
          }`}
        />
      ))}
    </span>
  );
}

// --------------------------------------------------------------------------
/** Confirmação que nomeia o objeto — "Excluir?" sozinho não é confirmação. */
export function Confirmar(props: {
  aberto: boolean;
  titulo: string;
  objeto: string;
  consequencia: string;
  aoConfirmar: () => void;
  aoCancelar: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!props.aberto) return;
    const anterior = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const aoTeclar = (e: KeyboardEvent) => {
      if (e.key === "Escape") props.aoCancelar();
    };
    document.addEventListener("keydown", aoTeclar);
    return () => {
      document.removeEventListener("keydown", aoTeclar);
      anterior?.focus();
    };
  }, [props.aberto]);

  if (!props.aberto) return null;
  return (
    <div className="fixed inset-0 bg-black/40 grid place-items-center p-4 z-40">
      <div
        ref={ref}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="dlg-titulo"
        aria-describedby="dlg-corpo"
        className="bg-superficie rounded border border-borda max-w-md w-full p-5"
      >
        <h2 id="dlg-titulo" className="font-semibold mb-2">
          {props.titulo}
        </h2>
        <p id="dlg-corpo" className="text-sm mb-4">
          {props.consequencia} <strong>{props.objeto}</strong>.
        </p>
        <div className="flex gap-2 justify-end">
          <Botao aoClicar={props.aoCancelar}>Cancelar</Botao>
          <Botao variante="destrutivo" aoClicar={props.aoConfirmar}>
            Confirmar
          </Botao>
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
/** Busca dados com estados de carregando/erro/vazio explícitos. */
export function useDados<T>(
  carregar: () => Promise<T>,
  deps: unknown[] = [],
): { dados: T | null; erro: string | null; carregando: boolean; recarregar: () => void } {
  const [dados, setDados] = useState<T | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let vivo = true;
    setCarregando(true);
    setErro(null);
    carregar()
      .then((d) => vivo && setDados(d))
      .catch((e) => vivo && setErro(e.message))
      .finally(() => vivo && setCarregando(false));
    return () => {
      vivo = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { dados, erro, carregando, recarregar: () => setTick((t) => t + 1) };
}
