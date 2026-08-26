import { useState } from "react";
import { api, type Fonte } from "../api";
import {
  Botao,
  Campo,
  Carregando,
  Erro,
  Selecao,
  Tabela,
  Vazio,
  useDados,
} from "../ui";

export function Fontes() {
  const { dados, erro, carregando, recarregar } = useDados(() => api.fontes());
  const [form, setForm] = useState({
    chave: "",
    nome: "",
    url_template: "",
    tipo_transporte: "http_zip",
    encoding: "utf-8",
    separador: ";",
    credencial_ref: "",
  });
  const [erroForm, setErroForm] = useState<Record<string, string>>({});
  const [salvando, setSalvando] = useState(false);

  async function salvar(e: React.FormEvent) {
    e.preventDefault();
    const problemas: Record<string, string> = {};
    if (!form.chave.trim()) problemas.chave = "Informe uma chave.";
    else if (!/^[a-z0-9_]+$/.test(form.chave))
      problemas.chave = "Use apenas letras minúsculas, números e underscore.";
    if (!form.nome.trim()) problemas.nome = "Informe um nome.";
    if (!form.url_template.trim())
      problemas.url_template = "Informe a URL de origem.";
    setErroForm(problemas);
    if (Object.keys(problemas).length) return;

    setSalvando(true);
    try {
      await api.salvarFonte(form);
      setForm({ ...form, chave: "", nome: "", url_template: "" });
      recarregar();
    } catch (e) {
      setErroForm({ geral: (e as Error).message });
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_360px]">
      <section aria-labelledby="lista-fontes">
        <h2 id="lista-fontes" className="font-medium mb-3">
          Fontes cadastradas
        </h2>
        {carregando && <Carregando oque="fontes" />}
        {erro && <Erro mensagem={erro} />}
        {dados && dados.dados.length === 0 && (
          <Vazio
            titulo="Nenhuma fonte cadastrada"
            dica="Cadastre a primeira ao lado para começar a ingerir dados."
          />
        )}
        {dados && dados.dados.length > 0 && (
          <Tabela
            legenda="Fontes de dados cadastradas"
            colunas={["Chave", "Nome", "Transporte", "Encoding", "Versão"]}
          >
            {dados.dados.map((f: Fonte) => (
              <tr key={f.chave} className="border-b border-borda last:border-0">
                <th scope="row" className="text-left px-3 py-2 font-mono text-xs">
                  {f.chave}
                </th>
                <td className="px-3 py-2">
                  {f.nome}
                  <span className="block text-xs text-tinta-suave font-mono">
                    {f.url_template}
                  </span>
                </td>
                <td className="px-3 py-2">{f.tipo_transporte}</td>
                <td className="px-3 py-2">
                  {f.encoding}
                  <span className="text-tinta-suave"> · {f.separador}</span>
                </td>
                <td className="px-3 py-2">v{f.versao}</td>
              </tr>
            ))}
          </Tabela>
        )}
      </section>

      <section aria-labelledby="nova-fonte">
        <h2 id="nova-fonte" className="font-medium mb-3">
          Nova versão de fonte
        </h2>
        <form onSubmit={salvar} className="border border-borda rounded p-4 bg-superficie">
          {erroForm.geral && <Erro mensagem={erroForm.geral} />}
          <Campo
            rotulo="Chave"
            valor={form.chave}
            aoMudar={(v) => setForm({ ...form, chave: v })}
            erro={erroForm.chave}
            ajuda="Identificador estável. Salvar sobre uma chave existente cria uma nova versão."
            obrigatorio
            monoespacado
          />
          <Campo
            rotulo="Nome"
            valor={form.nome}
            aoMudar={(v) => setForm({ ...form, nome: v })}
            erro={erroForm.nome}
            obrigatorio
          />
          <Campo
            rotulo="URL (template)"
            valor={form.url_template}
            aoMudar={(v) => setForm({ ...form, url_template: v })}
            erro={erroForm.url_template}
            ajuda="Aceita {ano}, {tipo} e {TIPO}."
            obrigatorio
            monoespacado
          />
          <Selecao
            rotulo="Transporte"
            valor={form.tipo_transporte}
            aoMudar={(v) => setForm({ ...form, tipo_transporte: v })}
            opcoes={[
              { valor: "http_zip", rotulo: "http_zip — ZIP com CSVs" },
              { valor: "http_csv", rotulo: "http_csv — CSV direto" },
              { valor: "http_json", rotulo: "http_json — JSON paginado" },
            ]}
          />
          <Campo
            rotulo="Encoding"
            valor={form.encoding}
            aoMudar={(v) => setForm({ ...form, encoding: v })}
            ajuda="latin-1 para a CVM. Ler como utf-8 corrompe acentuação."
          />
          <Campo
            rotulo="Separador"
            valor={form.separador}
            aoMudar={(v) => setForm({ ...form, separador: v })}
          />
          <Campo
            rotulo="Credencial (nome da variável de ambiente)"
            valor={form.credencial_ref ?? ""}
            aoMudar={(v) => setForm({ ...form, credencial_ref: v })}
            ajuda={
              "O token NÃO é guardado aqui: este campo recebe o nome da " +
              "variável de ambiente que o contém. Ex.: BRAPI_TOKEN envia " +
              "Authorization: Bearer. Para outro formato use " +
              "header:X-API-Key:MINHA_VAR ou query:token:MINHA_VAR."
            }
            monoespacado
          />
          <Botao tipo="submit" variante="primario" carregando={salvando}>
            Salvar fonte
          </Botao>
        </form>
      </section>
    </div>
  );
}
