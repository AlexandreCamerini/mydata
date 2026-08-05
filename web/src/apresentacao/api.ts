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

/** A mensagem de `chave_invalida` é escrita para quem consome a API por
 * programa — "informe uma chave válida no cabeçalho X-API-Key". Exibida a
 * quem abriu um site, ela instrui sobre um cabeçalho HTTP que essa pessoa não
 * tem como definir, e não diz a única coisa que resolve: entrar.
 *
 * A apresentação lê `/v1` sob a sessão do dono, então 401 aqui significa
 * sempre a mesma coisa — a sessão acabou ou nunca existiu. */
/** Redirecionar para o login, ou já tentamos?
 *
 * A guarda de `destino` não é zelo: sem ela isto vira laço. A raiz serve a
 * própria apresentação, então 401 redirecionava para `/?destino=/`, que
 * renderiza a apresentação, que busca, que recebe 401 — medido na aba de rede
 * antes de existir esta função. */
export function deveRedirecionar(status: number, query: string): boolean {
  if (status !== 401) return false;
  return !new URLSearchParams(query).has("destino");
}

export function humanizar(mensagem: string, status: number): string {
  if (status === 401) {
    return "Sua sessão expirou ou ainda não foi aberta. Entre para continuar.";
  }
  if (status === 429) {
    return "Muitas consultas em pouco tempo. Espere um instante e tente de novo.";
  }
  if (status >= 500) {
    return "O servidor falhou ao responder. Se persistir, veja as execuções em /admin.";
  }
  return mensagem || `Falha ${status}`;
}

async function pedir<T>(caminho: string): Promise<T> {
  const resp = await fetch(caminho, {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });
  const corpo = await resp.json().catch(() => null);
  if (!resp.ok) {
    const erro = corpo?.erro ?? {};
    const codigo = erro.codigo ?? "erro_desconhecido";
    // Sem sessão, toda tela responderia 401 e a pessoa veria uma sucessão de
    // erros sem saber que bastava entrar. Rebate para o login levando o
    // caminho de volta.
    if (deveRedirecionar(resp.status, window.location.search)) {
      const volta = encodeURIComponent(
        window.location.pathname + window.location.hash,
      );
      window.location.assign(`/?destino=${volta}`);
    }
    throw new ErroApi(
      codigo,
      humanizar(erro.mensagem ?? "", resp.status),
      resp.status,
    );
  }
  return corpo as T;
}

export type Proveniencia = {
  fonte?: string;
  url?: string;
  // O arquivo oficial que originou a linha, e sua digital. É o fim da cadeia:
  // com o `sha256` dá para conferir que o que está guardado é byte a byte o
  // que a fonte publicou.
  arquivo?: string;
  sha256?: string;
  // O caminho para baixar o arquivo original. A API sempre devolveu; este tipo
  // nunca declarou, e é por isso que nenhuma tela o alcançava — a promessa de
  // proveniência auditável parava um clique antes do fim.
  captura?: number;
  arquivo_em?: string;
  dt_captura?: string;
  versao_documento?: number | null;
  publicacao?: number | null;
  por_atributo?: Record<string, string>;
};

/** Um contrato de opção num pregão, como `gold_opcoes` publica.
 *
 * `volatilidade_implicita` é nula em cerca de 10% dos contratos, e isso é
 * fato e não falha: o fechamento de contrato ilíquido é o último negócio, que
 * pode ser de horas antes e ficar fora do que Black-Scholes alcança. A tela
 * precisa dizer isso — um traço mudo faria parecer defeito. */
export type Opcao = {
  dt_pregao: string;
  contrato: string;
  ticker_objeto: string | null;
  tipo: "CALL" | "PUT" | null;
  strike: number;
  dt_vencimento: string;
  prazo_anos: number | null;
  premio: number | null;
  melhor_oferta_compra: number | null;
  melhor_oferta_venda: number | null;
  total_negocios: number | null;
  volume_financeiro: number | null;
  preco_objeto: number | null;
  volatilidade_implicita: number | null;
  hv21_objeto: number | null;
  preco_teorico: number | null;
  delta: number | null;
  gamma: number | null;
  vega: number | null;
  theta: number | null;
  rho: number | null;
  isin: string | null;
  proveniencia?: Proveniencia;
};

export type Vencimento = {
  dt_vencimento: string;
  contratos: number;
  menor_strike: number;
  maior_strike: number;
};

export type Cotacao = {
  dt_pregao: string;
  ticker: string;
  preco_fechamento: number | null;
  preco_maximo: number | null;
  preco_minimo: number | null;
  volume_financeiro: number | null;
  log_retorno: number | null;
  hv21: number | null;
  hv63: number | null;
  proveniencia?: Proveniencia;
};

export type ResumoDemonstracao = {
  grupo: string;
  tipo_doc: string;
  consolidado: boolean;
  linhas: number;
  de: string;
  ate: string;
};

/** O que existe para uma companhia — a base da tela de entrada dela. */
export type ResumoEmpresa = {
  cd_cvm: number;
  demonstracoes: ResumoDemonstracao[];
  trimestres: { linhas: number; de: string; ate: string } | null;
  metricas: string[];
  capturas: {
    id: number;
    nome_arquivo: string;
    sha256: string;
    tamanho_bytes: number;
  }[];
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

export type PeriodoMetricas = {
  dt_refer: string;
  tipo_doc: string;
  metricas: Record<string, number>;
  definicoes: Record<
    string,
    { nome: string; contas: string[]; unidade: string | null; descricao: string | null }
  >;
  proveniencia: { captura_id: number | null };
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
  resumo: (cd_cvm: number) =>
    pedir<{ dados: ResumoEmpresa }>(`/v1/empresas/${cd_cvm}/resumo`),
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

  metricas: (cd_cvm: number, consolidado: boolean) =>
    pedir<{ dados: PeriodoMetricas[] }>(
      `/v1/empresas/${cd_cvm}/metricas?consolidado=${consolidado}`,
    ),

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

  vencimentos: (ticker: string) =>
    pedir<{ dados: Vencimento[] }>(
      `/v1/opcoes/${encodeURIComponent(ticker)}/vencimentos`,
    ),

  opcoes: (ticker: string, f: { vencimento?: string; tipo?: string }) => {
    const p = new URLSearchParams();
    if (f.vencimento) p.set("vencimento", f.vencimento);
    if (f.tipo) p.set("tipo", f.tipo);
    p.set("limite", "2000");
    return pedir<{ dados: Opcao[] }>(
      `/v1/opcoes/${encodeURIComponent(ticker)}?${p.toString()}`,
    );
  },

  cotacoes: (ticker: string, f: { de?: string } = {}) => {
    const p = new URLSearchParams();
    if (f.de) p.set("de", f.de);
    p.set("limite", "400");
    return pedir<{ dados: Cotacao[] }>(
      `/v1/cotacoes/${encodeURIComponent(ticker)}?${p.toString()}`,
    );
  },
};
