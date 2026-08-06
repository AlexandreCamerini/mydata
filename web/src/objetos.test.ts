// A aritmética dos objetos de observabilidade.
//
// Cada uma destas funções existe separada do componente pelo mesmo motivo:
// ela decide o que a tela afirma. Uma fração de SLA errada diz "em dia" sobre
// classe vencida; uma escala que não nasce no zero transforma 1% em montanha;
// um nulo desenhado como zero faz falta de medida parecer ausência de custo.
import { describe, expect, it } from "vitest";
import {
  bytes,
  caminho,
  fracaoDoSla,
  idadeTexto,
  proporcoes,
} from "./objetos";

describe("fracaoDoSla", () => {
  it("mede a idade contra o prazo declarado", () => {
    expect(fracaoDoSla(12, 24)).toBe(0.5);
  });

  it("satura em 1 — vencido é vencido, não 300% de barra", () => {
    expect(fracaoDoSla(72, 24)).toBe(1);
  });

  it("sem SLA não há fração", () => {
    // Classe sem prazo declarado não é classe vencida. Devolver 1 aqui
    // pintaria de vermelho tudo que ainda não tem SLA.
    expect(fracaoDoSla(500, null)).toBeNull();
    expect(fracaoDoSla(500, 0)).toBeNull();
  });

  it("sem carga não há fração", () => {
    expect(fracaoDoSla(null, 24)).toBeNull();
  });
});

describe("idadeTexto", () => {
  it("troca de unidade conforme a magnitude", () => {
    expect(idadeTexto(0.5)).toBe("30 min");
    expect(idadeTexto(5)).toBe("5 h");
    expect(idadeTexto(96)).toBe("4 d");
  });

  it("distingue 'sem carga' de 'zero hora'", () => {
    expect(idadeTexto(null)).toBe("sem carga");
    expect(idadeTexto(0)).toBe("0 min");
  });
});

describe("bytes", () => {
  it("escala até a unidade legível", () => {
    expect(bytes(915_000)).toBe("894 kB");
    expect(bytes(2_265_000_000)).toBe("2.1 GB");
  });

  it("nulo é traço, não zero", () => {
    expect(bytes(null)).toBe("—");
    expect(bytes(0)).toBe("0 B");
  });
});

describe("proporcoes", () => {
  const fases = [
    { fase: "baixar", duracao_ms: 500 },
    { fase: "parse", duracao_ms: 2000 },
    { fase: "calcular", duracao_ms: 119_500 },
    { fase: "publicar", duracao_ms: 12 },
  ];

  it("dá a cada fase a sua fatia do total", () => {
    const p = proporcoes(fases);
    const total = 500 + 2000 + 119_500 + 12;
    expect(p.map((x) => x.fase)).toEqual([
      "baixar",
      "parse",
      "calcular",
      "publicar",
    ]);
    expect(p[2].fracao).toBeCloseTo(119_500 / total, 6);
    expect(p.reduce((s, x) => s + x.fracao, 0)).toBeCloseTo(1, 6);
  });

  it("destaca a fase cara — que é a razão do objeto existir", () => {
    // Foi assim que os 119 s de `calcular` apareceram: em lista de números,
    // "119500 ms" tem a mesma tipografia que "12 ms".
    const maior = proporcoes(fases).reduce((a, b) => (b.fracao > a.fracao ? b : a));
    expect(maior.fase).toBe("calcular");
    expect(maior.fracao).toBeGreaterThan(0.9);
  });

  it("execução instantânea não divide por zero", () => {
    const p = proporcoes([{ fase: "nada", duracao_ms: 0 }]);
    expect(p[0].fracao).toBe(0);
  });

  it("fase sem duração conta como zero, não como NaN", () => {
    const p = proporcoes([
      { fase: "a", duracao_ms: null },
      { fase: "b", duracao_ms: 100 },
    ]);
    expect(p[0].fracao).toBe(0);
    expect(p[1].fracao).toBe(1);
  });
});

describe("caminho", () => {
  const pts = (vs: (number | null)[]) =>
    vs.map((v, i) => ({ rotulo: `p${i}`, valor: v }));

  it("a escala nasce no zero", () => {
    // Um eixo que começasse no mínimo transformaria 100 → 101 numa subida
    // vertical. É a forma mais barata de mentir com um gráfico honesto.
    const { min, max } = caminho(pts([100, 101]), 100, 50);
    expect(min).toBe(0);
    expect(max).toBe(101);
  });

  it("o maior valor toca o topo e o zero toca a base", () => {
    const { d } = caminho(pts([0, 10]), 100, 50);
    expect(d).toBe("M0.0,50.0 L100.0,0.0");
  });

  it("quebra o traço no nulo em vez de desenhar zero", () => {
    // Disco só o Postgres mede. No DuckDB o valor não existe, e uma linha
    // caindo até a base diria "o custo foi a zero neste dia".
    const { d } = caminho(pts([10, null, 10]), 100, 50);
    expect(d).toBe("M0.0,0.0 M100.0,0.0");
    expect(d).not.toContain("L");
  });

  it("sem nenhuma medida não desenha nada", () => {
    expect(caminho(pts([null, null]), 100, 50).d).toBe("");
    expect(caminho([], 100, 50).d).toBe("");
  });

  it("um ponto só não estoura na divisão pelo intervalo", () => {
    const { d } = caminho(pts([7]), 100, 50);
    expect(d).toBe("M0.0,0.0");
  });

  it("série constante fica reta, não vira ruído amplificado", () => {
    // Com base no mínimo, três medidas iguais viram serrilha de arredondamento.
    // Com base no zero, ficam retas — que é o que a série realmente diz.
    const { d } = caminho(pts([5, 5, 5]), 100, 50);
    expect(new Set(d.split(" ").map((p) => p.split(",")[1])).size).toBe(1);
  });
});
