// Busca e recorte do universo. Os três filtros respondem ao escopo real do
// produto: das ~2.500 companhias registradas na CVM, interessa quem negocia
// na B3 e publica balanço — e a tela diz quantas são, não só lista.
import { useEffect, useRef, useState } from "react";
import { Botao, Caixa, Campo, Carregando, Erro, Selecao, Selo, Tabela, Vazio } from "../ui";
import { api, type Empresa, type FiltrosEmpresas } from "./api";

const SEGMENTOS = [
  { valor: "", rotulo: "todos os segmentos" },
  { valor: "NM", rotulo: "Novo Mercado" },
  { valor: "N1", rotulo: "Nível 1" },
  { valor: "N2", rotulo: "Nível 2" },
  { valor: "MB", rotulo: "Balcão organizado (MB)" },
];

export function Busca() {
  const [filtros, setFiltros] = useState<FiltrosEmpresas>({});
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
        className="border border-borda rounded bg-white p-4"
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
        <Tabela
          legenda="Companhias no recorte atual"
          colunas={["Companhia", "CNPJ", "Ticker", "Segmento", "Setor", "UF"]}
        >
          {empresas.map((e) => (
            <tr key={e.cd_cvm} className="border-b border-borda last:border-0">
              <th scope="row" className="text-left px-3 py-2">
                <a
                  href={`#/empresa/${e.cd_cvm}`}
                  className="font-medium underline decoration-dotted"
                >
                  {e.denom_social ?? `Companhia ${e.cd_cvm}`}
                </a>
                <span className="block text-xs text-tinta-suave">
                  cd_cvm {e.cd_cvm}
                  {e.nome_pregao && ` · ${e.nome_pregao}`}
                </span>
              </th>
              <td className="px-3 py-2 font-mono text-xs">{e.cnpj ?? "—"}</td>
              <td className="px-3 py-2 font-mono text-xs">{e.ticker ?? "—"}</td>
              <td className="px-3 py-2 text-xs">
                {e.listada_b3 ? (
                  <Selo texto={e.segmento_listagem || "básico"} />
                ) : (
                  "—"
                )}
              </td>
              <td className="px-3 py-2 text-xs">{e.setor_atividade ?? "—"}</td>
              <td className="px-3 py-2 text-xs">{e.uf ?? "—"}</td>
            </tr>
          ))}
        </Tabela>
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
