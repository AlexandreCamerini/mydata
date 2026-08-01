// A apresentação: onde se vê o dado. Mora em / e lê só /v1 — a administração
// continua em /admin. Roteamento por hash, como no admin, pelo mesmo motivo:
// servido estático sem configuração de servidor e sem biblioteca de rotas.
import { useEffect, useState } from "react";
import { Busca } from "./Busca";
import { Demonstracoes } from "./Demonstracoes";
import { Ficha } from "./Ficha";

type Rota =
  | { tela: "busca" }
  | { tela: "empresa"; cd_cvm: number }
  | { tela: "demonstracoes"; cd_cvm: number };

function rotaAtual(): Rota {
  const dem = window.location.hash.match(/^#\/empresa\/(\d+)\/demonstracoes/);
  if (dem) return { tela: "demonstracoes", cd_cvm: Number(dem[1]) };
  const m = window.location.hash.match(/^#\/empresa\/(\d+)/);
  if (m) return { tela: "empresa", cd_cvm: Number(m[1]) };
  return { tela: "busca" };
}

export function App() {
  const [rota, setRota] = useState<Rota>(rotaAtual);

  useEffect(() => {
    const aoMudar = () => setRota(rotaAtual());
    window.addEventListener("hashchange", aoMudar);
    return () => window.removeEventListener("hashchange", aoMudar);
  }, []);

  useEffect(() => {
    document.title =
      rota.tela === "demonstracoes"
        ? `Demonstrações ${rota.cd_cvm} — MyData`
        : rota.tela === "empresa"
          ? `Companhia ${rota.cd_cvm} — MyData`
          : "MyData — companhias abertas";
  }, [rota]);

  return (
    <>
      <a href="#conteudo" className="pular">
        Pular para o conteúdo
      </a>
      <div className="min-h-screen grid grid-rows-[auto_1fr]">
        <header className="border-b border-borda bg-white">
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
            <a
              href="/admin/"
              className="text-xs text-tinta-suave underline decoration-dotted whitespace-nowrap"
            >
              administração
            </a>
          </div>
        </header>

        <main id="conteudo" className="max-w-5xl mx-auto px-4 py-6 w-full">
          {rota.tela === "busca" && <Busca />}
          {rota.tela === "empresa" && <Ficha cd_cvm={rota.cd_cvm} />}
          {rota.tela === "demonstracoes" && (
            <Demonstracoes cd_cvm={rota.cd_cvm} />
          )}
        </main>
      </div>
    </>
  );
}
