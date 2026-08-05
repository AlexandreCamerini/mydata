// As regras que a verificação no navegador pegou, travadas em teste.
//
// Duas delas são defeitos que existiram: o laço de redirecionamento e a cadeia
// abrindo num vencimento sem prazo. Os dois passavam pelo TypeScript, pelo
// build e pelo `axe` — só apareceram olhando a tela e a aba de rede. É
// exatamente o que teste de regressão existe para não repetir.
import { describe, expect, it } from "vitest";
import { deveRedirecionar, humanizar } from "./api";
import { janela, vencimentoInicial } from "./Negociacao";

describe("humanizar", () => {
  it("traduz 401 para a única ação que resolve", () => {
    const texto = humanizar(
      "Informe uma chave válida no cabeçalho X-API-Key.",
      401,
    );
    // A mensagem da API é escrita para quem consome por programa. Exibida a
    // quem abriu um site, instrui sobre um cabeçalho HTTP que essa pessoa não
    // tem como definir — e não diz que basta entrar.
    expect(texto).not.toMatch(/X-API-Key/);
    expect(texto).toMatch(/[Ee]ntre/);
  });

  it("distingue quota de falha de servidor", () => {
    expect(humanizar("", 429)).toMatch(/[Ee]spere|instante/);
    expect(humanizar("", 503)).toMatch(/servidor/i);
  });

  it("preserva a mensagem da API quando ela já serve ao humano", () => {
    expect(humanizar("Companhia 9999 não existe.", 404)).toBe(
      "Companhia 9999 não existe.",
    );
  });

  it("nunca devolve vazio, mesmo sem mensagem", () => {
    expect(humanizar("", 418).length).toBeGreaterThan(0);
  });
});

describe("deveRedirecionar", () => {
  it("redirecionaria uma vez no 401 sem marca", () => {
    expect(deveRedirecionar(401, "")).toBe(true);
  });

  it("não redireciona de novo depois de já ter tentado", () => {
    // Este é o laço: a raiz serve a própria apresentação, então 401 mandava
    // para `/?destino=/`, que renderiza, que busca, que recebe 401. Sem esta
    // guarda o navegador gira até o usuário fechar a aba.
    expect(deveRedirecionar(401, "?destino=%2F")).toBe(false);
    expect(deveRedirecionar(401, "?destino=%2Fadmin%2F&outro=1")).toBe(false);
  });

  it("só reage a 401 — 403 e 500 são outra conversa", () => {
    for (const status of [200, 403, 429, 500, 503]) {
      expect(deveRedirecionar(status, "")).toBe(false);
    }
  });
});

describe("vencimentoInicial", () => {
  const vencs = [
    { dt_vencimento: "2026-07-31" }, // o próprio pregão: prazo zero
    { dt_vencimento: "2026-08-07" },
    { dt_vencimento: "2026-08-21" },
  ];

  it("pula o vencimento do próprio pregão", () => {
    // Sem isto a tela abre com toda implícita nula — não existe sigma que
    // resolva Black-Scholes sem tempo até o vencimento.
    expect(vencimentoInicial(vencs, "2026-07-31")).toBe("2026-08-07");
  });

  it("escolhe o primeiro futuro, não o mais líquido", () => {
    expect(vencimentoInicial(vencs, "2026-08-07")).toBe("2026-08-21");
  });

  it("cai no primeiro quando não há pregão conhecido", () => {
    expect(vencimentoInicial(vencs, undefined)).toBe("2026-07-31");
  });

  it("cai no primeiro quando todos vencem no dia — cadeia sem implícita ainda é cadeia", () => {
    expect(vencimentoInicial(vencs, "2027-01-01")).toBe("2026-07-31");
  });

  it("devolve vazio sem vencimentos, em vez de estourar", () => {
    expect(vencimentoInicial([], "2026-07-31")).toBe("");
  });
});

describe("janela do grid virtualizado", () => {
  it("no topo, começa em zero e não pede linha negativa", () => {
    const { primeira, quantas } = janela(0, 480, 748);
    expect(primeira).toBe(0);
    expect(quantas).toBeGreaterThan(0);
  });

  it("rolando, a janela acompanha e mantém folga acima", () => {
    const { primeira } = janela(34 * 100, 480, 748);
    // Cem linhas roladas, menos a folga de oito.
    expect(primeira).toBe(92);
  });

  it("nunca pede além do total — é o que evita fatia vazia no fim", () => {
    const { primeira, quantas } = janela(34 * 740, 480, 748);
    expect(primeira + quantas).toBeLessThanOrEqual(748);
  });

  it("com poucas linhas, a janela cobre todas", () => {
    const { primeira, quantas } = janela(0, 480, 5);
    expect(primeira).toBe(0);
    expect(quantas).toBe(5);
  });

  it("renderiza uma fração do total — a razão de existir", () => {
    // 748 contratos numa cadeia de PETR4. Sem virtualização, 748 linhas no
    // DOM; com ela, o que cabe na tela mais folga.
    const { quantas } = janela(0, 480, 748);
    expect(quantas).toBeLessThan(748 / 10);
  });
});
