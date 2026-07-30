// Cliente da API de administração. Sem biblioteca: fetch resolve, e cada
// dependência a menos é imagem menor no Railway.

export type Resposta<T> = { dados: T };

export class ErroApi extends Error {
  codigo: string;
  status: number;
  constructor(codigo: string, mensagem: string, status: number) {
    super(mensagem);
    this.codigo = codigo;
    this.status = status;
  }
}

function tokenAdmin(): string | null {
  return localStorage.getItem("portal_admin_token");
}

export function definirToken(token: string) {
  if (token) localStorage.setItem("portal_admin_token", token);
  else localStorage.removeItem("portal_admin_token");
}

async function pedir<T>(
  caminho: string,
  opcoes: RequestInit = {},
): Promise<T> {
  const cabecalhos: Record<string, string> = {
    "Content-Type": "application/json",
    ...((opcoes.headers as Record<string, string>) ?? {}),
  };
  const token = tokenAdmin();
  if (token) cabecalhos["X-Admin-Token"] = token;

  const resp = await fetch(caminho, { ...opcoes, headers: cabecalhos });
  if (resp.status === 204) return undefined as T;

  const corpo = await resp.json().catch(() => null);
  if (!resp.ok) {
    const erro = corpo?.erro ?? {};
    throw new ErroApi(
      erro.codigo ?? "erro_desconhecido",
      erro.mensagem ?? `Falha ${resp.status} em ${caminho}`,
      resp.status,
    );
  }
  return corpo as T;
}

export const api = {
  fontes: () => pedir<Resposta<Fonte[]>>("/admin/api/fontes"),
  salvarFonte: (f: Partial<Fonte>) =>
    pedir<Resposta<Fonte>>("/admin/api/fontes", {
      method: "POST",
      body: JSON.stringify(f),
    }),

  datasets: () => pedir<Resposta<Dataset[]>>("/admin/api/datasets"),
  validarDataset: (chave: string, corpo: unknown) =>
    pedir<{ valido: boolean; mensagem: string }>(
      `/admin/api/datasets/${chave}/validar`,
      { method: "POST", body: JSON.stringify(corpo) },
    ),
  salvarDataset: (corpo: unknown) =>
    pedir<Resposta<Dataset>>("/admin/api/datasets", {
      method: "POST",
      body: JSON.stringify(corpo),
    }),

  execucoes: (dataset?: string) =>
    pedir<Resposta<Execucao[]>>(
      `/admin/api/execucoes${dataset ? `?dataset=${dataset}` : ""}`,
    ),
  disparar: (dataset_chave: string, janela: string, baixar: boolean) =>
    pedir<Resposta<ResultadoExecucao>>("/admin/api/execucoes", {
      method: "POST",
      body: JSON.stringify({ dataset_chave, janela, baixar }),
    }),

  publicacoes: () =>
    pedir<Resposta<Publicacao[]> & { atual: number }>("/admin/api/publicacoes"),
  reverter: (versao: number) =>
    pedir<Resposta<{ atual: number }>>(
      `/admin/api/publicacoes/${versao}/reverter`,
      { method: "POST" },
    ),

  chaves: () => pedir<Resposta<Chave[]>>("/admin/api/chaves"),
  emitirChave: (consumidor: string, quota_minuto: number, quota_dia: number) =>
    pedir<Resposta<{ prefixo: string; chave: string; aviso: string }>>(
      "/admin/api/chaves",
      {
        method: "POST",
        body: JSON.stringify({ consumidor, quota_minuto, quota_dia }),
      },
    ),
  revogarChave: (prefixo: string) =>
    pedir<Resposta<unknown>>(`/admin/api/chaves/${prefixo}`, {
      method: "DELETE",
    }),

  metricas: () => pedir<Resposta<Metrica[]>>("/admin/api/metricas"),
  salvarMetrica: (m: Partial<Metrica> & { chave: string }) =>
    pedir<Resposta<{ contas_referenciadas: string[] }>>("/admin/api/metricas", {
      method: "POST",
      body: JSON.stringify(m),
    }),

  catalogo: () => pedir<Resposta<string[]>>("/admin/api/catalogo"),
  tabela: (nome: string) =>
    pedir<Resposta<TabelaDetalhe>>(`/admin/api/catalogo/${nome}?limite=10`),
};

// --------------------------------------------------------------------------
export type Fonte = {
  chave: string;
  nome: string;
  descricao: string | null;
  tipo_transporte: string;
  url_template: string;
  encoding: string;
  separador: string;
  ativo: boolean;
  versao: number;
};

export type Coluna = {
  nome_origem: string;
  nome_destino: string;
  tipo: string;
  formato: string | null;
  obrigatoria: boolean;
  ordem: number;
};

export type Calculado = {
  nome: string;
  classe: string;
  expressao: string;
  colunas_origem: string;
  particao_por: string | null;
  descricao: string | null;
  ativo: boolean;
};

export type Regra = {
  nome: string;
  expressao_sql: string;
  severidade: string;
  tolerancia: number;
  descricao: string | null;
  ativo: boolean;
};

export type Dataset = {
  chave: string;
  nome: string;
  descricao: string | null;
  fonte_chave: string;
  padrao_arquivo: string;
  tabela_destino: string;
  chave_natural: string;
  versao: number;
  colunas: Coluna[];
  calculados: Calculado[];
  regras: Regra[];
};

export type Execucao = {
  id: number;
  dataset_chave: string;
  janela: string;
  status: string;
  trigger_tipo: string;
  iniciado_em: string;
  terminado_em: string | null;
  capturas: number;
  linhas_silver: number;
  delta_linhas: number | null;
  publicacao: number | null;
  erro: string | null;
};

export type ResultadoExecucao = {
  execucao_id: number;
  status: string;
  capturas: number;
  capturas_novas: number;
  linhas_silver: number;
  delta_linhas: number | null;
  publicacao: number | null;
  violacoes: { nome: string; severidade: string; linhas: number }[];
};

export type Publicacao = {
  versao: number;
  publicado_em: string;
  execucao_id: number | null;
  observacao: string | null;
};

export type Chave = {
  id: number;
  consumidor: string;
  prefixo: string;
  quota_minuto: number;
  quota_dia: number;
  criada_em: string;
  revogada_em: string | null;
};

export type Metrica = {
  chave: string;
  nome: string;
  formula: string;
  unidade: string;
  descricao: string | null;
  ativo: boolean;
  versao: number;
};

export type TabelaDetalhe = {
  tabela: string;
  colunas: { nome: string; tipo: string }[];
  linhas: number;
  amostra: Record<string, unknown>[];
};
