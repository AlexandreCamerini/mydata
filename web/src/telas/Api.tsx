import { useEffect, useMemo, useState } from "react";
import { Aviso, Botao, Campo, Carregando, Erro } from "../ui";

// O OpenAPI que o FastAPI gera é grande e dinâmico o bastante para não valer
// tipar campo a campo — `any` aqui é a escolha explícita de não importar um
// pacote de tipos só para isto.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Esquema = Record<string, any>;

type Parametro = {
  name: string;
  in: "query" | "path" | "header" | "cookie";
  required?: boolean;
  description?: string;
  schema?: Esquema;
};

type Operacao = {
  id: string;
  metodo: string;
  caminho: string;
  tag: string;
  resumo: string;
  descricao?: string;
  parametros: Parametro[];
  corpoSchema?: Esquema;
};

type EspecOpenApi = {
  info?: { title?: string; version?: string };
  paths: Record<string, Esquema>;
  components?: { schemas?: Record<string, Esquema> };
};

const METODOS_DOCUMENTADOS = ["get", "post", "put", "patch", "delete"];

const COR_METODO: Record<string, string> = {
  get: "bg-acento-suave text-acento border-acento",
  post: "bg-ok-suave text-ok border-ok",
  put: "bg-alerta-suave text-alerta border-alerta",
  patch: "bg-alerta-suave text-alerta border-alerta",
  delete: "bg-erro-suave text-erro border-erro",
};

function operacoesDoEspec(spec: EspecOpenApi): Operacao[] {
  const lista: Operacao[] = [];
  for (const [caminho, porMetodo] of Object.entries(spec.paths)) {
    for (const metodo of METODOS_DOCUMENTADOS) {
      const op = porMetodo[metodo];
      if (!op) continue;
      lista.push({
        id: `${metodo}:${caminho}`,
        metodo,
        caminho,
        tag: op.tags?.[0] ?? "outras",
        resumo: op.summary ?? caminho,
        descricao: op.description,
        parametros: op.parameters ?? [],
        corpoSchema: op.requestBody?.content?.["application/json"]?.schema,
      });
    }
  }
  return lista;
}

function resolver(schema: Esquema | undefined, spec: EspecOpenApi): Esquema | undefined {
  if (!schema) return schema;
  if (schema.$ref) {
    const nome = schema.$ref.split("/").pop() as string;
    return spec.components?.schemas?.[nome];
  }
  return schema;
}

/** Colapsa o padrão `anyOf: [{type}, {type: "null"}]` que o Pydantic v2 usa
 * para campo opcional em OpenAPI 3.1 — sem isto, todo parâmetro opcional
 * mostraria "anyOf" na tela em vez do tipo de verdade. */
function tipoLegivel(schema: Esquema | undefined): string {
  if (!schema) return "string";
  if (schema.anyOf) {
    const naoNulo = schema.anyOf.find((s: Esquema) => s.type !== "null");
    return naoNulo?.type ?? "string";
  }
  return schema.type ?? "string";
}

function exemploDoCorpo(schema: Esquema | undefined, spec: EspecOpenApi): unknown {
  const resolvido = resolver(schema, spec);
  if (!resolvido) return null;
  if (resolvido.properties) {
    const objeto: Record<string, unknown> = {};
    for (const [nome, propSchema] of Object.entries(resolvido.properties as Record<string, Esquema>)) {
      objeto[nome] = exemploDoCorpo(propSchema, spec);
    }
    return objeto;
  }
  if (resolvido.type === "array") return [exemploDoCorpo(resolvido.items, spec)];
  const tipo = tipoLegivel(resolvido);
  if (tipo === "integer" || tipo === "number") return resolvido.default ?? 0;
  if (tipo === "boolean") return resolvido.default ?? false;
  return resolvido.default ?? "";
}

/** Console de API: lê o `/openapi.json` que o próprio backend publica —
 * documentação e teste vêm da mesma fonte, então nunca desalinham do que
 * está de fato exposto.
 *
 * Sem dependência de terceiro. A primeira versão embutia o pacote `swagger-ui`
 * e precisou de dois remendos por incompatibilidade com React 19 (cópia
 * duplicada de React, `createRoot` ausente) — inflou o bundle do admin em
 * 15×. O parser abaixo cobre o que este OpenAPI de fato usa (parâmetros de
 * rota/query/header, corpo com `$ref` de um nível), não a especificação
 * inteira — o suficiente para documentar e testar cada rota, sem herdar a
 * superfície e o peso de uma biblioteca completa. */
export function Api() {
  const [chave, setChave] = useState("");
  const [spec, setSpec] = useState<EspecOpenApi | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    fetch("/openapi.json")
      .then((r) => {
        if (!r.ok) throw new Error(`/openapi.json respondeu ${r.status}`);
        return r.json();
      })
      .then((d) => vivo && setSpec(d))
      .catch((e) => vivo && setErro((e as Error).message));
    return () => {
      vivo = false;
    };
  }, []);

  const grupos = useMemo(() => {
    if (!spec) return [];
    const porTag = new Map<string, Operacao[]>();
    for (const op of operacoesDoEspec(spec)) {
      const lista = porTag.get(op.tag) ?? [];
      lista.push(op);
      porTag.set(op.tag, lista);
    }
    return [...porTag.entries()];
  }, [spec]);

  if (erro) return <Erro mensagem={erro} />;
  if (!spec) return <Carregando oque="rotas da API" />;

  const total = grupos.reduce((n, [, ops]) => n + ops.length, 0);

  return (
    <div className="grid gap-6">
      <Aviso>
        {total} rotas de <code>{spec.info?.title}</code> {spec.info?.version}, lidas direto de{" "}
        <code>/openapi.json</code>. Rotas <code>/admin/api/*</code> testam com a sua sessão de
        admin, sem nada a preencher. Rotas que exigem <code>X-API-Key</code> pedem a chave
        colada abaixo.
      </Aviso>
      <div className="max-w-sm">
        <Campo
          rotulo="Chave de API (para rotas que exigem X-API-Key)"
          valor={chave}
          aoMudar={setChave}
          tipo="password"
          placeholder="cole a chave aqui"
          ajuda="Fica só nesta aba, em memória — some ao sair da tela."
        />
      </div>
      {grupos.map(([tag, operacoes]) => (
        <section key={tag} aria-labelledby={`tag-${tag}`}>
          <h2 id={`tag-${tag}`} className="font-medium mb-2 capitalize">
            {tag}
          </h2>
          <div className="grid gap-2">
            {operacoes.map((op) => (
              <ItemOperacao key={op.id} operacao={op} spec={spec} chave={chave} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function ItemOperacao({
  operacao, spec, chave,
}: { operacao: Operacao; spec: EspecOpenApi; chave: string }) {
  const [aberta, setAberta] = useState(false);
  const [valores, setValores] = useState<Record<string, string>>({});
  const [corpo, setCorpo] = useState(() =>
    operacao.corpoSchema ? JSON.stringify(exemploDoCorpo(operacao.corpoSchema, spec), null, 2) : "",
  );
  const [executando, setExecutando] = useState(false);
  const [resposta, setResposta] = useState<{ status: number; corpo: string } | null>(null);
  const [erroExec, setErroExec] = useState<string | null>(null);

  const paramsVisiveis = operacao.parametros.filter((p) => p.in === "query" || p.in === "path");
  const exigeChave = operacao.parametros.some(
    (p) => p.in === "header" && p.name.toLowerCase() === "x-api-key",
  );

  async function executar() {
    setExecutando(true);
    setErroExec(null);
    setResposta(null);
    try {
      let caminho = operacao.caminho;
      const query = new URLSearchParams();
      for (const p of paramsVisiveis) {
        const v = valores[p.name];
        if (!v) continue;
        if (p.in === "path") caminho = caminho.replace(`{${p.name}}`, encodeURIComponent(v));
        else query.set(p.name, v);
      }
      const qs = query.toString();
      const cabecalhos: Record<string, string> = {};
      if (exigeChave && chave) cabecalhos["X-API-Key"] = chave;
      if (operacao.corpoSchema) cabecalhos["Content-Type"] = "application/json";

      const resp = await fetch(caminho + (qs ? `?${qs}` : ""), {
        method: operacao.metodo.toUpperCase(),
        credentials: "same-origin",
        headers: cabecalhos,
        body: operacao.corpoSchema ? corpo : undefined,
      });
      const texto = await resp.text();
      let formatado = texto;
      try {
        formatado = JSON.stringify(JSON.parse(texto), null, 2);
      } catch {
        // resposta não é JSON — mostra como o servidor mandou
      }
      setResposta({ status: resp.status, corpo: formatado });
    } catch (e) {
      setErroExec((e as Error).message);
    } finally {
      setExecutando(false);
    }
  }

  return (
    <div className="border border-borda rounded bg-white">
      <button
        onClick={() => setAberta((a) => !a)}
        aria-expanded={aberta}
        className="w-full flex items-center gap-3 px-3 py-2 text-left"
      >
        <span
          className={`inline-block rounded border px-2 py-0.5 text-xs font-mono font-medium uppercase ${
            COR_METODO[operacao.metodo] ?? "bg-superficie text-tinta-suave border-borda"
          }`}
        >
          {operacao.metodo}
        </span>
        <span className="font-mono text-xs">{operacao.caminho}</span>
        <span className="text-xs text-tinta-suave ml-auto">{operacao.resumo}</span>
      </button>

      {aberta && (
        <div className="border-t border-borda p-3 grid gap-3">
          {operacao.descricao && (
            <p className="text-xs text-tinta-suave whitespace-pre-line">{operacao.descricao}</p>
          )}
          {exigeChave && !chave && (
            <p className="text-xs text-alerta">
              Esta rota exige a chave de API preenchida acima.
            </p>
          )}
          {paramsVisiveis.map((p) => (
            <Campo
              key={p.name}
              rotulo={`${p.name} (${tipoLegivel(p.schema)}${p.required ? ", obrigatório" : ""})`}
              valor={valores[p.name] ?? ""}
              aoMudar={(v) => setValores((atual) => ({ ...atual, [p.name]: v }))}
              ajuda={p.description}
              obrigatorio={p.required}
            />
          ))}
          {operacao.corpoSchema && (
            <Campo
              rotulo="Corpo (JSON)"
              valor={corpo}
              aoMudar={setCorpo}
              multilinha
              monoespacado
            />
          )}
          <div>
            <Botao aoClicar={executar} variante="primario" carregando={executando}>
              Executar
            </Botao>
          </div>
          {erroExec && <Erro mensagem={erroExec} />}
          {resposta && (
            <div role="status" className="border border-borda rounded p-3 bg-papel">
              <p className="text-xs font-medium mb-1">
                Status:{" "}
                <span
                  className={
                    resposta.status < 300
                      ? "text-ok"
                      : resposta.status < 500
                        ? "text-alerta"
                        : "text-erro"
                  }
                >
                  {resposta.status}
                </span>
              </p>
              <pre className="text-xs overflow-x-auto whitespace-pre-wrap font-mono">
                {resposta.corpo}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
