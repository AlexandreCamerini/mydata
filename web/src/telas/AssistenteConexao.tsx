// Direção B do redesenho: os três passos que a prévia de arquivo torna
// possíveis. Fonte → Arquivo → Ligar campos monta um `DatasetPayload`
// rascunho e entrega para o `DatasetForm` de sempre terminar (agendar,
// validar, salvar) — não duplica a validação nem o salvamento, que já
// existem e já são testados.
import { useState } from "react";
import {
  api,
  type Classe,
  type ColunaPayload,
  type DatasetPayload,
  type Fonte,
  type PreviaArquivo,
} from "../api";
import { Aviso, Botao, Campo, Erro, Selecao, useDados } from "../ui";
import { DatasetForm } from "./DatasetForm";

type Passo = 1 | 2 | 3 | 4;

const TRANSPORTES_COM_PREVIA = new Set(["http_csv", "http_zip"]);

function Passos({ atual }: { atual: Passo }) {
  const nomes = ["Fonte", "Arquivo", "Ligar campos", "Agendar e salvar"];
  return (
    <div className="flex items-center gap-2 text-xs text-tinta-suave flex-wrap pb-2 border-b border-borda">
      {nomes.map((nome, i) => {
        const n = (i + 1) as Passo;
        const feito = n < atual;
        const aqui = n === atual;
        return (
          <span
            key={nome}
            className={`inline-flex items-center gap-1.5 ${aqui ? "text-tinta font-medium" : ""}`}
          >
            <span
              className={`w-4 h-4 rounded-full border grid place-items-center text-[10px] ${
                feito
                  ? "bg-ok border-ok text-papel"
                  : aqui
                    ? "bg-acento border-acento text-papel"
                    : "border-borda"
              }`}
            >
              {feito ? "✓" : n}
            </span>
            {nome}
          </span>
        );
      })}
    </div>
  );
}

export function AssistenteConexao(props: {
  aoSalvar: () => void;
  aoFechar: () => void;
}) {
  const fontes = useDados(() => api.fontes());
  const classes = useDados(() => api.classes());
  const [passo, setPasso] = useState<Passo>(1);

  const [fonteChave, setFonteChave] = useState("");
  const [chave, setChave] = useState("");
  const [nome, setNome] = useState("");
  const [classeChave, setClasseChave] = useState("");
  const [janela, setJanela] = useState(String(new Date().getFullYear()));
  const [padraoArquivo, setPadraoArquivo] = useState("");

  const [buscando, setBuscando] = useState(false);
  const [erroPrevia, setErroPrevia] = useState<string | null>(null);
  const [previa, setPrevia] = useState<PreviaArquivo | null>(null);
  const [pulouPrevia, setPulouPrevia] = useState(false);

  const [ligacoes, setLigacoes] = useState<Record<string, string>>({});

  const listaFontes: Fonte[] = fontes.dados?.dados ?? [];
  const listaClasses: Classe[] = classes.dados?.dados ?? [];
  const fonte = listaFontes.find((f) => f.chave === fonteChave);
  const temPrevia = fonte ? TRANSPORTES_COM_PREVIA.has(fonte.tipo_transporte) : false;

  async function buscarPrevia() {
    setBuscando(true);
    setErroPrevia(null);
    try {
      const r = await api.previaArquivo(fonteChave, {
        chave: chave.trim(),
        janela: janela.trim(),
        padrao_arquivo: padraoArquivo.trim() || null,
        parametros: {},
      });
      setPrevia(r.dados);
      const iniciais: Record<string, string> = {};
      for (const col of r.dados.colunas) iniciais[col] = "";
      setLigacoes(iniciais);
      setPasso(3);
    } catch (e) {
      setErroPrevia((e as Error).message);
    } finally {
      setBuscando(false);
    }
  }

  function colunasLigadas(): ColunaPayload[] {
    const origens = previa?.colunas ?? Object.keys(ligacoes);
    return origens
      .map((origem, i): ColunaPayload | null => {
        const destino = (ligacoes[origem] ?? "").trim();
        if (!destino) return null;
        return {
          nome_origem: origem,
          nome_destino: destino,
          tipo: "texto",
          formato: null,
          obrigatoria: false,
          ordem: i + 1,
        };
      })
      .filter((c): c is ColunaPayload => c !== null);
  }

  if (passo === 4) {
    const classeEscolhida = listaClasses.find((c) => c.chave === classeChave);
    const rascunho: DatasetPayload = {
      chave: chave.trim(),
      fonte_chave: fonteChave,
      nome: nome.trim() || chave.trim(),
      padrao_arquivo: padraoArquivo.trim(),
      tabela_destino: classeEscolhida?.tabela ?? "",
      chave_natural: [],
      classe_chave: classeChave || null,
      politica_versao: "max_versao",
      particao: "ano",
      parametros: {},
      colunas: colunasLigadas(),
      calculados: [],
      regras: [],
      descricao: null,
      ativo: true,
    };
    return (
      <div className="grid gap-4">
        <Passos atual={4} />
        <Aviso>
          Os campos abaixo já vêm preenchidos do que a prévia leu — confira
          chave natural e tabela antes de salvar. "Nova versão de{" "}
          {rascunho.chave}" é só o rótulo do formulário: para uma chave nova,
          salvar cria a primeira versão.
        </Aviso>
        <DatasetForm
          inicial={rascunho}
          fontes={listaFontes.map((f) => f.chave)}
          classes={listaClasses.map((c) => c.chave)}
          aoSalvar={props.aoSalvar}
          aoFechar={props.aoFechar}
        />
      </div>
    );
  }

  return (
    <section aria-labelledby="assistente" className="grid gap-4">
      <h2 id="assistente" className="font-medium">
        Nova conexão
      </h2>
      <Passos atual={passo} />

      {passo === 1 && (
        <div className="border border-borda rounded bg-superficie p-4 grid gap-x-6 md:grid-cols-2">
          <Selecao
            rotulo="Fonte"
            valor={fonteChave}
            aoMudar={setFonteChave}
            opcoes={[
              { valor: "", rotulo: "— escolha —" },
              ...listaFontes.map((f) => ({ valor: f.chave, rotulo: f.nome })),
            ]}
          />
          <Campo
            rotulo="Chave"
            valor={chave}
            aoMudar={setChave}
            ajuda="Identificador estável da conexão."
            obrigatorio
            monoespacado
          />
          <Campo rotulo="Nome" valor={nome} aoMudar={setNome} obrigatorio />
          <Selecao
            rotulo="O que ela alimenta"
            valor={classeChave}
            aoMudar={setClasseChave}
            opcoes={[
              { valor: "", rotulo: "— nenhuma —" },
              ...listaClasses.map((c) => ({ valor: c.chave, rotulo: c.nome })),
            ]}
          />
          <Campo
            rotulo="Janela de teste"
            valor={janela}
            aoMudar={setJanela}
            ajuda="Ano ou data usada só para buscar o arquivo de exemplo."
            monoespacado
          />
          <div className="md:col-span-2 pt-2">
            <Botao
              variante="primario"
              desabilitado={!fonteChave || !chave.trim()}
              aoClicar={() => setPasso(2)}
            >
              Avançar
            </Botao>
            <span className="ml-2">
              <Botao aoClicar={props.aoFechar}>Cancelar</Botao>
            </span>
          </div>
        </div>
      )}

      {passo === 2 && (
        <div className="border border-borda rounded bg-superficie p-4 grid gap-4">
          {!temPrevia ? (
            <Aviso>
              A prévia não cobre o transporte desta fonte (
              <code>{fonte?.tipo_transporte}</code>) — API paginada ou de
              bilhete não tem uma "primeira linha" isolada. Pule esta etapa e
              ligue os campos às cegas na próxima tela, como hoje.
            </Aviso>
          ) : (
            <>
              {fonte?.tipo_transporte === "http_zip" && (
                <Campo
                  rotulo="Padrão de arquivo"
                  valor={padraoArquivo}
                  aoMudar={setPadraoArquivo}
                  ajuda="Expressão regular para escolher o membro certo dentro do zip."
                  monoespacado
                  obrigatorio
                />
              )}
              {erroPrevia && <Erro mensagem={erroPrevia} />}
              {previa && (
                <p className="text-sm text-ok" role="status">
                  {previa.nome_arquivo} — {previa.colunas.length} colunas,{" "}
                  {previa.amostra.length} linhas de amostra.
                </p>
              )}
              <div>
                <Botao
                  variante="primario"
                  carregando={buscando}
                  desabilitado={fonte?.tipo_transporte === "http_zip" && !padraoArquivo.trim()}
                  aoClicar={buscarPrevia}
                >
                  Baixar e mostrar o arquivo
                </Botao>
              </div>
            </>
          )}
          <div className="flex gap-2">
            <Botao aoClicar={() => setPasso(1)}>Voltar</Botao>
            {!temPrevia && (
              <Botao
                variante="primario"
                aoClicar={() => {
                  setPrevia(null);
                  setPulouPrevia(true);
                  setPasso(3);
                }}
              >
                Pular — ligar às cegas
              </Botao>
            )}
          </div>
        </div>
      )}

      {passo === 3 && (
        <div className="border border-borda rounded bg-superficie p-4 grid gap-4">
          {pulouPrevia || !previa ? (
            <Aviso>
              Sem prévia desta fonte, o campo de origem é digitado — confira
              o nome exato contra o arquivo antes de salvar.
            </Aviso>
          ) : (
            <p className="text-xs text-tinta-suave">
              Deixe o destino em branco para não trazer a coluna.
            </p>
          )}
          <ul className="grid gap-1 list-none p-0 m-0">
            {(previa?.colunas ?? [""]).map((origem) => (
              <li
                key={origem || "manual"}
                className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 border-b border-borda last:border-0 py-1"
              >
                <span className="border border-borda rounded px-2 py-1 text-xs">
                  <span className="font-mono">{origem || "(digite a origem)"}</span>
                  {previa && (
                    <span className="block text-tinta-suave font-mono truncate">
                      {previa.amostra[0]?.[origem] ?? ""}
                    </span>
                  )}
                </span>
                <span className="text-acento font-bold text-center" aria-hidden="true">
                  →
                </span>
                <input
                  value={ligacoes[origem] ?? ""}
                  onChange={(e) =>
                    setLigacoes((l) => ({ ...l, [origem]: e.target.value }))
                  }
                  placeholder="não trazer"
                  className="border border-borda rounded px-2 py-1 text-xs font-mono bg-superficie"
                  aria-label={`Campo de destino para ${origem || "coluna"}`}
                />
              </li>
            ))}
          </ul>
          {(pulouPrevia || !previa) && (
            <Botao
              aoClicar={() =>
                setLigacoes((l) => ({ ...l, [`origem_${Object.keys(l).length + 1}`]: "" }))
              }
            >
              Acrescentar linha
            </Botao>
          )}
          <div className="flex gap-2">
            <Botao aoClicar={() => setPasso(previa ? 2 : 1)}>Voltar</Botao>
            <Botao
              variante="primario"
              desabilitado={colunasLigadas().length === 0}
              aoClicar={() => setPasso(4)}
            >
              Avançar
            </Botao>
          </div>
        </div>
      )}
    </section>
  );
}
