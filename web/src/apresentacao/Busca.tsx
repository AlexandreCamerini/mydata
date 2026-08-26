// Busca e recorte do universo. Os três filtros respondem ao escopo real do
// produto: das ~2.500 companhias registradas na CVM, interessa quem negocia
// na B3 e publica balanço — e a tela diz quantas são, não só lista.
import { useEffect, useRef, useState } from "react";
import { Botao, Caixa, Campo, Carregando, Erro, Selecao, Selo, Vazio } from "../ui";
import { api, type Empresa, type FiltrosEmpresas } from "./api";

const SEGMENTOS = [
  { valor: "", rotulo: "todos os segmentos" },
  { valor: "NM", rotulo: "Novo Mercado" },
  { valor: "N1", rotulo: "Nível 1" },
  { valor: "N2", rotulo: "Nível 2" },
  { valor: "MB", rotulo: "Balcão organizado (MB)" },
];

/** Uma linha de tabela força 6 colunas por companhia mesmo quando o dado não
 * existe — a maioria fora do filtro de B3 preenchia 4 delas com "—". O card
 * mostra só o campo que a companhia tem. Mesmo padrão visual do `Cartao` de
 * `Empresa.tsx`, para não introduzir um terceiro estilo de card no produto. */
function CartaoEmpresa({ e }: { e: Empresa }) {
  return (
    <a
      href={`#/empresa/${e.cd_cvm}`}
      role="listitem"
      className="border border-borda rounded bg-superficie p-3 grid gap-1 content-start
                 hover:border-tinta focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-1"
    >
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="font-medium">{e.denom_social ?? `Companhia ${e.cd_cvm}`}</span>
        {e.ticker && <span className="font-mono text-xs text-tinta-suave">{e.ticker}</span>}
        {e.listada_b3 && <Selo texto={e.segmento_listagem || "básico"} />}
      </div>
      {(e.setor_atividade || e.uf) && (
        <p className="text-xs text-tinta-suave">
          {[e.setor_atividade, e.uf].filter(Boolean).join(" · ")}
        </p>
      )}
      {e.cnpj && <p className="text-xs text-tinta-suave font-mono">{e.cnpj}</p>}
    </a>
  );
}

export function Busca() {
  // Sem filtro, a base é as ~2.500 companhias registradas na CVM — a maioria
  // não negocia na B3 e não publica balanço recente, então a lista nasceria
  // cheia de campo vazio. Quem abre esta tela quer companhia com dado; os
  // dois filtros começam ligados, e dá pra desligar pra ver o universo cru.
  const [filtros, setFiltros] = useState<FiltrosEmpresas>({
    listada_b3: true,
    com_balanco: true,
  });
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  // A digitação espera meio segundo parada antes de consultar; filtro é clique
  // e consulta na hora.
  const atraso = useRef<number | undefined>(undefined);

  async function consultar(f: FiltrosEmpresas, acumular = false) {
    setCarregando(true);
    setErro(null);
    try {
      const r = await api.empresas({ ...f, limite: 50 });
      setEmpresas((atuais) => (acumular ? [...atuais, ...r.dados] : r.dados));
      setTotal(r.total);
      setCursor(r.proximo_cursor);
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setCarregando(false);
    }
  }

  useEffect(() => {
    consultar(filtros);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function mudar(muda: Partial<FiltrosEmpresas>, imediato: boolean) {
    const novos = { ...filtros, ...muda, cursor: undefined };
    setFiltros(novos);
    window.clearTimeout(atraso.current);
    if (imediato) consultar(novos);
    else atraso.current = window.setTimeout(() => consultar(novos), 500);
  }

  return (
    <div className="grid gap-5">
      {/* Toda página precisa de um h1: é por ele que leitor de tela anuncia
          onde a pessoa está. Aqui ele era invisível porque a busca começava
          direto nos filtros. */}
      <h1 className="sr-only">Companhias abertas registradas na CVM</h1>
      <section
        aria-labelledby="filtros"
        className="border border-borda rounded bg-superficie p-4"
      >
        <h2 id="filtros" className="sr-only">
          Busca e filtros
        </h2>
        <Campo
          rotulo="Buscar companhia"
          valor={filtros.q ?? ""}
          aoMudar={(v) => mudar({ q: v || undefined }, false)}
          placeholder="nome, CNPJ ou ticker — ex.: petrobras, PETR4"
          ajuda="Ticker casa pelo papel: PETR4 encontra a raiz PETR registrada na B3."
        />
        <div className="grid gap-x-6 sm:grid-cols-[auto_auto_1fr] items-end">
          <Caixa
            rotulo="Só listadas na B3"
            marcado={Boolean(filtros.listada_b3)}
            aoMudar={(v) => mudar({ listada_b3: v || undefined }, true)}
          />
          <Caixa
            rotulo="Só quem publica balanço"
            marcado={Boolean(filtros.com_balanco)}
            aoMudar={(v) => mudar({ com_balanco: v || undefined }, true)}
          />
          <div className="max-w-xs">
            <Selecao
              rotulo="Segmento de listagem"
              valor={filtros.segmento ?? ""}
              aoMudar={(v) => mudar({ segmento: v || undefined }, true)}
              opcoes={SEGMENTOS}
            />
          </div>
        </div>
      </section>

      {erro && <Erro mensagem={erro} />}
      {carregando && empresas.length === 0 && <Carregando oque="companhias" />}

      {total !== null && (
        <p role="status" className="text-sm text-tinta-suave">
          <strong className="text-tinta tabular-nums">{total}</strong>{" "}
          {total === 1 ? "companhia" : "companhias"} no recorte
          {empresas.length < total && ` · mostrando ${empresas.length}`}
        </p>
      )}

      {!carregando && empresas.length === 0 && !erro && (
        <Vazio
          titulo="Nenhuma companhia no recorte"
          dica="Afrouxe a busca ou os filtros."
        />
      )}

      {empresas.length > 0 && (
        <div
          role="list"
          aria-label="Companhias no recorte atual"
          className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3"
        >
          {empresas.map((e) => (
            <CartaoEmpresa key={e.cd_cvm} e={e} />
          ))}
        </div>
      )}

      {cursor && (
        <div>
          <Botao
            carregando={carregando}
            aoClicar={() => consultar({ ...filtros, cursor }, true)}
          >
            Carregar mais
          </Botao>
        </div>
      )}
    </div>
  );
}
