// A lógica que decide o que a tela Console afirma. Cada teste protege uma
// frase que estaria errada se a função errasse: "falha" sobre origem
// desligada, "há 3 min" sobre relógio em fuso trocado, zero no lugar de
// "não medido".
import { describe, expect, it } from "vitest";
import {
  agruparMetricas,
  classificarOrigem,
  commitCurto,
  deploysRecentes,
  formatarDuracao,
  formatarMs,
  haTempo,
  horaOuData,
  parseInstante,
  tomDoDeploy,
} from "./consoleLogica";

const AGORA = new Date("2026-09-28T15:00:00Z");

describe("classificarOrigem", () => {
  it("ok quando configurada e a última coleta deu certo", () => {
    expect(
      classificarOrigem({ configurada: true, ok: true, ultima_coleta: "2026-09-28T14:57:00Z" }),
    ).toBe("ok");
  });

  it("falha quando configurada e a última coleta falhou", () => {
    expect(
      classificarOrigem({ configurada: true, ok: false, ultima_coleta: "2026-09-28T14:57:00Z" }),
    ).toBe("falha");
  });

  it("não configurada é neutra mesmo com ok=false (o backend grava assim)", () => {
    expect(
      classificarOrigem({ configurada: false, ok: false, ultima_coleta: "2026-09-28T14:57:00Z" }),
    ).toBe("nao_configurada");
  });

  it("aceita ok como 0/1, como alguns bancos devolvem", () => {
    expect(classificarOrigem({ configurada: true, ok: 1, ultima_coleta: "x" })).toBe("ok");
    expect(classificarOrigem({ configurada: true, ok: 0, ultima_coleta: "x" })).toBe("falha");
  });

  it("nunca coletou: sem coleta, nem ok nem falha", () => {
    expect(classificarOrigem({ configurada: true, ok: null, ultima_coleta: null })).toBe(
      "sem_coleta",
    );
  });
});

describe("parseInstante", () => {
  it("sem fuso significa UTC, não hora local", () => {
    expect(parseInstante("2026-09-28 14:57:00")?.toISOString()).toBe("2026-09-28T14:57:00.000Z");
    expect(parseInstante("2026-09-28T14:57:00")?.toISOString()).toBe("2026-09-28T14:57:00.000Z");
  });

  it("respeita o fuso quando ele existe", () => {
    expect(parseInstante("2026-09-28T11:57:00-03:00")?.toISOString()).toBe(
      "2026-09-28T14:57:00.000Z",
    );
    expect(parseInstante("2026-09-28T14:57:00+00:00")?.toISOString()).toBe(
      "2026-09-28T14:57:00.000Z",
    );
  });

  it("nulo, vazio e lixo viram null", () => {
    expect(parseInstante(null)).toBeNull();
    expect(parseInstante("")).toBeNull();
    expect(parseInstante("ontem")).toBeNull();
  });
});

describe("haTempo", () => {
  it("minutos", () => {
    expect(haTempo("2026-09-28T14:57:00Z", AGORA)).toBe("há 3 min");
  });
  it("menos de um minuto", () => {
    expect(haTempo("2026-09-28T14:59:30Z", AGORA)).toBe("agora há pouco");
  });
  it("horas e dias", () => {
    expect(haTempo("2026-09-28T12:00:00Z", AGORA)).toBe("há 3 h");
    expect(haTempo("2026-09-25T15:00:00Z", AGORA)).toBe("há 3 d");
  });
  it("fronteiras: 59 min e 60 min", () => {
    expect(haTempo("2026-09-28T14:01:00Z", AGORA)).toBe("há 59 min");
    expect(haTempo("2026-09-28T14:00:00Z", AGORA)).toBe("há 1 h");
  });
  it("futuro (relógio adiantado) não vira número negativo", () => {
    expect(haTempo("2026-09-28T15:05:00Z", AGORA)).toBe("agora há pouco");
  });
  it("sem instante, traço", () => {
    expect(haTempo(null, AGORA)).toBe("—");
    expect(haTempo("lixo", AGORA)).toBe("—");
  });
});

describe("horaOuData", () => {
  it("mesmo dia mostra só a hora; outro dia inclui a data", () => {
    // Constrói pelo relógio local para o teste não depender do fuso da máquina.
    const agora = new Date(2026, 8, 28, 15, 0, 0);
    const hoje = new Date(2026, 8, 28, 9, 5, 0).toISOString();
    const ontem = new Date(2026, 8, 27, 23, 41, 0).toISOString();
    expect(horaOuData(hoje, agora)).toBe("09:05");
    expect(horaOuData(ontem, agora)).toBe("27/09 23:41");
  });
  it("sem instante, traço", () => {
    expect(horaOuData(null)).toBe("—");
  });
});

describe("formatarDuracao / formatarMs", () => {
  it("nulo não é zero", () => {
    expect(formatarDuracao(null)).toBe("—");
    expect(formatarMs(null)).toBe("—");
    expect(formatarDuracao(0)).toBe("0 ms");
  });
  it("milissegundos e segundos", () => {
    expect(formatarDuracao(850)).toBe("850 ms");
    expect(formatarDuracao(1340)).toBe("1,3 s");
  });
  it("latência com até uma casa", () => {
    expect(formatarMs(12.34)).toBe("12,3 ms");
    expect(formatarMs(7)).toBe("7 ms");
  });
});

describe("commitCurto", () => {
  it("abrevia em 7 caracteres", () => {
    expect(commitCurto("0123456789abcdef")).toBe("0123456");
  });
  it("ausente vira traço", () => {
    expect(commitCurto(null)).toBe("—");
    expect(commitCurto("  ")).toBe("—");
  });
});

describe("agruparMetricas", () => {
  const linhas = [
    { dia: "2026-09-28", sistema: "mcp", metrica: "situacao", valor: "atencao", fonte: "https://mcp/obs" },
    { dia: "2026-09-28", sistema: "mcp", metrica: "alertas_ativos", valor: "2", fonte: "https://mcp/obs" },
    { dia: "2026-09-28", sistema: "mcp", metrica: "alertas_criticos", valor: "0", fonte: "https://mcp/obs" },
    { dia: "2026-09-26", sistema: "mcp", metrica: "situacao", valor: "critico", fonte: "https://velha" },
    { dia: "2026-09-27", sistema: "boris", metrica: "situacao", valor: "ok", fonte: "https://boris/obs" },
  ];

  it("fica com o valor mais recente de cada métrica, seja qual for a ordem", () => {
    const [boris, mcp] = agruparMetricas([...linhas].reverse());
    expect(mcp.sistema).toBe("mcp");
    expect(mcp.situacao).toBe("atencao");
    expect(mcp.alertasAtivos).toBe(2);
    expect(mcp.alertasCriticos).toBe(0);
    expect(mcp.dia).toBe("2026-09-28");
    expect(mcp.fontes).toEqual(["https://mcp/obs"]);
    expect(boris.sistema).toBe("boris");
  });

  it("métrica ausente é null, nunca zero", () => {
    const boris = agruparMetricas(linhas).find((s) => s.sistema === "boris")!;
    expect(boris.situacao).toBe("ok");
    expect(boris.alertasAtivos).toBeNull();
    expect(boris.alertasCriticos).toBeNull();
  });

  it("situação fora do vocabulário do envelope vira null", () => {
    const [s] = agruparMetricas([
      { dia: "2026-09-28", sistema: "portal", metrica: "situacao", valor: "", fonte: "f" },
    ]);
    expect(s.situacao).toBeNull();
  });

  it("valor não numérico de alertas vira null", () => {
    const [s] = agruparMetricas([
      { dia: "2026-09-28", sistema: "portal", metrica: "alertas_ativos", valor: "abc", fonte: "f" },
    ]);
    expect(s.alertasAtivos).toBeNull();
  });

  it("lista vazia, resultado vazio", () => {
    expect(agruparMetricas([])).toEqual([]);
  });
});

describe("tomDoDeploy", () => {
  it("mapeia os status do Railway", () => {
    expect(tomDoDeploy("SUCCESS")).toBe("ok");
    expect(tomDoDeploy("failed")).toBe("erro");
    expect(tomDoDeploy("CRASHED")).toBe("erro");
    expect(tomDoDeploy("BUILDING")).toBe("andamento");
    expect(tomDoDeploy("REMOVED")).toBe("neutro");
    expect(tomDoDeploy(null)).toBe("neutro");
  });
});

describe("deploysRecentes", () => {
  const d = (deploy_id: string, quando: string | null) => ({
    sistema: "mcp", ambiente: "production", deploy_id, commit_sha: null, quando, status: "SUCCESS",
  });

  it("mais recentes primeiro, sem data por último, com limite", () => {
    const r = deploysRecentes(
      [d("a", "2026-09-01T00:00:00Z"), d("b", null), d("c", "2026-09-10T00:00:00Z"), d("e", null)],
      3,
    );
    expect(r.map((x) => x.deploy_id)).toEqual(["c", "a", "b"]);
  });

  it("não muta a entrada", () => {
    const entrada = [d("a", "2026-09-01T00:00:00Z"), d("c", "2026-09-10T00:00:00Z")];
    deploysRecentes(entrada);
    expect(entrada[0].deploy_id).toBe("a");
  });
});
