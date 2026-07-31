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
              <td className="px-3 py-2 font-mono text-xs">{c.chave_identidade}</td>
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
          aoEditar={(c) => setEditor({ inicial: classeParaEntrada(c) })}
        />
      )}
    </div>
  );
}

function Detalhe({
  classe,
  aoEditar,
}: {
  classe: Classe;
  aoEditar: (c: Classe) => void;
}) {
  const ddl = useDados(() => api.ddlDaClasse(classe.chave), [classe.chave]);
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
          <tr key={a.nome} className="border-b border-borda last:border-0 align-top">
            <th scope="row" className="text-left px-3 py-2 font-mono text-xs">
              {a.nome}
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
        ))}
      </Tabela>

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
