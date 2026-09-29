import { useEffect, useState } from "react";
import { api } from "./api";
import { Gestao } from "./telas/Gestao";
import { Classes } from "./telas/Classes";
import { Fontes } from "./telas/Fontes";
import { Datasets } from "./telas/Datasets";
import { Calculados } from "./telas/Calculados";
import { Qualidade } from "./telas/Qualidade";
import { Execucoes } from "./telas/Execucoes";
import { Carga } from "./telas/Carga";
import { Chaves } from "./telas/Chaves";
import { Catalogo } from "./telas/Catalogo";
import { Acesso } from "./telas/Acesso";
import { Api } from "./telas/Api";
import { Console } from "./telas/Console";

// Roteamento por hash: funciona servido estaticamente em /admin sem
// configuração de servidor e sem dependência de biblioteca de rotas.
//
// `grupo` é só rótulo de navegação — não muda rota nem componente. 12 abas
// no mesmo nível não davam pista de qual pertencia a quê; os três nomes
// abaixo são os que docs/arquitetura.md já usa para essas camadas, não
// taxonomia nova. "Visão geral" fica sem rótulo — não é uma categoria de
// verdade, é onde a navegação começa.
const TELAS = [
  { id: "gestao", titulo: "Gestão", grupo: "Visão geral", componente: Gestao,
    resumo: "O que o hub tem, quem consome e o que está para vencer o SLA" },
  { id: "console", titulo: "Console", grupo: "Visão geral", componente: Console,
    resumo: "Saúde, métricas e deploys dos cinco sistemas, coletados de fora" },
  { id: "classes", titulo: "O que você guarda", grupo: "Modelo de dado", componente: Classes,
    resumo: "Empresa, Demonstração financeira — a informação que o portal guarda, e quem a alimenta" },
  { id: "fontes", titulo: "Fontes", grupo: "Modelo de dado", componente: Fontes,
    resumo: "De onde o dado vem" },
  { id: "datasets", titulo: "Conexões", grupo: "Modelo de dado", componente: Datasets,
    resumo: "A ligação fonte → classe, com estado de cada uma" },
  { id: "calculados", titulo: "Campos calculados", grupo: "Modelo de dado", componente: Calculados,
    resumo: "Derivadas com linhagem" },
  { id: "qualidade", titulo: "Qualidade", grupo: "Operação do pipeline", componente: Qualidade,
    resumo: "Regras que barram publicação" },
  { id: "execucoes", titulo: "Execuções", grupo: "Operação do pipeline", componente: Execucoes,
    resumo: "Histórico, replay e publicações" },
  { id: "carga", titulo: "Carga e custo", grupo: "Operação do pipeline", componente: Carga,
    resumo: "O que cada execução pesa em disco, e o que isso custa" },
  { id: "chaves", titulo: "Chaves de API", grupo: "Acesso e consumo", componente: Chaves,
    resumo: "Consumidores e quotas" },
  { id: "catalogo", titulo: "Catálogo", grupo: "Acesso e consumo", componente: Catalogo,
    resumo: "Schema e amostra" },
  { id: "acesso", titulo: "Acesso", grupo: "Acesso e consumo", componente: Acesso,
    resumo: "Quem entra no portal, por onde, e como revogar" },
  { id: "api", titulo: "API", grupo: "Acesso e consumo", componente: Api,
    resumo: "Toda rota exposta, documentada e testável ao vivo" },
] as const;

/** TELAS já vem na ordem de leitura certa (visão geral, depois cada grupo
 * inteiro) — agrupar preservando a ordem de primeira ocorrência basta, sem
 * precisar de uma lista de grupos à parte para manter em sincronia. */
const GRUPOS_NAV = (() => {
  const porGrupo = new Map<string, (typeof TELAS)[number][]>();
  for (const t of TELAS) {
    const lista = porGrupo.get(t.grupo) ?? [];
    lista.push(t);
    porGrupo.set(t.grupo, lista);
  }
  return [...porGrupo.entries()];
})();

/** A tela é o que vem antes do "?". O que vem depois é argumento dela.
 *
 * Sem isto, "#/catalogo?tabela=fato_conta" não casa com tela nenhuma e cai no
 * padrão — um link que parece funcionar e leva ao lugar errado é pior do que
 * link que não existe. */
export function argumento(nome: string): string | null {
  const hash = window.location.hash.replace("#/", "");
  const [, consulta = ""] = hash.split("?");
  return new URLSearchParams(consulta).get(nome);
}

function telaAtual(): string {
  const id = window.location.hash.replace("#/", "").split("?")[0];
  // A entrada é a classe de informação, não o histórico de execução: quem
  // abre o portal quer saber o que existe, não o que rodou ontem.
  return TELAS.some((t) => t.id === id) ? id : "classes";
}

/** O semáforo na navegação: um ponto em "Gestão" quando há alerta ativo.
 *
 * O alarme mais barato é o que aparece onde a pessoa já está. Sem isto, quem
 * trabalha em Mapeamentos só descobre uma falha quando resolve abrir Gestão —
 * e a auditoria mediu que ninguém abre por acaso. Sondagem de minuto em
 * minuto: estado operacional muda em minutos, não em segundos.
 */
function useSituacao(): "ok" | "atencao" | "critico" | null {
  const [situacao, setSituacao] = useState<"ok" | "atencao" | "critico" | null>(null);
  useEffect(() => {
    let vivo = true;
    const sondar = () =>
      api
        .alertas()
        .then((r) => vivo && setSituacao(r.dados.resumo.situacao))
        .catch(() => vivo && setSituacao(null));
    sondar();
    const id = window.setInterval(sondar, 60_000);
    return () => {
      vivo = false;
      window.clearInterval(id);
    };
  }, []);
  return situacao;
}

export function App() {
  const [rota, setRota] = useState(telaAtual);
  const situacao = useSituacao();
  // No celular as 4 categorias empilhadas passavam de 700px de navegação
  // antes do conteúdo — a partir de `md:` a navegação sempre aparece
  // inteira; abaixo disso, fica atrás de um botão.
  const [menuAberto, setMenuAberto] = useState(false);

  useEffect(() => {
    const aoMudar = () => setRota(telaAtual());
    window.addEventListener("hashchange", aoMudar);
    return () => window.removeEventListener("hashchange", aoMudar);
  }, []);

  const tela = TELAS.find((t) => t.id === rota)!;
  const Componente = tela.componente;

  useEffect(() => {
    document.title = `${tela.titulo} — MyData`;
  }, [tela.titulo]);

  useEffect(() => {
    setMenuAberto(false);
  }, [rota]);

  return (
    <>
      <a href="#conteudo" className="pular">
        Pular para o conteúdo
      </a>
      <div className="min-h-screen grid grid-rows-[auto_1fr]">
        <header className="border-b border-borda bg-superficie">
          <div className="max-w-6xl mx-auto px-4 py-3 flex items-baseline justify-between gap-4">
            <div>
              <p className="font-semibold">MyData — configuração</p>
              <p className="text-xs text-tinta-suave">
                Hub multi-fonte. O dado oficial é imutável; o derivado se
                recomputa.
              </p>
            </div>
            <a
              href="/"
              className="text-xs text-tinta-suave underline decoration-dotted whitespace-nowrap"
            >
              ver companhias
            </a>
          </div>
          <nav
            aria-label="Seções de configuração"
            className="max-w-6xl mx-auto px-4"
          >
            <button
              type="button"
              className="md:hidden flex items-center gap-2 py-2 text-sm font-medium"
              aria-expanded={menuAberto}
              aria-controls="nav-admin-grupos"
              onClick={() => setMenuAberto((a) => !a)}
            >
              <span aria-hidden="true">{menuAberto ? "▾" : "▸"}</span>
              Seções · {tela.titulo}
            </button>
            <div
              id="nav-admin-grupos"
              className={`${menuAberto ? "flex" : "hidden"} md:flex flex-col md:flex-row flex-wrap items-start md:items-end gap-x-6 gap-y-1 pb-2 md:pb-0`}
            >
              {GRUPOS_NAV.map(([grupo, itens]) => (
                <div key={grupo}>
                  {grupo !== "Visão geral" && (
                    <p className="rotulo px-3">{grupo}</p>
                  )}
                  <ul className="flex flex-wrap gap-1 -mb-px">
                    {itens.map((t) => (
                      <li key={t.id}>
                        <a
                          href={`#/${t.id}`}
                          aria-current={t.id === rota ? "page" : undefined}
                          className={`inline-block px-3 py-2 text-sm border-b-2 ${
                            t.id === rota
                              ? "border-acento text-acento font-medium"
                              : "border-transparent text-tinta-suave hover:text-tinta"
                          }`}
                        >
                          {t.titulo}
                          {t.id === "gestao" && situacao && situacao !== "ok" && (
                            <span
                              aria-label={situacao === "critico"
                                ? "há alertas críticos"
                                : "há pontos de atenção"}
                              role="img"
                              className={`inline-block w-2 h-2 rounded-full ml-1.5 align-middle ${
                                situacao === "critico" ? "bg-erro" : "bg-alerta"
                              }`}
                            />
                          )}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </nav>
        </header>

        <main id="conteudo" className="max-w-6xl mx-auto px-4 py-6 w-full">
          <h1 className="text-xl font-semibold">{tela.titulo}</h1>
          <p className="text-sm text-tinta-suave mb-5">{tela.resumo}</p>
          <Componente />
        </main>
      </div>
    </>
  );
}
