// A apresentação: onde se vê o dado. Mora em / e lê só /v1 — a administração
// continua em /admin. Roteamento por hash, como no admin, pelo mesmo motivo:
// servido estático sem configuração de servidor e sem biblioteca de rotas.
//
// A companhia é o ponto de partida: `#/empresa/9512` é a tela de onde se
// navega para tudo que existe sobre ela. O grupo entra no endereço
// (`…/demonstracoes/BPA`) para que o recorte seja citável — sem isso, mandar
// a evidência para outra pessoa só funcionaria por captura de tela.
import { useEffect, useState } from "react";
import { Arquivos } from "./Arquivos";
import { Busca } from "./Busca";
import { Demonstracoes } from "./Demonstracoes";
import { Empresa } from "./Empresa";
import { Ficha } from "./Ficha";
import { Indicadores } from "./Indicadores";
import { Negociacao } from "./Negociacao";
import { Operador } from "./Operador";

type Rota =
  | { tela: "busca" }
  | { tela: "empresa"; cd_cvm: number }
  | { tela: "ficha"; cd_cvm: number }
  | { tela: "demonstracoes"; cd_cvm: number; grupo?: string; consolidado?: boolean }
  | { tela: "indicadores"; cd_cvm: number }
  | { tela: "arquivos"; cd_cvm: number }
  | { tela: "negociacao"; ticker: string }
  | { tela: "operador" };

function rotaAtual(): Rota {
  const h = window.location.hash;
  if (h.startsWith("#/operador")) return { tela: "operador" };

  const neg = h.match(/^#\/negociacao(?:\/([A-Za-z0-9]+))?/);
  if (neg) return { tela: "negociacao", ticker: (neg[1] ?? "PETR4").toUpperCase() };

  // O terceiro grupo é opcional e vem de um card de Empresa.tsx que já sabe
  // qual dos dois modos (consolidado/individual) tem linha pra este grupo —
  // sem isto a tela sempre abria consolidado, mesmo quando só individual
  // tinha dado.
  const dem = h.match(
    /^#\/empresa\/(\d+)\/demonstracoes(?:\/([A-Za-z_]+))?(?:\?consolidado=([01]))?/,
  );
  if (dem)
    return {
      tela: "demonstracoes",
      cd_cvm: Number(dem[1]),
      grupo: dem[2],
      consolidado: dem[3] === undefined ? undefined : dem[3] === "1",
    };

  const ind = h.match(/^#\/empresa\/(\d+)\/indicadores/);
  if (ind) return { tela: "indicadores", cd_cvm: Number(ind[1]) };

  const arq = h.match(/^#\/empresa\/(\d+)\/arquivos/);
  if (arq) return { tela: "arquivos", cd_cvm: Number(arq[1]) };

  const fic = h.match(/^#\/empresa\/(\d+)\/ficha/);
  if (fic) return { tela: "ficha", cd_cvm: Number(fic[1]) };

  const emp = h.match(/^#\/empresa\/(\d+)/);
  if (emp) return { tela: "empresa", cd_cvm: Number(emp[1]) };

  return { tela: "busca" };
}

function titulo(rota: Rota): string {
  switch (rota.tela) {
    case "operador":
      return "Operador — MyData";
    case "negociacao":
      return `Opções ${rota.ticker} — MyData`;
    case "demonstracoes":
      return `Demonstrações ${rota.cd_cvm}${rota.grupo ? ` · ${rota.grupo}` : ""} — MyData`;
    case "indicadores":
      return `Indicadores ${rota.cd_cvm} — MyData`;
    case "arquivos":
      return `Arquivos originais ${rota.cd_cvm} — MyData`;
    case "ficha":
      return `Ficha ${rota.cd_cvm} — MyData`;
    case "empresa":
      return `Companhia ${rota.cd_cvm} — MyData`;
    default:
      return "MyData — companhias abertas";
  }
}

export function App() {
  const [rota, setRota] = useState<Rota>(rotaAtual);

  useEffect(() => {
    const aoMudar = () => setRota(rotaAtual());
    window.addEventListener("hashchange", aoMudar);
    return () => window.removeEventListener("hashchange", aoMudar);
  }, []);

  useEffect(() => {
    document.title = titulo(rota);
  }, [rota]);

  return (
    <>
      <a href="#conteudo" className="pular">
        Pular para o conteúdo
      </a>
      <div className="min-h-screen grid grid-rows-[auto_1fr]">
        <header className="border-b border-borda bg-superficie">
          <div className="max-w-5xl mx-auto px-4 py-3 flex items-baseline justify-between gap-4">
            <div>
              <p className="font-semibold">
                <a href="#/">MyData</a>
                <span className="text-tinta-suave font-normal">
                  {" "}
                  — companhias abertas
                </span>
              </p>
              <p className="text-xs text-tinta-suave">
                Dado da fonte oficial, com proveniência em cada número.
              </p>
            </div>
            <nav aria-label="Operação" className="flex gap-4 whitespace-nowrap">
              <a
                href="#/negociacao/PETR4"
                className="text-xs text-tinta-suave underline decoration-dotted"
              >
                opções (B3)
              </a>
              <a
                href="#/operador"
                className="text-xs text-tinta-suave underline decoration-dotted"
              >
                operador
              </a>
              <a
                href="/admin/"
                className="text-xs text-tinta-suave underline decoration-dotted"
              >
                administração
              </a>
              <a
                href="/sair"
                className="text-xs text-tinta-suave underline decoration-dotted"
              >
                sair
              </a>
            </nav>
          </div>
        </header>

        <main id="conteudo" className="max-w-5xl mx-auto px-4 py-6 w-full">
          {rota.tela === "busca" && <Busca />}
          {rota.tela === "empresa" && <Empresa cd_cvm={rota.cd_cvm} />}
          {rota.tela === "ficha" && <Ficha cd_cvm={rota.cd_cvm} />}
          {rota.tela === "demonstracoes" && (
            <Demonstracoes
              cd_cvm={rota.cd_cvm}
              grupoInicial={rota.grupo}
              consolidadoInicial={rota.consolidado}
            />
          )}
          {rota.tela === "indicadores" && <Indicadores cd_cvm={rota.cd_cvm} />}
          {rota.tela === "arquivos" && <Arquivos cd_cvm={rota.cd_cvm} />}
          {rota.tela === "negociacao" && <Negociacao ticker={rota.ticker} />}
          {rota.tela === "operador" && <Operador />}
        </main>
      </div>
    </>
  );
}
