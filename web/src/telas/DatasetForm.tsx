// Editor de mapeamento (dataset) e das suas três seções aninhadas — colunas,
// campos calculados e regras de qualidade. As seções são exportadas em
// separado porque Calculados e Qualidade editam só a sua parte: o POST é
// sempre o dataset inteiro (salvar cria nova versão), mas a tela de cada
// assunto não precisa carregar o resto do formulário.
import { useState } from "react";
import {
  api,
  lista,
  type CalculadoPayload,
  type ColunaPayload,
  type DatasetPayload,
  type RegraPayload,
} from "../api";
import { Aviso, Botao, Caixa, Campo, Erro, Selecao } from "../ui";

const TIPOS = ["texto", "inteiro", "numero", "data", "booleano"].map((t) => ({
  valor: t,
  rotulo: t,
}));

export const DATASET_VAZIO: DatasetPayload = {
  chave: "",
  fonte_chave: "",
  nome: "",
  padrao_arquivo: "",
  tabela_destino: "",
  chave_natural: [],
  classe_chave: null,
  politica_versao: "max_versao",
  particao: "ano",
  parametros: {},
  colunas: [],
  calculados: [],
  regras: [],
  descricao: null,
  ativo: true,
};

// --------------------------------------------------------------------------
export function EditorColunas(props: {
  colunas: ColunaPayload[];
  aoMudar: (c: ColunaPayload[]) => void;
}) {
  function mudar(i: number, muda: Partial<ColunaPayload>) {
    props.aoMudar(
      props.colunas.map((c, j) => (j === i ? { ...c, ...muda } : c)),
    );
  }
  return (
    <fieldset className="border border-borda rounded p-3 mb-4">
      <legend className="text-sm font-medium px-1">Colunas</legend>
      <p className="text-xs text-tinta-suave mb-3">
        Origem com <code>$</code> lê dos grupos nomeados do padrão de arquivo,
        não do CSV.
      </p>
      <ul className="grid gap-3 list-none p-0 m-0">
        {props.colunas.map((c, i) => (
          <li
            key={i}
            className="border border-borda rounded p-3 grid gap-x-4 md:grid-cols-[1fr_1fr_1fr_1fr_auto]"
          >
            <Campo
              rotulo={`Coluna ${i + 1} — origem`}
              valor={c.nome_origem}
              aoMudar={(v) => mudar(i, { nome_origem: v })}
              obrigatorio
              monoespacado
            />
            <Campo
              rotulo="Destino"
              valor={c.nome_destino}
              aoMudar={(v) => mudar(i, { nome_destino: v })}
              obrigatorio
              monoespacado
            />
            <Selecao
              rotulo="Tipo"
              valor={c.tipo}
              aoMudar={(v) => mudar(i, { tipo: v })}
              opcoes={TIPOS}
            />
            <Campo
              rotulo="Formato"
              valor={c.formato ?? ""}
              aoMudar={(v) => mudar(i, { formato: v.trim() || null })}
              ajuda="Ex.: decimal_ptbr, data_iso, igual:S."
              monoespacado
            />
            <div className="pt-6">
              <Botao
                variante="destrutivo"
                aoClicar={() =>
                  props.aoMudar(props.colunas.filter((_, j) => j !== i))
                }
              >
                Remover
                <span className="sr-only"> coluna {i + 1}</span>
              </Botao>
            </div>
            <div className="md:col-span-5">
              <Caixa
                rotulo="Obrigatória"
                marcado={c.obrigatoria}
                aoMudar={(v) => mudar(i, { obrigatoria: v })}
              />
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-3">
        <Botao
          aoClicar={() =>
            props.aoMudar([
              ...props.colunas,
              {
                nome_origem: "",
                nome_destino: "",
                tipo: "texto",
                formato: null,
                obrigatoria: false,
                ordem: props.colunas.length + 1,
              },
            ])
          }
        >
          Acrescentar coluna
        </Botao>
      </div>
    </fieldset>
  );
}

// --------------------------------------------------------------------------
export function EditorCalculados(props: {
  calculados: CalculadoPayload[];
  aoMudar: (c: CalculadoPayload[]) => void;
}) {
  function mudar(i: number, muda: Partial<CalculadoPayload>) {
    props.aoMudar(
      props.calculados.map((c, j) => (j === i ? { ...c, ...muda } : c)),
    );
  }
  return (
    <fieldset className="border border-borda rounded p-3 mb-4">
      <legend className="text-sm font-medium px-1">Campos calculados</legend>
      <p className="text-xs text-tinta-suave mb-3">
        Todo calculado declara as colunas de origem que usa — sem isso a
        linhagem quebra e a validação recusa.
      </p>
      <ul className="grid gap-3 list-none p-0 m-0">
        {props.calculados.map((c, i) => (
          <li
            key={i}
            className="border border-borda rounded p-3 grid gap-x-4 md:grid-cols-[1fr_1fr_auto]"
          >
            <Campo
              rotulo={`Calculado ${i + 1} — nome`}
              valor={c.nome}
              aoMudar={(v) => mudar(i, { nome: v })}
              obrigatorio
              monoespacado
            />
            <Selecao
              rotulo="Classe do cálculo"
              valor={c.classe}
              aoMudar={(v) => mudar(i, { classe: v })}
              opcoes={[
                { valor: "escalar", rotulo: "escalar — linha a linha" },
                { valor: "janela", rotulo: "janela — sobre partição ordenada" },
              ]}
            />
            <div className="pt-6">
              <Botao
                variante="destrutivo"
                aoClicar={() =>
                  props.aoMudar(props.calculados.filter((_, j) => j !== i))
                }
              >
                Remover
                <span className="sr-only"> calculado {i + 1}</span>
              </Botao>
            </div>
            <div className="md:col-span-3">
              <Campo
                rotulo="Expressão SQL"
                valor={c.expressao}
                aoMudar={(v) => mudar(i, { expressao: v })}
                obrigatorio
                monoespacado
                multilinha
              />
            </div>
            <Campo
              rotulo="Colunas de origem"
              valor={c.colunas_origem.join(", ")}
              aoMudar={(v) => mudar(i, { colunas_origem: lista(v) })}
              ajuda="Separe por vírgula. É a linhagem declarada do campo."
              obrigatorio
              monoespacado
            />
            {c.classe === "janela" && (
              <>
                <Campo
                  rotulo="Partição por"
                  valor={(c.particao_por ?? []).join(", ")}
                  aoMudar={(v) =>
                    mudar(i, { particao_por: lista(v).length ? lista(v) : null })
                  }
                  monoespacado
                />
                <Campo
                  rotulo="Ordena por"
                  valor={(c.ordena_por ?? []).join(", ")}
                  aoMudar={(v) =>
                    mudar(i, { ordena_por: lista(v).length ? lista(v) : null })
                  }
                  monoespacado
                />
              </>
            )}
            <div className="md:col-span-2">
              <Campo
                rotulo="Descrição"
                valor={c.descricao ?? ""}
                aoMudar={(v) => mudar(i, { descricao: v.trim() || null })}
              />
            </div>
            <div className="md:col-span-3">
              <Caixa
                rotulo="Ativo"
                marcado={c.ativo}
                aoMudar={(v) => mudar(i, { ativo: v })}
                ajuda="Desativar não apaga: o campo para de ser calculado nas próximas cargas."
              />
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-3">
        <Botao
          aoClicar={() =>
            props.aoMudar([
              ...props.calculados,
              {
                nome: "",
                expressao: "",
                colunas_origem: [],
                classe: "escalar",
                tipo_retorno: "numeric",
                particao_por: null,
                ordena_por: null,
                materializacao: "coluna",
                descricao: null,
                ativo: true,
                ordem: props.calculados.length + 1,
              },
            ])
          }
        >
          Acrescentar calculado
        </Botao>
      </div>
    </fieldset>
  );
}

// --------------------------------------------------------------------------
export function EditorRegras(props: {
  regras: RegraPayload[];
  aoMudar: (r: RegraPayload[]) => void;
}) {
  function mudar(i: number, muda: Partial<RegraPayload>) {
    props.aoMudar(props.regras.map((r, j) => (j === i ? { ...r, ...muda } : r)));
  }
  return (
    <fieldset className="border border-borda rounded p-3 mb-4">
      <legend className="text-sm font-medium px-1">Regras de qualidade</legend>
      <p className="text-xs text-tinta-suave mb-3">
        A expressão seleciona as linhas <strong>erradas</strong>: zero linhas é
        aprovado. Severidade <code>bloqueia</code> segura a publicação.
      </p>
      <ul className="grid gap-3 list-none p-0 m-0">
        {props.regras.map((r, i) => (
          <li
            key={i}
            className="border border-borda rounded p-3 grid gap-x-4 md:grid-cols-[1fr_1fr_1fr_auto]"
          >
            <Campo
              rotulo={`Regra ${i + 1} — nome`}
              valor={r.nome}
              aoMudar={(v) => mudar(i, { nome: v })}
              obrigatorio
              monoespacado
            />
            <Selecao
              rotulo="Severidade"
              valor={r.severidade}
              aoMudar={(v) => mudar(i, { severidade: v })}
              opcoes={[
                { valor: "informa", rotulo: "informa — só registra" },
                { valor: "alerta", rotulo: "alerta — reporta e publica" },
                { valor: "bloqueia", rotulo: "bloqueia — segura a publicação" },
              ]}
            />
            <Campo
              rotulo="Tolerância"
              valor={String(r.tolerancia)}
              aoMudar={(v) => mudar(i, { tolerancia: Number(v) || 0 })}
              ajuda="Fração de linhas erradas admitida antes de valer a severidade. Sob tolerância, vira alerta."
            />
            <div className="pt-6">
              <Botao
                variante="destrutivo"
                aoClicar={() =>
                  props.aoMudar(props.regras.filter((_, j) => j !== i))
                }
              >
                Remover
                <span className="sr-only"> regra {i + 1}</span>
              </Botao>
            </div>
            <div className="md:col-span-3">
              <Campo
                rotulo="Expressão SQL (linhas erradas)"
                valor={r.expressao_sql}
                aoMudar={(v) => mudar(i, { expressao_sql: v })}
                obrigatorio
                monoespacado
                multilinha
              />
            </div>
            <div className="md:col-span-2">
              <Campo
                rotulo="Descrição"
                valor={r.descricao ?? ""}
                aoMudar={(v) => mudar(i, { descricao: v.trim() || null })}
              />
            </div>
            <div className="md:col-span-4">
              <Caixa
                rotulo="Ativa"
                marcado={r.ativo}
                aoMudar={(v) => mudar(i, { ativo: v })}
              />
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-3">
        <Botao
          aoClicar={() =>
            props.aoMudar([
              ...props.regras,
              {
                nome: "",
                expressao_sql: "",
                severidade: "alerta",
                tolerancia: 0,
                descricao: null,
                ativo: true,
              },
            ])
          }
        >
          Acrescentar regra
        </Botao>
      </div>
    </fieldset>
  );
}

// --------------------------------------------------------------------------
/** Valida no servidor e, se válido, salva (nova versão). Reusado pelas telas
 * que editam só uma seção. */
export function useSalvarDataset(aoSalvar: () => void) {
  const [ocupado, setOcupado] = useState(false);
  const [resultado, setResultado] = useState<{
    ok: boolean;
    msg: string;
  } | null>(null);

  async function validar(d: DatasetPayload) {
    setOcupado(true);
    setResultado(null);
    try {
      const r = await api.validarDataset(d.chave, d);
      setResultado({ ok: r.valido, msg: r.mensagem });
      return r.valido;
    } catch (e) {
      setResultado({ ok: false, msg: (e as Error).message });
      return false;
    } finally {
      setOcupado(false);
    }
  }

  async function salvar(d: DatasetPayload) {
    setOcupado(true);
    setResultado(null);
    try {
      const r = await api.validarDataset(d.chave, d);
      if (!r.valido) {
        setResultado({ ok: false, msg: r.mensagem });
        return false;
      }
      await api.salvarDataset(d);
      setResultado({ ok: true, msg: "Nova versão salva." });
      aoSalvar();
      return true;
    } catch (e) {
      setResultado({ ok: false, msg: (e as Error).message });
      return false;
    } finally {
      setOcupado(false);
    }
  }

  return { ocupado, resultado, validar, salvar, limpar: () => setResultado(null) };
}

export function ResultadoValidacao({
  resultado,
}: {
  resultado: { ok: boolean; msg: string } | null;
}) {
  if (!resultado) return null;
  if (resultado.ok)
    return (
      <p role="status" className="text-sm text-ok mb-3">
        {resultado.msg}
      </p>
    );
  return <Erro mensagem={resultado.msg} />;
}

// --------------------------------------------------------------------------
export function DatasetForm(props: {
  inicial?: DatasetPayload;
  fontes: string[];
  classes: string[];
  aoSalvar: () => void;
  aoFechar: () => void;
}) {
  const editando = Boolean(props.inicial);
  const [d, setD] = useState<DatasetPayload>(
    () => props.inicial ?? { ...DATASET_VAZIO },
  );
  const [erros, setErros] = useState<Record<string, string>>({});
  const { ocupado, resultado, validar, salvar } = useSalvarDataset(
    props.aoSalvar,
  );

  function checar(): boolean {
    const p: Record<string, string> = {};
    if (!d.chave.trim()) p.chave = "Informe uma chave.";
    else if (!/^[a-z0-9_]+$/.test(d.chave.trim()))
      p.chave = "Use apenas letras minúsculas, números e underscore.";
    if (!d.nome.trim()) p.nome = "Informe um nome.";
    if (!d.fonte_chave) p.fonte_chave = "Escolha a fonte.";
    if (!d.padrao_arquivo.trim())
      p.padrao_arquivo = "Informe o padrão de arquivo.";
    if (!d.tabela_destino.trim())
      p.tabela_destino = "Informe a tabela de destino.";
    if (d.chave_natural.length === 0)
      p.chave_natural = "A chave natural precisa de ao menos uma coluna.";
    setErros(p);
    return Object.keys(p).length === 0;
  }

  async function aoSubmeter(e: React.FormEvent) {
    e.preventDefault();
    if (!checar()) return;
    await salvar(d);
  }

  return (
    <section aria-labelledby="form-dataset" className="grid gap-4">
      <h2 id="form-dataset" className="font-medium">
        {editando ? `Nova versão de ${d.chave}` : "Novo mapeamento"}
      </h2>
      <Aviso>
        O mapeamento liga uma fonte a uma classe: qual arquivo ler, o que
        extrair e como tipar. Salvar cria uma <strong>nova versão</strong>; as
        cargas passadas continuam apontando para a versão que as produziu.
      </Aviso>

      <form
        onSubmit={aoSubmeter}
        className="border border-borda rounded bg-superficie p-4"
      >
        {erros.geral && <Erro mensagem={erros.geral} />}
        <div className="grid gap-x-6 md:grid-cols-2">
          <Campo
            rotulo="Chave"
            valor={d.chave}
            aoMudar={(v) => setD({ ...d, chave: v })}
            erro={erros.chave}
            ajuda="Salvar sobre uma chave existente cria uma nova versão."
            obrigatorio
            monoespacado
          />
          <Campo
            rotulo="Nome"
            valor={d.nome}
            aoMudar={(v) => setD({ ...d, nome: v })}
            erro={erros.nome}
            obrigatorio
          />
          <Selecao
            rotulo="Fonte"
            valor={d.fonte_chave}
            aoMudar={(v) => setD({ ...d, fonte_chave: v })}
            opcoes={[
              { valor: "", rotulo: "— escolha —" },
              ...props.fontes.map((f) => ({ valor: f, rotulo: f })),
            ]}
          />
          <Selecao
            rotulo="Classe de informação"
            valor={d.classe_chave ?? ""}
            aoMudar={(v) => setD({ ...d, classe_chave: v || null })}
            opcoes={[
              { valor: "", rotulo: "— nenhuma —" },
              ...props.classes.map((c) => ({ valor: c, rotulo: c })),
            ]}
            ajuda="A classe de que este mapeamento é uma das fontes."
          />
          <Campo
            rotulo="Padrão de arquivo"
            valor={d.padrao_arquivo}
            aoMudar={(v) => setD({ ...d, padrao_arquivo: v })}
            erro={erros.padrao_arquivo}
            ajuda="Expressão regular; grupos nomeados viram pseudo-colunas $grupo."
            obrigatorio
            monoespacado
          />
          <Campo
            rotulo="Tabela de destino"
            valor={d.tabela_destino}
            aoMudar={(v) => setD({ ...d, tabela_destino: v })}
            erro={erros.tabela_destino}
            ajuda="A tabela da classe. Quem manda nela é a classe, não o mapeamento."
            obrigatorio
            monoespacado
          />
          <Campo
            rotulo="Chave natural"
            valor={d.chave_natural.join(", ")}
            aoMudar={(v) => setD({ ...d, chave_natural: lista(v) })}
            erro={erros.chave_natural}
            ajuda="Deve dizer o mesmo que a identidade da classe. Separe por vírgula."
            obrigatorio
            monoespacado
          />
        </div>
        <Campo
          rotulo="Descrição"
          valor={d.descricao ?? ""}
          aoMudar={(v) => setD({ ...d, descricao: v.trim() || null })}
          multilinha
        />

        <EditorColunas
          colunas={d.colunas}
          aoMudar={(colunas) => setD({ ...d, colunas })}
        />
        <EditorCalculados
          calculados={d.calculados}
          aoMudar={(calculados) => setD({ ...d, calculados })}
        />
        <EditorRegras
          regras={d.regras}
          aoMudar={(regras) => setD({ ...d, regras })}
        />

        <ResultadoValidacao resultado={resultado} />
        <div className="flex gap-2">
          <Botao carregando={ocupado} aoClicar={() => checar() && validar(d)}>
            Só validar
          </Botao>
          <Botao tipo="submit" variante="primario" carregando={ocupado}>
            Validar e salvar
          </Botao>
          <Botao aoClicar={props.aoFechar}>Cancelar</Botao>
        </div>
      </form>
    </section>
  );
}
