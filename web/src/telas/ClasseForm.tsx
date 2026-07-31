// O editor da promessa central: criar uma classe de informação pela
// interface, sem deploy. Salvar aqui gera DDL contra o banco — por isso o
// fluxo obriga a prévia: o operador vê as sentenças e as divergências antes
// de qualquer coisa rodar.
import { useState } from "react";
import { api, lista, type ClassePayload } from "../api";
import { Aviso, Botao, Caixa, Campo, Erro, Selecao } from "../ui";

const TIPOS = ["texto", "inteiro", "numero", "data", "booleano"].map((t) => ({
  valor: t,
  rotulo: t,
}));

// Estado de linha do montador: tudo string, convertido só no payload.
type LinhaAtributo = {
  nome: string;
  tipo: string;
  origem: string;
  obrigatorio: boolean;
  guarda_texto: boolean;
  unidade: string;
  precedencia: string;
  descricao: string;
};

const LINHA_VAZIA: LinhaAtributo = {
  nome: "",
  tipo: "texto",
  origem: "fonte",
  obrigatorio: false,
  guarda_texto: false,
  unidade: "",
  precedencia: "",
  descricao: "",
};

function linhasDe(p: ClassePayload): LinhaAtributo[] {
  return p.atributos.map((a) => ({
    nome: a.nome,
    tipo: a.tipo,
    origem: a.origem,
    obrigatorio: a.obrigatorio,
    guarda_texto: a.guarda_texto,
    unidade: a.unidade ?? "",
    precedencia: a.precedencia.join(", "),
    descricao: a.descricao ?? "",
  }));
}

export function ClasseForm(props: {
  inicial?: ClassePayload;
  aoSalvar: () => void;
  aoFechar: () => void;
}) {
  const editando = Boolean(props.inicial);
  const [form, setForm] = useState(() => ({
    chave: props.inicial?.chave ?? "",
    nome: props.inicial?.nome ?? "",
    tabela: props.inicial?.tabela ?? "",
    chave_identidade: props.inicial?.chave_identidade.join(", ") ?? "",
    indices:
      props.inicial?.indices.map((g) => g.join(", ")).join("; ") ?? "",
    sla_horas: props.inicial?.sla_horas?.toString() ?? "",
    resolucao: props.inicial?.resolucao ?? "unica",
    precedencia: props.inicial?.precedencia.join(", ") ?? "",
    descricao: props.inicial?.descricao ?? "",
  }));
  const [atributos, setAtributos] = useState<LinhaAtributo[]>(() =>
    props.inicial ? linhasDe(props.inicial) : [{ ...LINHA_VAZIA }],
  );
  const [erros, setErros] = useState<Record<string, string>>({});
  const [previa, setPrevia] = useState<{
    sentencas: string[];
    divergencias: string[];
  } | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [aplicado, setAplicado] = useState<string[] | null>(null);

  const multiFonte = form.resolucao === "precedencia";

  function payload(): ClassePayload {
    return {
      chave: form.chave.trim(),
      nome: form.nome.trim(),
      tabela: form.tabela.trim(),
      chave_identidade: lista(form.chave_identidade),
      indices: form.indices
        .split(";")
        .map((g) => lista(g))
        .filter((g) => g.length > 0),
      sla_horas: form.sla_horas.trim() ? Number(form.sla_horas) : null,
      resolucao: form.resolucao,
      precedencia: lista(form.precedencia),
      descricao: form.descricao.trim() || null,
      ativo: props.inicial?.ativo ?? true,
      atributos: atributos.map((a, i) => ({
        nome: a.nome.trim(),
        tipo: a.tipo,
        origem: a.origem,
        obrigatorio: a.obrigatorio,
        guarda_texto: a.guarda_texto,
        unidade: a.unidade.trim() || null,
        descricao: a.descricao.trim() || null,
        ordem: i + 1,
        precedencia: lista(a.precedencia),
      })),
    };
  }

  function validar(): boolean {
    const p: Record<string, string> = {};
    if (!form.chave.trim()) p.chave = "Informe uma chave.";
    else if (!/^[a-z0-9_]+$/.test(form.chave.trim()))
      p.chave = "Use apenas letras minúsculas, números e underscore.";
    if (!form.nome.trim()) p.nome = "Informe um nome.";
    if (!form.tabela.trim()) p.tabela = "Informe a tabela.";
    else if (!/^[a-z0-9_]+$/.test(form.tabela.trim()))
      p.tabela = "Use apenas letras minúsculas, números e underscore.";
    if (lista(form.chave_identidade).length === 0)
      p.chave_identidade = "A identidade precisa de ao menos um atributo.";
    if (form.sla_horas.trim() && !/^\d+$/.test(form.sla_horas.trim()))
      p.sla_horas = "Horas, em número inteiro.";
    const nomes = atributos.map((a) => a.nome.trim()).filter(Boolean);
    if (nomes.length === 0) p.atributos = "Declare ao menos um atributo.";
    const fora = lista(form.chave_identidade).filter((c) => !nomes.includes(c));
    if (fora.length && !p.chave_identidade)
      p.chave_identidade = `Cita atributo que não existe: ${fora.join(", ")}`;
    setErros(p);
    return Object.keys(p).length === 0;
  }

  function mudarLinha(i: number, muda: Partial<LinhaAtributo>) {
    setAtributos((ls) => ls.map((l, j) => (j === i ? { ...l, ...muda } : l)));
    setPrevia(null);
  }

  function moverLinha(i: number, delta: -1 | 1) {
    setAtributos((ls) => {
      const alvo = i + delta;
      if (alvo < 0 || alvo >= ls.length) return ls;
      const novo = [...ls];
      [novo[i], novo[alvo]] = [novo[alvo], novo[i]];
      return novo;
    });
    setPrevia(null);
  }

  // A prévia é a porta do salvar: primeiro o operador vê o DDL e as
  // divergências; só então o botão de aplicar aparece.
  async function verDdl(e: React.FormEvent) {
    e.preventDefault();
    if (!validar()) return;
    setOcupado(true);
    setPrevia(null);
    try {
      const r = await api.previaClasse(payload());
      setPrevia(r.dados);
    } catch (err) {
      setErros({ geral: (err as Error).message });
    } finally {
      setOcupado(false);
    }
  }

  async function salvar() {
    setOcupado(true);
    try {
      const r = await api.salvarClasse(payload());
      setAplicado(r.ddl_aplicado);
      props.aoSalvar();
    } catch (err) {
      setErros({ geral: (err as Error).message });
      setPrevia(null);
    } finally {
      setOcupado(false);
    }
  }

  if (aplicado) {
    return (
      <section
        aria-labelledby="classe-salva"
        className="border border-borda rounded bg-white p-4"
      >
        <h2 id="classe-salva" className="font-medium mb-2">
          Classe {form.chave} salva
        </h2>
        {aplicado.length > 0 ? (
          <>
            <p className="text-sm mb-2">DDL aplicado no banco:</p>
            <pre className="text-xs overflow-x-auto mb-3" tabIndex={0}>
              {aplicado.join("\n")}
            </pre>
          </>
        ) : (
          <p className="text-sm mb-3">
            Nenhum DDL precisou rodar — a tabela já refletia a configuração.
          </p>
        )}
        <Botao aoClicar={props.aoFechar}>Voltar à lista</Botao>
      </section>
    );
  }

  return (
    <section aria-labelledby="form-classe" className="grid gap-4">
      <h2 id="form-classe" className="font-medium">
        {editando ? `Nova versão de ${form.chave}` : "Nova classe de informação"}
      </h2>
      <Aviso>
        Salvar uma classe <strong>gera DDL contra o banco</strong>: a tabela
        nasce (ou evolui) da configuração. O DDL aparece aqui antes de rodar.
      </Aviso>

      <form onSubmit={verDdl} className="border border-borda rounded bg-white p-4">
        {erros.geral && <Erro mensagem={erros.geral} />}

        <div className="grid gap-x-6 md:grid-cols-2">
          <Campo
            rotulo="Chave"
            valor={form.chave}
            aoMudar={(v) => setForm({ ...form, chave: v })}
            erro={erros.chave}
            ajuda="Identificador estável. Salvar sobre uma chave existente cria uma nova versão."
            obrigatorio
            monoespacado
          />
          <Campo
            rotulo="Nome"
            valor={form.nome}
            aoMudar={(v) => setForm({ ...form, nome: v })}
            erro={erros.nome}
            obrigatorio
          />
          <Campo
            rotulo="Tabela"
            valor={form.tabela}
            aoMudar={(v) => setForm({ ...form, tabela: v })}
            erro={erros.tabela}
            ajuda="A tabela física é consequência da classe — nasce daqui, não de migração."
            obrigatorio
            monoespacado
          />
          <Campo
            rotulo="Chave de identidade"
            valor={form.chave_identidade}
            aoMudar={(v) => setForm({ ...form, chave_identidade: v })}
            erro={erros.chave_identidade}
            ajuda="Atributos que dizem quando duas linhas falam da mesma coisa. Separe por vírgula."
            obrigatorio
            monoespacado
          />
          <Campo
            rotulo="Índices"
            valor={form.indices}
            aoMudar={(v) => setForm({ ...form, indices: v })}
            ajuda="Grupos separados por ponto e vírgula; colunas por vírgula. Ex.: sensor; sensor, medido_em"
            monoespacado
          />
          <Campo
            rotulo="SLA (horas)"
            valor={form.sla_horas}
            aoMudar={(v) => setForm({ ...form, sla_horas: v })}
            erro={erros.sla_horas}
            ajuda="Idade máxima do dado antes de a classe aparecer como atrasada. Vazio = sem SLA."
          />
          <Selecao
            rotulo="Resolução multi-fonte"
            valor={form.resolucao}
            aoMudar={(v) => setForm({ ...form, resolucao: v })}
            opcoes={[
              { valor: "unica", rotulo: "única — uma fonte alimenta a classe" },
              {
                valor: "precedencia",
                rotulo: "precedência — fontes disputam, a vista resolve",
              },
            ]}
            ajuda="Com precedência, a linha publicada sai de uma vista que escolhe por atributo."
          />
          {multiFonte && (
            <Campo
              rotulo="Precedência da classe"
              valor={form.precedencia}
              aoMudar={(v) => setForm({ ...form, precedencia: v })}
              ajuda="Datasets em ordem de preferência, separados por vírgula. Atributo sem precedência própria herda esta."
              monoespacado
            />
          )}
        </div>
        <Campo
          rotulo="Descrição"
          valor={form.descricao}
          aoMudar={(v) => setForm({ ...form, descricao: v })}
          multilinha
        />

        <h3 className="font-medium mt-2 mb-1">Atributos</h3>
        <p className="text-xs text-tinta-suave mb-3">
          A ordem aqui é a ordem das colunas na tabela.
        </p>
        {erros.atributos && <Erro mensagem={erros.atributos} />}

        <ul className="grid gap-3 list-none p-0 m-0">
          {atributos.map((a, i) => (
            <li
              key={i}
              className="border border-borda rounded p-3 grid gap-x-4 md:grid-cols-[1fr_1fr_1fr_auto]"
            >
              <Campo
                rotulo={`Atributo ${i + 1} — nome`}
                valor={a.nome}
                aoMudar={(v) => mudarLinha(i, { nome: v })}
                obrigatorio
                monoespacado
              />
              <Selecao
                rotulo="Tipo"
                valor={a.tipo}
                aoMudar={(v) => mudarLinha(i, { tipo: v })}
                opcoes={TIPOS}
              />
              <Selecao
                rotulo="Origem"
                valor={a.origem}
                aoMudar={(v) => mudarLinha(i, { origem: v })}
                opcoes={[
                  { valor: "fonte", rotulo: "fonte" },
                  { valor: "calculado", rotulo: "calculado" },
                ]}
                ajuda="Calculado exige um campo calculado que o produza."
              />
              <div
                className="flex md:flex-col gap-1 items-start pt-6"
                role="group"
                aria-label={`Mover ou remover atributo ${i + 1}`}
              >
                <Botao
                  aoClicar={() => moverLinha(i, -1)}
                  desabilitado={i === 0}
                >
                  ↑<span className="sr-only"> subir atributo {i + 1}</span>
                </Botao>
                <Botao
                  aoClicar={() => moverLinha(i, 1)}
                  desabilitado={i === atributos.length - 1}
                >
                  ↓<span className="sr-only"> descer atributo {i + 1}</span>
                </Botao>
                <Botao
                  variante="destrutivo"
                  aoClicar={() => {
                    setAtributos((ls) => ls.filter((_, j) => j !== i));
                    setPrevia(null);
                  }}
                >
                  Remover
                </Botao>
              </div>
              <div className="md:col-span-2">
                <Campo
                  rotulo="Unidade"
                  valor={a.unidade}
                  aoMudar={(v) => mudarLinha(i, { unidade: v })}
                  ajuda="Ex.: R$, °C. Só documenta; não converte."
                />
              </div>
              {multiFonte && (
                <div className="md:col-span-2">
                  <Campo
                    rotulo="Precedência deste atributo"
                    valor={a.precedencia}
                    aoMudar={(v) => mudarLinha(i, { precedencia: v })}
                    ajuda="Vazio herda a da classe. A melhor fonte para um atributo não é necessariamente a melhor para o resto."
                    monoespacado
                  />
                </div>
              )}
              <div className="md:col-span-3">
                <Campo
                  rotulo="Descrição"
                  valor={a.descricao}
                  aoMudar={(v) => mudarLinha(i, { descricao: v })}
                />
              </div>
              <div className="md:col-span-4">
                <Caixa
                  rotulo="Obrigatório"
                  marcado={a.obrigatorio}
                  aoMudar={(v) => mudarLinha(i, { obrigatorio: v })}
                />
                <Caixa
                  rotulo="Guardar texto original"
                  marcado={a.guarda_texto}
                  aoMudar={(v) => mudarLinha(i, { guarda_texto: v })}
                  ajuda="Cria a coluna sombra <nome>_txt com a representação exata do arquivo."
                />
              </div>
            </li>
          ))}
        </ul>

        <div className="flex gap-2 mt-4">
          <Botao
            aoClicar={() => setAtributos((ls) => [...ls, { ...LINHA_VAZIA }])}
          >
            Acrescentar atributo
          </Botao>
          <Botao tipo="submit" variante="primario" carregando={ocupado}>
            Ver DDL antes de salvar
          </Botao>
          <Botao aoClicar={props.aoFechar}>Cancelar</Botao>
        </div>
      </form>

      {previa && (
        <section
          aria-labelledby="previa-ddl"
          className="border border-borda rounded bg-white p-4"
        >
          <h3 id="previa-ddl" className="font-medium mb-2">
            O que vai rodar no banco
          </h3>
          {previa.divergencias.length > 0 && (
            <Aviso>
              <strong>Divergências com o banco hoje:</strong>
              <ul className="list-disc ml-5 mt-1">
                {previa.divergencias.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            </Aviso>
          )}
          <pre
            className="text-xs overflow-x-auto whitespace-pre-wrap mb-3"
            tabIndex={0}
          >
            {previa.sentencas.join(";\n\n")}
          </pre>
          <div className="flex gap-2">
            <Botao variante="primario" carregando={ocupado} aoClicar={salvar}>
              {editando ? "Salvar nova versão e aplicar" : "Criar classe e aplicar"}
            </Botao>
            <Botao aoClicar={() => setPrevia(null)}>Voltar ao formulário</Botao>
          </div>
        </section>
      )}
    </section>
  );
}
