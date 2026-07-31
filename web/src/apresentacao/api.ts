// Cliente da apresentação. Lê SOMENTE /v1 — nunca o banco, nunca a API de
// admin. Cada tela daqui é um teste do contrato público: se algo faltar, o
// buraco é da API e se fecha lá.
//
// Nenhuma chave vive aqui. Em dev o servidor roda com PORTAL_API_ABERTA=1;
// em produção o acesso é resolvido no servidor (Fase 5), porque chave de API
// no navegador é chave pública.

export class ErroApi extends Error {
  codigo: string;
  status: number;
  constructor(codigo: string, mensagem: string, status: number) {
    super(mensagem);
    this.codigo = codigo;
    this.status = status;
  }
}

async function pedir<T>(caminho: string): Promise<T> {
  const resp = await fetch(caminho, {
    headers: { Accept: "application/json" },
  });
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

export type Proveniencia = {
  fonte?: string;
  url?: string;
  dt_captura?: string;
  versao_documento?: number | null;
  publicacao?: number | null;
  por_atributo?: Record<string, string>;
};

export type Empresa = {
  cd_cvm: number;
  cnpj: string | null;
  denom_social: string | null;
  denom_comerc: string | null;
  setor_atividade: string | null;
  situacao: string | null;
  controle_acionario: string | null;
  uf: string | null;
  municipio: string | null;
  dt_registro: string | null;
  ticker: string | null;
  nome_pregao: string | null;
  setor_b3: string | null;
  segmento_listagem: string | null;
  dt_listagem: string | null;
  listada_b3: boolean | null;
  proveniencia: Proveniencia;
};

export type FiltrosEmpresas = {
  q?: string;
  segmento?: string;
  listada_b3?: boolean;
  com_balanco?: boolean;
  cursor?: string;
  limite?: number;
};

export type MetaAtributo = {
  nome: string;
  tipo: string;
  origem: string;
  unidade: string | null;
  descricao: string | null;
  precedencia: string[];
};

export type MetaClasse = {
  chave: string;
  nome: string;
  descricao: string | null;
  identidade: string[];
  resolucao: string;
  precedencia: string[];
  fontes: string[];
  atributos: MetaAtributo[];
};

export const api = {
  empresas: (f: FiltrosEmpresas) => {
    const p = new URLSearchParams();
    if (f.q) p.set("q", f.q);
    if (f.segmento) p.set("segmento", f.segmento);
    if (f.listada_b3) p.set("listada_b3", "true");
    if (f.com_balanco) p.set("com_balanco", "true");
    if (f.cursor) p.set("cursor", f.cursor);
    if (f.limite) p.set("limite", String(f.limite));
    const qs = p.toString();
    return pedir<{ dados: Empresa[]; total: number; proximo_cursor: string | null }>(
      `/v1/empresas${qs ? `?${qs}` : ""}`,
    );
  },
  empresa: (cd_cvm: number) =>
    pedir<{ dados: Empresa }>(`/v1/empresas/${cd_cvm}`),
  classes: () => pedir<{ dados: MetaClasse[] }>("/v1/meta/classes"),
};
