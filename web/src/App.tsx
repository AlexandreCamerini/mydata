import { useEffect, useState } from "react";
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

// Roteamento por hash: funciona servido estaticamente em /admin sem
// configuração de servidor e sem dependência de biblioteca de rotas.
const TELAS = [
  { id: "gestao", titulo: "Gestão", componente: Gestao,
    resumo: "O que o hub tem, quem consome e o que está para vencer o SLA" },
  { id: "classes", titulo: "Classes", componente: Classes,
    resumo: "A informação que o portal guarda, e quem a alimenta" },
  { id: "fontes", titulo: "Fontes", componente: Fontes,
    resumo: "De onde o dado vem" },
  { id: "datasets", titulo: "Mapeamentos", componente: Datasets,
    resumo: "Ligação fonte → classe: o que extrair e como tipar" },
  { id: "calculados", titulo: "Campos calculados", componente: Calculados,
    resumo: "Derivadas com linhagem" },
  { id: "qualidade", titulo: "Qualidade", componente: Qualidade,
    resumo: "Regras que barram publicação" },
  { id: "execucoes", titulo: "Execuções", componente: Execucoes,
    resumo: "Histórico, replay e publicações" },
  { id: "carga", titulo: "Carga e custo", componente: Carga,
    resumo: "O que cada execução pesa em disco, e o que isso custa" },
  { id: "chaves", titulo: "Chaves de API", componente: Chaves,
    resumo: "Consumidores e quotas" },
  { id: "catalogo", titulo: "Catálogo", componente: Catalogo,
    resumo: "Schema e amostra" },
] as const;

function telaAtual(): string {
  const id = window.location.hash.replace("#/", "");
  // A entrada é a classe de informação, não o histórico de execução: quem
  // abre o portal quer saber o que existe, não o que rodou ontem.
  return TELAS.some((t) => t.id === id) ? id : "classes";
}

export function App() {
  const [rota, setRota] = useState(telaAtual);

  useEffect(() => {
    const aoMudar = () => setRota(telaAtual());
    window.addEventListener("hashchange", aoMudar);
    return () => window.removeEventListener("hashchange", aoMudar);
  }, []);

  const tela = TELAS.find((t) => t.id === rota)!;
  const Componente = tela.componente;

  useEffect(() => {
    document.title = `${tela.titulo} — Portal de Dados`;
  }, [tela.titulo]);

  return (
    <>
      <a href="#conteudo" className="pular">
        Pular para o conteúdo
      </a>
      <div className="min-h-screen grid grid-rows-[auto_1fr]">
        <header className="border-b border-borda bg-white">
          <div className="max-w-6xl mx-auto px-4 py-3">
            <p className="font-semibold">Portal de Dados — B3/CVM</p>
            <p className="text-xs text-tinta-suave">
              Hub multi-fonte. O dado oficial é imutável; o derivado se
              recomputa.
            </p>
          </div>
          <nav
            aria-label="Seções de configuração"
            className="max-w-6xl mx-auto px-4"
          >
            <ul className="flex flex-wrap gap-1 -mb-px">
              {TELAS.map((t) => (
                <li key={t.id}>
                  <a
                    href={`#/${t.id}`}
                    aria-current={t.id === rota ? "page" : undefined}
                    className={`inline-block px-3 py-2 text-sm border-b-2 ${
                      t.id === rota
                        ? "border-tinta font-medium"
                        : "border-transparent text-tinta-suave hover:text-tinta"
                    }`}
                  >
                    {t.titulo}
                  </a>
                </li>
              ))}
            </ul>
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
