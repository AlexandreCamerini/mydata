import { useEffect, useRef, useState } from "react";
import SwaggerUIBundle from "swagger-ui";
import ReactDOM from "react-dom";
import { createRoot } from "react-dom/client";
import "swagger-ui/dist/swagger-ui.css";
import { Aviso, Campo } from "../ui";

// `swagger-ui` importa `createRoot` do topo de `react-dom`, mas essa API só
// existe em `react-dom/client` desde a divisão de entrypoints do React 18 —
// o pacote nunca foi atualizado para acompanhar. Sem isto, a tela crasha
// assim que o efeito abaixo monta o console: "createRoot is not a function".
// Remendado aqui porque o bundle é de terceiro; `react-dom` é o mesmo módulo
// compartilhado entre este arquivo e o bundle do swagger-ui, então a
// atribuição vale para os dois.
if (!("createRoot" in ReactDOM)) {
  Object.assign(ReactDOM, { createRoot });
}

/** Console de API: lê o `/openapi.json` que o próprio backend publica, então
 * nunca desalinha do que está de fato exposto — não é documentação mantida
 * à parte.
 *
 * Duas famílias de rota, duas autenticações. `/admin/api/*` anda na sessão
 * do admin, que o cookie já carrega — nada a fazer aqui além de pedir
 * `credentials: "same-origin"`, como o resto do app já faz em `api.ts`.
 * `/v1/*` é por chave do consumidor: sem uma sessão de admin para emprestar,
 * o operador cola a própria chave, que só vive em memória desta tela — o
 * `useRef` existe para o interceptor de requisição, que roda fora do ciclo
 * de render do React, ler o valor corrente sem recriar o SwaggerUI a cada
 * tecla digitada. */
export function Api() {
  const container = useRef<HTMLDivElement>(null);
  const [chave, setChave] = useState("");
  const chaveRef = useRef(chave);
  chaveRef.current = chave;

  useEffect(() => {
    if (!container.current) return;
    SwaggerUIBundle({
      url: "/openapi.json",
      domNode: container.current,
      presets: [SwaggerUIBundle.presets.apis],
      layout: "BaseLayout",
      docExpansion: "list",
      requestInterceptor: (req) => {
        req.credentials = "same-origin";
        const caminho = new URL(req.url, window.location.origin).pathname;
        if (caminho.startsWith("/v1/") && chaveRef.current) {
          req.headers = { ...req.headers, "X-API-Key": chaveRef.current };
        }
        return req;
      },
    });
  }, []);

  return (
    <div className="grid gap-4">
      <Aviso>
        Rotas <code>/admin/api/*</code> testam com a sua sessão de admin, sem
        nada a preencher. Rotas <code>/v1/*</code> são por chave de
        consumidor — cole uma abaixo para testá-las.
      </Aviso>
      <div className="max-w-sm">
        <Campo
          rotulo="Chave de API (para rotas /v1)"
          valor={chave}
          aoMudar={setChave}
          tipo="password"
          placeholder="cole a chave aqui"
          ajuda="Fica só nesta aba, em memória — some ao sair da tela."
        />
      </div>
      <div ref={container} />
    </div>
  );
}
