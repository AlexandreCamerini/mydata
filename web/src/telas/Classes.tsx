// A entrada principal do plano de controle.
//
// A tela antiga obrigava o operador a saber que `cvm_dfp` existe para chegar
// a uma empresa. Aqui ele parte da informação — "Empresa", "Demonstração
// financeira" — e daí enxerga quais fontes a alimentam, quais atributos estão
// em disputa, quando cada uma atualizou e se a configuração ainda descreve a
// tabela que está no banco.
import { useState } from "react";
import {
  api,
  classeParaEntrada,
  type Classe,
  type ClassePayload,
  type Frescor,
} from "../api";
import { Botao, Carregando, Erro, Selo, Tabela, Vazio, useDados } from "../ui";
import { Identidade, Linhagem, SaudeClasse } from "../objetos";
import { ClasseForm } from "./ClasseForm";

function idade(f: Frescor | undefined): string {
  if (!f || f.idade_horas === null) return "sem carga";
  if (f.idade_horas < 1) return `${Math.round(f.idade_horas * 60)} min`;
  if (f.idade_horas < 48) return `${Math.round(f.idade_horas)} h`;
  return `${Math.round(f.idade_horas / 24)} d`;
}

export function Classes() {
  const classes = useDados(() => api.classes());
  const frescor = useDados(() => api.frescor());
  const [aberta, setAberta] = useState<string | null>(null);
  // null = lista; {} = classe nova; {inicial} = nova versão de uma existente.
  const [editor, setEditor] = useState<{ inicial?: ClassePayload } | null>(null);

  if (editor) {
    return (
      <ClasseForm
        inicial={editor.inicial}
        aoSalvar={() => classes.recarregar()}
        aoFechar={() => setEditor(null)}
      />
    );
  }

  // Só na primeira carga: o recarregar pós-salvar não pode desmontar a tela.
  if (classes.carregando && !classes.dados)
    return <Carregando oque="classes de informação" />;
  if (classes.erro) return <Erro mensagem={classes.erro} />;

  const lista = classes.dados?.dados ?? [];
  if (lista.length === 0) {
    return (
      <div className="grid gap-4">
        <Vazio
          titulo="Nenhuma classe de informação cadastrada"
          dica="Uma classe é a coisa sobre a qual o portal guarda dado — Empresa, Cotação. É dela que a tabela nasce."
        />
        <div>
          <Botao variante="primario" aoClicar={() => setEditor({})}>
            Nova classe
          </Botao>
        </div>
      </div>
    );
  }

  const porChave = new Map(
    (frescor.dados?.dados ?? []).map((f) => [f.classe, f]),
  );

  return (
    <div className="grid gap-6">
      <div>
        <Botao variante="primario" aoClicar={() => setEditor({})}>
          Nova classe
        </Botao>
      </div>
      <Tabela
        legenda="Classes de informação, fontes que as alimentam e frescor"
        colunas={["Classe", "Identidade", "Fontes", "Atributos", "Atualizada há", "Situação"]}
      >
        {lista.map((c) => {
          const f = porChave.get(c.chave);
          return (
            <tr key={c.chave} className="border-b border-borda last:border-0 align-top">
              <th scope="row" className="text-left px-3 py-2">
                <button
                  onClick={() => setAberta(aberta === c.chave ? null : c.chave)}
                  aria-expanded={aberta === c.chave}
                  className="text-left font-medium underline decoration-dotted"
                >
                  {c.nome}
                </button>
                <span className="block text-xs text-tinta-suave font-mono">
                  {c.tabela}
                </span>
                {c.divergencias.length > 0 && (
                  <span className="block text-xs text-erro mt-1">
                    {c.divergencias.length} divergência(s) com o banco
                  </span>
                )}
              </th>
              <td className="px-3 py-2">
                <Identidade partes={c.chave_identidade.split(",").filter(Boolean)} />
              </td>
              <td className="px-3 py-2 text-xs">
                {c.datasets.length === 0 ? (
                  <span className="text-tinta-suave">nenhuma</span>
                ) : (
                  c.datasets.join(", ")
                )}
                {c.resolucao === "precedencia" && (
                  <span className="block text-tinta-suave">
                    resolve por precedência
                  </span>
                )}
              </td>
              <td className="px-3 py-2 tabular-nums">{c.atributos.length}</td>
              <td className="px-3 py-2 text-xs">{idade(f)}</td>
              <td className="px-3 py-2">
                <Selo texto={f?.situacao ?? "sem_carga"} />
                {f?.ultima_falha && (
                  <span className="block text-xs text-alerta mt-1">
                    última falha: #{f.ultima_falha.id}
                  </span>
                )}
              </td>
            </tr>
          );
        })}
      </Tabela>

      {aberta && (
        <Detalhe
          classe={lista.find((c) => c.chave === aberta)!}
          frescor={porChave.get(aberta)}
          aoEditar={(c) => setEditor({ inicial: classeParaEntrada(c) })}
        />
      )}
    </div>
  );
}

function Detalhe({
  classe,
  frescor,
  aoEditar,
}: {
  classe: Classe;
  frescor?: Frescor;
  aoEditar: (c: Classe) => void;
}) {
  const ddl = useDados(() => api.ddlDaClasse(classe.chave), [classe.chave]);
  const [rastreado, setRastreado] = useState<string | null>(null);
  const multiplas = classe.datasets.length > 1;

  return (
    <section aria-labelledby="det" className="grid gap-4">
      <div className="flex items-center justify-between gap-4">
        <h2 id="det" className="font-medium">
          {classe.nome}
        </h2>
        <Botao aoClicar={() => aoEditar(classe)}>
          Editar (nova versão)
        </Botao>
      </div>
      {classe.descricao && (
        <p className="text-sm text-tinta-suave">{classe.descricao}</p>
      )}

      {frescor && (
        <SaudeClasse
          c={{ ...frescor, chave: classe.chave }}
          acao={
            <a
              className="text-sm text-acento underline"
              href={`#/catalogo?tabela=${classe.tabela}`}
            >
              Ver as linhas
            </a>
          }
        />
      )}

      {classe.divergencias.length > 0 && (
        <Erro
          mensagem={`A configuração não descreve a tabela: ${classe.divergencias.join("; ")}`}
        />
      )}

      <Tabela
        legenda={`Atributos de ${classe.nome}`}
        colunas={
          multiplas
            ? ["Atributo", "Tipo", "Vem de", "Precedência", "Descrição"]
            : ["Atributo", "Tipo", "Vem de", "Descrição"]
        }
      >
        {classe.atributos.map((a) => (
          <>
          <tr key={a.nome} className="border-b border-borda last:border-0 align-top">
            <th scope="row" className="text-left px-3 py-2 font-mono text-xs">
              {/* O beco sem saída do achado 2.1 morre aqui: do atributo se
                  chega à fonte, à regra que o vigia e ao arquivo original.
                  Só busca quem abre — quarenta atributos seriam quarenta
                  chamadas se todos disparassem na montagem. */}
              <button
                onClick={() => setRastreado(rastreado === a.nome ? null : a.nome)}
                aria-expanded={rastreado === a.nome}
                className="underline decoration-dotted"
              >
                {a.nome}
                <span className="sr-only"> — de onde veio</span>
              </button>
              {a.obrigatorio && (
                <span className="text-erro ml-1" aria-label="obrigatório">
                  *
                </span>
              )}
            </th>
            <td className="px-3 py-2 text-xs">
              {a.tipo}
              {a.unidade && (
                <span className="text-tinta-suave"> ({a.unidade})</span>
              )}
            </td>
            <td className="px-3 py-2 text-xs">
              {a.origem === "calculado" ? "cálculo" : "fonte"}
            </td>
            {multiplas && (
              <td className="px-3 py-2 text-xs">
                {a.precedencia ? (
                  <span className="font-mono">{a.precedencia}</span>
                ) : (
                  <span className="text-tinta-suave">herda da classe</span>
                )}
              </td>
            )}
            <td className="px-3 py-2 text-xs text-tinta-suave max-w-md">
              {a.descricao ?? "—"}
            </td>
          </tr>
          {rastreado === a.nome && (
            <tr key={`${a.nome}-linhagem`}>
              <td colSpan={multiplas ? 5 : 4} className="px-3 py-3 bg-papel">
                <LinhagemDe classe={classe.chave} atributo={a.nome} />
              </td>
            </tr>
          )}
          </>
        ))}
      </Tabela>

      {/* O contrato existia desde a etapa 7 e nenhuma tela o lia — achado 3.4.
          Contrato publicado que ninguém publica não é contrato. Fica aqui, ao
          lado do DDL, porque os dois respondem a mesma pergunta em níveis
          diferentes: o que esta classe promete, e o que ela vira no banco. */}
      <ContratoDaClasse classe={classe.chave} />

      <details className="border border-borda rounded bg-white p-3">
        <summary className="text-sm font-medium cursor-pointer">
          DDL que esta configuração implica
        </summary>
        {ddl.carregando && <Carregando oque="DDL" />}
        {ddl.dados && (
          <pre className="mt-3 text-xs overflow-x-auto whitespace-pre-wrap" tabIndex={0}>
            {ddl.dados.dados.sentencas.join(";\n\n")}
          </pre>
        )}
      </details>
    </section>
  );
}

/** Busca a linhagem de um atributo e entrega ao objeto que a desenha. */
function LinhagemDe({ classe, atributo }: { classe: string; atributo: string }) {
  const l = useDados(() => api.linhagem(classe, atributo), [classe, atributo]);
  if (l.carregando) return <Carregando oque={`linhagem de ${atributo}`} />;
  if (l.erro) return <Erro mensagem={l.erro} />;
  if (!l.dados) return null;
  return <Linhagem l={l.dados.dados} />;
}


/** O perfil ODCS da classe — o que ela promete a quem integra.
 *
 * `<details>` e não seção aberta: é referência de integração, não coisa que se
 * lê todo dia. E só busca quem abre. */
function ContratoDaClasse({ classe }: { classe: string }) {
  const [aberto, setAberto] = useState(false);
  return (
    <details
      className="border border-borda rounded bg-white p-3"
      onToggle={(e) => setAberto((e.currentTarget as HTMLDetailsElement).open)}
    >
      <summary className="text-sm font-medium cursor-pointer">
        Contrato publicado desta classe
      </summary>
      {aberto && <CorpoDoContrato classe={classe} />}
    </details>
  );
}

function CorpoDoContrato({ classe }: { classe: string }) {
  const c = useDados(() => api.contrato(classe), [classe]);
  if (c.carregando) return <Carregando oque="o contrato" />;
  if (c.erro) return <Erro mensagem={c.erro} />;
  if (!c.dados) return null;
  const d = c.dados.dados;
  const bloqueiam = d.quality.filter((q) => q.impedePublicacao);

  return (
    <div className="mt-3 grid gap-4 text-sm">
      <p className="text-tinta-suave">{d.description.usage}</p>

      <dl className="grid sm:grid-cols-3 gap-3">
        <div>
          <dt className="text-xs text-tinta-suave">Identidade</dt>
          <dd className="mt-1">
            <Identidade partes={d.customProperties.identidade} />
          </dd>
        </div>
        <div>
          <dt className="text-xs text-tinta-suave">Versão do contrato</dt>
          <dd className="numero">
            v{d.version}
            <span className="text-xs text-tinta-suave">
              {" "}· publicação v{d.customProperties.publicacao?.versao ?? "—"}
            </span>
          </dd>
        </div>
        <div>
          <dt className="text-xs text-tinta-suave">Frescor prometido</dt>
          <dd>
            {d.slas.length === 0 ? (
              <span className="text-tinta-suave text-xs">sem SLA declarado</span>
            ) : (
              d.slas.map((s) => (
                <span key={s.property} className="text-xs">
                  {s.value} {s.unit}
                </span>
              ))
            )}
          </dd>
        </div>
      </dl>

      <div>
        <p className="text-xs text-tinta-suave mb-1">
          {/* A severidade nominal não é o que o consumidor precisa saber; a
              consequência é. Regra que bloqueia significa que todo dado
              publicado passou por ela. */}
          {bloqueiam.length} de {d.quality.length} regras impedem a publicação —
          o dado que chega ao consumidor passou por todas elas.
        </p>
        {d.quality.length > 0 && (
          <Tabela
            legenda={`Regras de qualidade de ${d.name}`}
            colunas={["Regra", "Consequência", "Tolerância", "Mapeamento"]}
          >
            {d.quality.map((q) => (
              <tr key={q.name} className="border-b border-borda last:border-0">
                <th scope="row" className="text-left px-3 py-1.5 font-mono text-xs">
                  {q.name}
                  {q.description && (
                    <span className="block font-sans text-tinta-suave">
                      {q.description}
                    </span>
                  )}
                </th>
                <td className="px-3 py-1.5">
                  <Selo texto={q.impedePublicacao ? "bloqueia" : q.severity} />
                </td>
                <td className="px-3 py-1.5 numero text-xs">{q.tolerance}</td>
                <td className="px-3 py-1.5 text-xs font-mono">
                  {q.customProperties.mapeamento}
                </td>
              </tr>
            ))}
          </Tabela>
        )}
      </div>

      <p className="text-xs text-tinta-suave border-l-2 border-acento pl-3">
        {d.customProperties.original}
      </p>

      <p className="text-xs">
        <a
          className="text-acento underline"
          href={`/v1/meta/contrato?classe=${encodeURIComponent(classe)}`}
        >
          O contrato inteiro em JSON
        </a>
        <span className="text-tinta-suave">
          {" "}— é isto que o consumidor lê para integrar.
        </span>
      </p>
    </div>
  );
}
