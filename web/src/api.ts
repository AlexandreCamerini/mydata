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
  classes: () => pedir<Resposta<Classe[]>>("/admin/api/classes"),
  ddlDaClasse: (chave: string) =>
    pedir<Resposta<{ sentencas: string[]; divergencias: string[] }>>(
      `/admin/api/classes/${chave}/ddl`,
    ),
  previaClasse: (corpo: ClassePayload) =>
    pedir<Resposta<{ sentencas: string[]; divergencias: string[] }>>(
      "/admin/api/classes/previa",
      { method: "POST", body: JSON.stringify(corpo) },
    ),
  salvarClasse: (corpo: ClassePayload) =>
    pedir<Resposta<Classe> & { ddl_aplicado: string[] }>("/admin/api/classes", {
      method: "POST",
      body: JSON.stringify(corpo),
    }),
  frescor: () => pedir<Resposta<Frescor[]>>("/admin/api/frescor"),
  carga: (dataset?: string) =>
    pedir<PainelCarga>(
      `/admin/api/carga${dataset ? `?dataset=${dataset}` : ""}`,
    ),
  gestao: () => pedir<Resposta<Gestao>>("/admin/api/gestao"),
  fases: (execucao: number) =>
    pedir<Resposta<Fase[]>>(`/admin/api/execucoes/${execucao}/fases`),

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
  // `classes` vazio significa leitura de tudo — é o padrão do backend, e a
  // tela precisa dizer isso em voz alta. Enquanto este campo não era enviado,
  // toda chave criada pela interface nascia com escopo total em silêncio.
  emitirChave: (
    consumidor: string,
    quota_minuto: number,
    quota_dia: number,
    classes: string[],
  ) =>
    pedir<Resposta<{ prefixo: string; chave: string; aviso: string }>>(
      "/admin/api/chaves",
      {
        method: "POST",
        body: JSON.stringify({ consumidor, quota_minuto, quota_dia, classes }),
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
// Payloads de escrita — a forma que os POST aceitam. Difere da forma de
// leitura: listas são arrays aqui e strings separadas por vírgula lá, porque
// o GET devolve a linha do banco como está.
export type AtributoPayload = {
  nome: string;
  tipo: string;
  origem: string;
  obrigatorio: boolean;
  guarda_texto: boolean;
  unidade: string | null;
  descricao: string | null;
  ordem: number;
  precedencia: string[];
};

export type ClassePayload = {
  chave: string;
  nome: string;
  tabela: string;
  chave_identidade: string[];
  atributos: AtributoPayload[];
  indices: string[][];
  sla_horas: number | null;
  resolucao: string;
  precedencia: string[];
  descricao: string | null;
  ativo: boolean;
};

export type ColunaPayload = {
  nome_origem: string;
  nome_destino: string;
  tipo: string;
  formato: string | null;
  obrigatoria: boolean;
  ordem: number;
};

export type CalculadoPayload = {
  nome: string;
  expressao: string;
  colunas_origem: string[];
  classe: string;
  tipo_retorno: string;
  particao_por: string[] | null;
  ordena_por: string[] | null;
  materializacao: string;
  descricao: string | null;
  ativo: boolean;
  ordem: number;
};

export type RegraPayload = {
  nome: string;
  expressao_sql: string;
  severidade: string;
  tolerancia: number;
  descricao: string | null;
  ativo: boolean;
};

export type DatasetPayload = {
  chave: string;
  fonte_chave: string;
  nome: string;
  padrao_arquivo: string;
  tabela_destino: string;
  chave_natural: string[];
  classe_chave: string | null;
  politica_versao: string;
  particao: string;
  parametros: Record<string, string>;
  colunas: ColunaPayload[];
  calculados: CalculadoPayload[];
  regras: RegraPayload[];
  descricao: string | null;
  ativo: boolean;
};

/** "a, b" -> ["a","b"]; vazio/nulo -> []. */
export function lista(valor: string | null | undefined): string[] {
  return (valor ?? "")
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean);
}

/** A linha que o GET devolveu, na forma que o POST aceita. É o que permite
 * editar pela tela sem perder campo no caminho. */
export function datasetParaEntrada(d: Dataset): DatasetPayload {
  return {
    chave: d.chave,
    fonte_chave: d.fonte_chave,
    nome: d.nome,
    padrao_arquivo: d.padrao_arquivo,
    tabela_destino: d.tabela_destino,
    chave_natural: lista(d.chave_natural),
    classe_chave: d.classe_chave,
    politica_versao: d.politica_versao,
    particao: d.particao,
    parametros: d.parametros ? JSON.parse(d.parametros) : {},
    colunas: d.colunas.map((c) => ({
      nome_origem: c.nome_origem,
      nome_destino: c.nome_destino,
      tipo: c.tipo,
      formato: c.formato,
      obrigatoria: c.obrigatoria,
      ordem: c.ordem,
    })),
    calculados: d.calculados.map((c) => ({
      nome: c.nome,
      expressao: c.expressao,
      colunas_origem: lista(c.colunas_origem),
      classe: c.classe,
      tipo_retorno: c.tipo_retorno,
      particao_por: c.particao_por ? lista(c.particao_por) : null,
      ordena_por: c.ordena_por ? lista(c.ordena_por) : null,
      materializacao: c.materializacao,
      descricao: c.descricao,
      ativo: c.ativo,
      ordem: c.ordem,
    })),
    regras: d.regras.map((r) => ({
      nome: r.nome,
      expressao_sql: r.expressao_sql,
      severidade: r.severidade,
      tolerancia: r.tolerancia,
      descricao: r.descricao,
      ativo: r.ativo,
    })),
    descricao: d.descricao,
    ativo: d.ativo,
  };
}

// --------------------------------------------------------------------------
export type Atributo = {
  nome: string;
  tipo: string;
  origem: string;
  obrigatorio: boolean;
  guarda_texto: boolean;
  unidade: string | null;
  descricao: string | null;
  precedencia: string | null;
  ordem: number;
};

export type Classe = {
  chave: string;
  nome: string;
  descricao: string | null;
  tabela: string;
  chave_identidade: string;
  indices: string | null;
  resolucao: string;
  precedencia: string | null;
  sla_horas: number | null;
  ativo: boolean;
  versao: number;
  atributos: Atributo[];
  datasets: string[];
  divergencias: string[];
};

/** Grupos de índice "a,b;c" -> [["a","b"],["c"]]. */
export function indicesDe(bruto: string | null): string[][] {
  return (bruto ?? "")
    .split(";")
    .map((grupo) => lista(grupo))
    .filter((g) => g.length > 0);
}

/** A classe que o GET devolveu, na forma que o POST (e a prévia) aceitam. */
export function classeParaEntrada(c: Classe): ClassePayload {
  return {
    chave: c.chave,
    nome: c.nome,
    tabela: c.tabela,
    chave_identidade: lista(c.chave_identidade),
    indices: indicesDe(c.indices),
    sla_horas: c.sla_horas,
    resolucao: c.resolucao,
    precedencia: lista(c.precedencia),
    descricao: c.descricao,
    ativo: c.ativo,
    atributos: c.atributos.map((a, i) => ({
      nome: a.nome,
      tipo: a.tipo,
      origem: a.origem,
      obrigatorio: a.obrigatorio,
      guarda_texto: a.guarda_texto,
      unidade: a.unidade,
      descricao: a.descricao,
      ordem: a.ordem || i + 1,
      precedencia: lista(a.precedencia),
    })),
  };
}

export type Frescor = {
  classe: string;
  nome: string;
  tabela: string;
  fontes: string[];
  sla_horas: number | null;
  idade_horas: number | null;
  situacao: "em_dia" | "atrasada" | "sem_carga";
  ultima_publicacao: { id: number; dataset_chave: string; janela: string } | null;
  ultima_falha: { id: number; status: string; erro: string | null } | null;
};

export type Fase = {
  fase: string;
  iniciado_em: string;
  terminado_em: string | null;
  duracao_ms: number | null;
};

export type Fonte = {
  chave: string;
  nome: string;
  descricao: string | null;
  tipo_transporte: string;
  url_template: string;
  encoding: string;
  separador: string;
  /** Nome da variável de ambiente que guarda o token — nunca o token. */
  credencial_ref: string | null;
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
  tipo_retorno: string;
  particao_por: string | null;
  ordena_por: string | null;
  materializacao: string;
  descricao: string | null;
  ativo: boolean;
  ordem: number;
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
  classe_chave: string | null;
  politica_versao: string;
  particao: string;
  parametros: string | null;
  ativo: boolean;
  versao: number;
  colunas: Coluna[];
  calculados: Calculado[];
  regras: Regra[];
};

/** Uma linha de `relatorio_carga`: o que a execução trouxe e o que pesa.
 *
 * Os campos de bytes são nulos quando não há como medir — o DuckDB local roda
 * em memória. Nulo é o fato; zero pareceria medida. */
export type RelatorioCarga = {
  id: number;
  execucao_id: number;
  dataset_chave: string;
  classe_chave: string | null;
  janela: string;
  status: string;
  gerado_em: string;
  linhas_carregadas: number | null;
  delta_linhas: number | null;
  capturas_novas: number | null;
  bytes_capturados: number | null;
  linhas_classe: number | null;
  bytes_classe: number | null;
  bytes_bronze: number | null;
  bytes_banco: number | null;
  delta_bytes_banco: number | null;
  duracao_ms: number | null;
  gb_armazenados: number | null;
  custo_mes_usd: number | null;
  custo_mes_brl: number | null;
  cambio_usd_brl: number | null;
  crescimento_gb_dia: number | null;
  projecao_12m_gb: number | null;
  projecao_12m_usd: number | null;
};

export type PainelCarga = {
  dados: RelatorioCarga[];
  resumo: {
    bytes_banco: number | null;
    gb_armazenados: number | null;
    custo_mes_usd: number | null;
    custo_mes_brl: number | null;
    cambio_usd_brl: number | null;
    crescimento_gb_dia: number | null;
    projecao_12m_gb: number | null;
    projecao_12m_usd: number | null;
    gerado_em: string | null;
  };
  tarifa: {
    recurso: string; unidade: string; preco_usd: number;
    vigente_desde: string; fonte: string | null; descricao: string | null;
  } | null;
  medicao: { fisico: string; financeiro: string; nao_coberto: string };
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
  /** `leitura` = tudo; `classe:x,classe:y` restringe. */
  escopos: string | null;
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

/** O hub inteiro numa resposta: `/admin/api/gestao`. */
export type Gestao = {
  classes: {
    chave: string;
    nome: string;
    tabela: string;
    linhas: number;
    linhas_publicadas: number;
    retidas_no_gate: number;
    fontes: string[];
    situacao: string | null;
    idade_horas: number | null;
    sla_horas: number | null;
    ultima_publicacao: string | null;
  }[];
  bronze: { capturas: number; bytes: number };
  consumidores: {
    consumidor: string;
    prefixo: string;
    quota_minuto: number;
    quota_dia: number;
    escopos: string | null;
    criada_em: string | null;
    revogada_em: string | null;
    ativa: boolean;
  }[];
  correlacoes: { chave: string; origem: string; destino: string }[];
  fora_do_sla: string[];
};
