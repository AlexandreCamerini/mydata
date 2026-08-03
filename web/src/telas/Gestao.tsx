// A pergunta que o operador faz primeiro — "como está o sistema" — respondida
// numa tela, sem abrir o banco nem percorrer cinco abas.
//
// Nada aqui é dado novo: frescor, chaves, execuções e catálogo já existiam,
// cada um em seu lugar. O que faltava era a visão de conjunto.
import { Carregando, Erro, Selo, Tabela, Vazio, useDados } from "../ui";
import { api } from "../api";

const fmt = new Intl.NumberFormat("pt-BR");

function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const unidades = ["kB", "MB", "GB", "TB"];
  let valor = n / 1024;
  let i = 0;
  while (valor >= 1024 && i < unidades.length - 1) {
    valor /= 1024;
    i += 1;
  }
  return `${valor.toFixed(valor < 10 ? 1 : 0)} ${unidades[i]}`;
}

function idade(horas: number | null, sla: number | null): string {
  if (horas == null) return "—";
  const dias = horas / 24;
  const texto = dias >= 2 ? `${dias.toFixed(0)} dias` : `${horas.toFixed(0)} h`;
  return sla ? `${texto} de ${(sla / 24).toFixed(0)} dias` : texto;
}

export function Gestao() {
  const { dados, erro, carregando } = useDados(() => api.gestao(), []);

  if (carregando && !dados) return <Carregando oque="o estado do hub" />;
  if (erro) return <Erro mensagem={erro} />;
  if (!dados) return <Vazio titulo="Sem dado de gestão" />;

  const g = dados.dados;
  const linhasTotais = g.classes.reduce((s, c) => s + c.linhas, 0);
  const retidas = g.classes.reduce((s, c) => s + c.retidas_no_gate, 0);

  return (
    <div className="grid gap-6">
      {g.fora_do_sla.length > 0 && (
        <p
          role="status"
          className="border border-borda rounded bg-white px-3 py-2 text-sm"
        >
          Fora do SLA: <strong>{g.fora_do_sla.join(", ")}</strong>. Uma classe
          que nunca carregou aparece aqui — é o caso mais fácil de passar
          despercebido.
        </p>
      )}

      <section aria-labelledby="resumo" className="grid gap-2">
        <h2 id="resumo" className="font-medium">
          O que o hub tem
        </h2>
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
          {[
            ["Classes", fmt.format(g.classes.length)],
            ["Linhas em silver", fmt.format(linhasTotais)],
            ["Capturas em bronze", fmt.format(g.bronze.capturas)],
            ["Espaço do original", bytes(g.bronze.bytes)],
          ].map(([rotulo, valor]) => (
            <div key={rotulo} className="border border-borda rounded bg-white p-3">
              <dt className="text-xs text-tinta-suave">{rotulo}</dt>
              <dd className="text-lg tabular-nums">{valor}</dd>
            </div>
          ))}
        </dl>
        {retidas > 0 && (
          <p className="text-xs text-tinta-suave">
            {fmt.format(retidas)} linhas carregadas e não publicadas: o gate de
            qualidade as reteve. Elas existem em silver e são invisíveis para
            quem consome.
          </p>
        )}
      </section>

      <section aria-labelledby="classes" className="grid gap-2">
        <h2 id="classes" className="font-medium">
          Por classe
        </h2>
        <Tabela
          legenda="Classes de informação com volume, fontes e frescor"
          colunas={["Classe", "Linhas", "Retidas", "Fontes", "Idade", "Situação"]}
        >
          {g.classes.map((c) => (
            <tr key={c.chave} className="border-b border-borda last:border-0">
              <th scope="row" className="text-left px-3 py-1.5">
                {c.nome}
                <span className="block text-xs text-tinta-suave font-mono">
                  {c.tabela}
                </span>
              </th>
              <td className="px-3 py-1.5 text-right tabular-nums">
                {fmt.format(c.linhas_publicadas)}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">
                {c.retidas_no_gate > 0 ? fmt.format(c.retidas_no_gate) : "—"}
              </td>
              <td className="px-3 py-1.5 text-xs">
                {c.fontes.length > 0 ? c.fontes.join(", ") : "—"}
              </td>
              <td className="px-3 py-1.5 text-xs whitespace-nowrap">
                {idade(c.idade_horas, c.sla_horas)}
              </td>
              <td className="px-3 py-1.5">
                <Selo texto={c.situacao ?? "—"} />
              </td>
            </tr>
          ))}
        </Tabela>
      </section>

      <section aria-labelledby="consumidores" className="grid gap-2">
        <h2 id="consumidores" className="font-medium">
          Quem consome
        </h2>
        {g.consumidores.length === 0 ? (
          <Vazio
            titulo="Nenhuma chave emitida"
            dica="Um consumidor novo é uma chave nova, não código novo."
          />
        ) : (
          <Tabela
            legenda="Chaves de API emitidas, com quota e escopo"
            colunas={["Consumidor", "Escopo", "Quota", "Situação"]}
          >
            {g.consumidores.map((k) => (
              <tr key={k.prefixo} className="border-b border-borda last:border-0">
                <th scope="row" className="text-left px-3 py-1.5">
                  {k.consumidor}
                  <span className="block text-xs text-tinta-suave font-mono">
                    {k.prefixo}
                  </span>
                </th>
                <td className="px-3 py-1.5 text-xs">{k.escopos || "leitura"}</td>
                <td className="px-3 py-1.5 text-xs tabular-nums whitespace-nowrap">
                  {fmt.format(k.quota_minuto)}/min · {fmt.format(k.quota_dia)}/dia
                </td>
                <td className="px-3 py-1.5">
                  <Selo texto={k.ativa ? "ativa" : "revogada"} />
                </td>
              </tr>
            ))}
          </Tabela>
        )}
      </section>

      <section aria-labelledby="correlacoes" className="grid gap-2">
        <h2 id="correlacoes" className="font-medium">
          Correlações declaradas
        </h2>
        {g.correlacoes.length === 0 ? (
          <Vazio
            titulo="Nenhuma correlação"
            dica="Sem declaração não há junção: o motor recusa a travessia."
          />
        ) : (
          <ul className="text-sm grid gap-1">
            {g.correlacoes.map((c) => (
              <li key={c.chave} className="border border-borda rounded bg-white px-3 py-2">
                <span className="font-mono text-xs">{c.chave}</span>{" "}
                — {c.origem} → {c.destino}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
