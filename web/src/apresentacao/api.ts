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

export type Conta = {
  cd_cvm: number;
  denom_cia: string | null;
  tipo_doc: string;
  grupo: string;
  consolidado: boolean;
  dt_refer: string;
  dt_ini_exerc: string | null;
  dt_fim_exerc: string | null;
  versao: number;
  cd_conta: string;
  ds_conta: string | null;
  st_conta_fixa: string | null;
  escala_moeda: string | null;
  moeda: string | null;
  vl_conta: number | null;
  vl_conta_norm: number | null;
  itr_acumulado: boolean | null;
  proveniencia: Proveniencia;
};

export type Trimestre = {
  cd_cvm: number;
  grupo: string;
  consolidado: boolean;
  cd_conta: string;
  ds_conta: string | null;
  dt_refer: string;
  exercicio: string;
  vl_acumulado: number | null;
  vl_trimestre: number | null;
  proveniencia: Proveniencia;
};

export type Frescor = {
  classe: string;
  nome: string;
  tabela: string;
  fontes: string[];
  sla_horas: number | null;
  idade_horas: number | null;
  situacao: "em_dia" | "atrasada" | "sem_carga";
  ultima_publicacao: {
    id: number;
    dataset_chave: string;
    janela: string;
    terminado_em: string | null;
  } | null;
  ultima_falha: {
    id: number;
    dataset_chave: string;
    janela: string;
    status: string;
    erro: string | null;
    terminado_em: string | null;
  } | null;
};

export type Execucao = {
  id: number;
  dataset_chave: string;
  janela: string;
  status: string;
  trigger_tipo: string | null;
  iniciado_em: string;
  terminado_em: string | null;
  capturas: number | null;
  linhas_silver: number | null;
  erro: string | null;
};

export type FaseExecucao = {
  fase: string;
  iniciado_em: string;
  terminado_em: string | null;
  duracao_ms: number | null;
};

export type OrigemLinhagem = {
  dataset: string;
  fonte: { chave: string; url_template: string | null };
  coluna_de_origem: string | null;
  formato: string | null;
  expressao: string | null;
  colunas_que_usa: string[];
  capturas_recentes: {
    id: number;
    nome_arquivo: string;
    url: string | null;
    sha256: string;
    capturado_em: string;
    tamanho_bytes: number | null;
  }[];
  regras: { nome: string; severidade: string; descricao: string | null }[];
};

export type Linhagem = {
  classe: string;
  atributo: string;
  tipo: string;
  descricao: string | null;
  disputado: boolean;
  precedencia: string[];
  origens: OrigemLinhagem[];
  vistas: string[];
  publicacao_atual: number | null;
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

  /** Todas as linhas do recorte, seguindo o cursor até o fim (com teto). */
  demonstracoes: async (
    cd_cvm: number,
    f: { tipo?: string; grupo?: string; consolidado: boolean },
  ) => {
    const linhas: Conta[] = [];
    let cursor: string | null = null;
    for (let pagina = 0; pagina < 10; pagina++) {
      const p = new URLSearchParams();
      if (f.tipo) p.set("tipo", f.tipo);
      if (f.grupo) p.set("grupo", f.grupo);
      p.set("consolidado", String(f.consolidado));
      p.set("limite", "2000");
      if (cursor) p.set("cursor", cursor);
      const r: { dados: Conta[]; proximo_cursor: string | null } = await pedir(
        `/v1/empresas/${cd_cvm}/demonstracoes?${p.toString()}`,
      );
      linhas.push(...r.dados);
      cursor = r.proximo_cursor;
      if (!cursor) break;
    }
    return linhas;
  },

  frescor: () => pedir<{ dados: Frescor[] }>("/v1/meta/frescor"),
  execucoes: (f: { status?: string; limite?: number } = {}) => {
    const p = new URLSearchParams();
    if (f.status) p.set("status", f.status);
    if (f.limite) p.set("limite", String(f.limite));
    const qs = p.toString();
    return pedir<{ dados: Execucao[] }>(
      `/v1/meta/execucoes${qs ? `?${qs}` : ""}`,
    );
  },
  fases: (execucao_id: number) =>
    pedir<{ dados: FaseExecucao[] }>(
      `/v1/meta/execucoes/${execucao_id}/fases`,
    ),
  linhagem: (classe: string, atributo: string) =>
    pedir<{ dados: Linhagem }>(
      `/v1/meta/linhagem?classe=${encodeURIComponent(classe)}&atributo=${encodeURIComponent(atributo)}`,
    ),

  trimestres: (
    cd_cvm: number,
    f: { conta?: string; consolidado: boolean },
  ) => {
    const p = new URLSearchParams();
    if (f.conta) p.set("conta", f.conta);
    p.set("consolidado", String(f.consolidado));
    p.set("limite", "2000");
    return pedir<{ dados: Trimestre[] }>(
      `/v1/empresas/${cd_cvm}/trimestres?${p.toString()}`,
    );
  },
};
