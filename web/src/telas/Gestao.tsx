// A pergunta que o operador faz primeiro — "como está o sistema" — respondida
// numa tela, sem abrir o banco nem percorrer cinco abas.
//
// Nada aqui é dado novo: frescor, chaves, execuções e catálogo já existiam,
// cada um em seu lugar. O que faltava era a visão de conjunto.
//
// Duas correções da auditoria moram nesta tela. A 2.2: "quanto isto pesa" era
// respondido em dois lugares, cada um com metade — aqui saía o bronze (915 kB)
// e em Carga saía o banco (2,11 GB), e quem abria esta primeiro recebia o
// número menos relevante. Agora os dois aparecem juntos, com o link para o
// detalhe carga a carga. A 3.2: as correlações eram uma lista de nomes;
// agora dizem por qual atributo atravessam e podem ser executadas daqui.
import { useState } from "react";
import { Botao, Carregando, Erro, Selo, Tabela, Vazio, useDados } from "../ui";
import { SaudeClasse, bytes } from "../objetos";
import { api, type Agendamento, type Alerta, type Correlacao } from "../api";

const fmt = new Intl.NumberFormat("pt-BR");

/** "hoje 23:59", "amanhã 06:00", senão "26/08 23:59" — a agenda é para bater
 * o olho, e data completa em toda linha esconde justamente a mais próxima. */
function quando(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const hora = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  const hoje = new Date();
  const amanha = new Date(hoje);
  amanha.setDate(hoje.getDate() + 1);
  const mesmoDia = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
  if (mesmoDia(d, hoje)) return `hoje ${hora}`;
  if (mesmoDia(d, amanha)) return `amanhã ${hora}`;
  return `${d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })} ${hora}`;
}

/** O semáforo e a lista do que precisa de intervenção — o primeiro bloco da
 * tela, porque é a primeira pergunta: "tem algo que eu precise fazer?".
 *
 * Antes, falha ficava enterrada numa lista de 50 execuções e SLA vencido era
 * uma frase num banner. O alerta traz a ação junto (a rota da tela onde se
 * age): alarme sem porta de saída é só ansiedade com timestamp. */
function Semaforo() {
  const { dados, erro, carregando } = useDados(() => api.alertas(), []);
  if (carregando && !dados) return <Carregando oque="alertas" />;
  if (erro) return <Erro mensagem={erro} />;
  if (!dados) return null;

  const { alertas, resumo } = dados.dados;
  const cor = {
    ok: "border-ok bg-ok-suave text-ok",
    atencao: "border-alerta bg-alerta-suave text-alerta",
    critico: "border-erro bg-erro-suave text-erro",
  }[resumo.situacao];
  const frase = {
    ok: "Tudo em dia",
    atencao: `${resumo.atencao} ponto${resumo.atencao > 1 ? "s" : ""} de atenção`,
    critico: `${resumo.critico} alerta${resumo.critico > 1 ? "s" : ""} crítico${resumo.critico > 1 ? "s" : ""}`,
  }[resumo.situacao];

  return (
    <section aria-labelledby="semaforo" className="grid gap-2">
      <h2 id="semaforo" className="sr-only">
        Situação do hub
      </h2>
      <p
        role="status"
        className={`border rounded px-4 py-3 text-lg font-medium ${cor}`}
      >
        {frase}
        {resumo.situacao === "critico" && resumo.atencao > 0 && (
          <span className="text-sm font-normal">
            {" "}
            · {resumo.atencao} de atenção
          </span>
        )}
        {resumo.situacao === "ok" && (
          <span className="block text-xs font-normal text-tinta-suave mt-0.5">
            Nenhuma classe atrasada, nenhuma falha nas últimas 24h, nenhuma
            credencial ausente.
          </span>
        )}
      </p>
      {alertas.length > 0 && (
        <ul className="grid gap-2">
          {alertas.map((a) => (
            <ItemAlerta key={`${a.tipo}:${a.titulo}`} a={a} />
          ))}
        </ul>
      )}
    </section>
  );
}

function ItemAlerta({ a }: { a: Alerta }) {
  const critico = a.severidade === "critico";
  return (
    <li
      className={`border rounded p-3 grid gap-1 ${
        critico ? "border-erro bg-erro-suave" : "border-alerta bg-alerta-suave"
      }`}
    >
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <p className={`text-sm font-medium ${critico ? "text-erro" : "text-alerta"}`}>
          {a.titulo}
        </p>
        <a
          href={a.acao.rota}
          className={`text-xs underline whitespace-nowrap ${
            critico ? "text-erro" : "text-alerta"
          }`}
        >
          {a.acao.rotulo} →
        </a>
      </div>
      <p className="text-xs text-tinta-suave">{a.detalhe}</p>
    </li>
  );
}

/** Próximas cargas, já resolvidas do cron para "hoje 23:59".
 *
 * `cfg_agendamento` nunca teve tela: o horário do COTAHIST só existia como
 * `59 23 * * 1-5` no banco, e o operador não tinha como saber o que o sistema
 * fará em seguida — só o que ele já fez. */
function ProximasCargas() {
  const { dados, erro, carregando } = useDados(() => api.agendamentos(), []);
  if (carregando && !dados) return <Carregando oque="a agenda" />;
  if (erro) return <Erro mensagem={erro} />;
  const lista = (dados?.dados ?? []).filter((a) => a.ativo);
  if (lista.length === 0) return null;

  return (
    <section aria-labelledby="agenda" className="grid gap-2">
      <h2 id="agenda" className="font-medium">
        Próximas cargas
      </h2>
      <Tabela
        legenda="Agendamentos ativos com o próximo disparo esperado"
        colunas={["Agendamento", "Próxima", "Última rodada"]}
      >
        {lista.map((a: Agendamento) => (
          <tr key={a.chave} className="border-b border-borda last:border-0">
            <th scope="row" className="text-left px-3 py-1.5">
              {a.chave}
              <span className="block text-xs text-tinta-suave font-mono">
                {a.cron}
                {a.timezone ? ` · ${a.timezone}` : ""}
              </span>
            </th>
            <td className="px-3 py-1.5 text-sm numero whitespace-nowrap">
              {quando(a.proxima)}
            </td>
            <td className="px-3 py-1.5">
              {a.ultima_situacao ? (
                <Selo texto={a.ultima_situacao} />
              ) : (
                <span className="text-xs text-tinta-suave">nunca rodou</span>
              )}
            </td>
          </tr>
        ))}
      </Tabela>
    </section>
  );
}

export function Gestao() {
  const { dados, erro, carregando } = useDados(() => api.gestao(), []);
  // O painel de custo é a outra metade da pergunta "quanto isto pesa". Ele
  // falha sozinho sem levar a tela junto: sem medida de disco o hub continua
  // descritível.
  const custo = useDados(() => api.carga(), []);

  if (carregando && !dados) return <Carregando oque="o estado do hub" />;
  if (erro) return <Erro mensagem={erro} />;
  if (!dados) return <Vazio titulo="Sem dado de gestão" />;

  const g = dados.dados;
  const resumo = custo.dados?.resumo;
  const linhasTotais = g.classes.reduce((s, c) => s + c.linhas, 0);
  const retidas = g.classes.reduce((s, c) => s + c.retidas_no_gate, 0);

  return (
    <div className="grid gap-6">
      {/* O banner "Fora do SLA" virou alerta do semáforo: mesma informação,
          agora com severidade, contexto e a ação do lado. */}
      <Semaforo />

      <ProximasCargas />

      <section aria-labelledby="resumo" className="grid gap-2">
        <h2 id="resumo" className="font-medium">
          O que o hub tem, e quanto pesa
        </h2>
        <dl className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 text-sm">
          {[
            ["Classes", fmt.format(g.classes.length), ""],
            ["Linhas em silver", fmt.format(linhasTotais), ""],
            ["Capturas em bronze", fmt.format(g.bronze.capturas), ""],
            ["Arquivos originais", bytes(g.bronze.bytes),
             "somados como a fonte os publicou"],
            ["Bronze em disco",
             g.bronze.ocupado_bytes === null ? "—" : bytes(g.bronze.ocupado_bytes),
             // Com o TOAST comprimindo (ADR-21), o arquivo publicado e o
             // espaço ocupado deixam de coincidir. Mostrar só o primeiro fazia
             // a gestão superestimar o próprio custo.
             g.bronze.ocupado_bytes === null
               ? "só o Postgres mede"
               : "com índices, já comprimido"],
            [
              "Banco inteiro",
              resumo?.gb_armazenados != null
                ? `${resumo.gb_armazenados.toFixed(2)} GB`
                : "—",
              "com índices e derivado",
            ],
            [
              "Custo por mês",
              resumo?.custo_mes_usd != null
                ? `US$ ${resumo.custo_mes_usd.toFixed(2)}`
                : "—",
              resumo?.custo_mes_brl != null
                ? `R$ ${resumo.custo_mes_brl.toFixed(2)}`
                : "estimado sobre o disco",
            ],
          ].map(([rotulo, valor, nota]) => (
            <div
              key={rotulo}
              className="border border-borda rounded bg-superficie p-3"
            >
              <dt className="rotulo">{rotulo}</dt>
              {/* A nota vai dentro do `dd`: um `div` de lista de definição só
                  aceita `dt` e `dd`, e o `p` solto aqui era violação de
                  `definition-list` — pega pelo axe, não pelo olho. */}
              <dd className="text-lg numero">
                {valor}
                {nota && (
                  <span className="block text-xs text-tinta-suave mt-1 font-sans">
                    {nota}
                  </span>
                )}
              </dd>
            </div>
          ))}
        </dl>
        <p className="text-xs text-tinta-suave">
          {retidas > 0 && (
            <>
              {fmt.format(retidas)} linhas carregadas e não publicadas: o gate de
              qualidade as reteve. Elas existem em silver e são invisíveis para
              quem consome.{" "}
            </>
          )}
          Carga a carga, com crescimento e projeção, em{" "}
          <a className="text-acento underline" href="#/carga">
            Carga e custo
          </a>
          .
        </p>
      </section>

      <section aria-labelledby="classes" className="grid gap-3">
        <h2 id="classes" className="font-medium">
          Por classe
        </h2>
        <div className="grid gap-3 lg:grid-cols-2">
          {g.classes.map((c) => (
            <SaudeClasse
              key={c.chave}
              c={c}
              acao={
                <a
                  className="text-sm text-acento underline"
                  href={`#/catalogo?tabela=${c.tabela}`}
                >
                  Ver as linhas
                </a>
              }
            />
          ))}
        </div>
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
                <td className="px-3 py-1.5 text-xs numero whitespace-nowrap">
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

      <Correlacoes />
    </div>
  );
}

/** As travessias declaradas, e o que elas devolvem.
 *
 * A correlação existe para o consumidor não reinventar a junção. Listar só o
 * nome dela não prova que funciona — e o dono não tinha como conferir sem
 * abrir o banco (achado 3.2). */
function Correlacoes() {
  const { dados, erro, carregando } = useDados(() => api.correlacoes(), []);
  const lista = dados?.dados ?? [];

  return (
    <section aria-labelledby="correlacoes" className="grid gap-2">
      <h2 id="correlacoes" className="font-medium">
        Correlações declaradas
      </h2>
      {carregando && <Carregando oque="correlações" />}
      {erro && <Erro mensagem={erro} />}
      {dados && lista.length === 0 && (
        <Vazio
          titulo="Nenhuma correlação"
          dica="Sem declaração não há junção: o motor recusa a travessia."
        />
      )}
      <div className="grid gap-3">
        {lista.map((c) => (
          <Travessia key={c.chave} c={c} />
        ))}
      </div>
    </section>
  );
}

function Travessia({ c }: { c: Correlacao }) {
  const [linhas, setLinhas] = useState<Record<string, unknown>[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [indo, setIndo] = useState(false);

  async function atravessar() {
    setIndo(true);
    setErro(null);
    try {
      const r = await api.atravessar(c.chave, 5);
      setLinhas(r.dados);
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setIndo(false);
    }
  }

  // `proveniencia` vem em toda resposta de dado e é um objeto: mostrada como
  // coluna, encheria a tabela de "[object Object]". A linhagem tem tela
  // própria em Classes.
  const colunas =
    linhas && linhas.length > 0
      ? Object.keys(linhas[0]).filter((k) => k !== "proveniencia")
      : [];

  return (
    <div className="border border-borda rounded bg-superficie p-3 grid gap-2">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <p className="text-sm">
            <span className="font-mono text-xs">{c.chave}</span> — {c.origem} →{" "}
            {c.destino}
          </p>
          <p className="text-xs text-tinta-suave">
            por <span className="font-mono">{c.por.origem}</span> ={" "}
            <span className="font-mono">{c.por.destino}</span>
            {c.relacionamento && <> · {c.relacionamento}</>}
          </p>
          {c.descricao && (
            <p className="text-xs text-tinta-suave mt-1">{c.descricao}</p>
          )}
        </div>
        <Botao carregando={indo} aoClicar={atravessar}>
          Atravessar
        </Botao>
      </div>

      {erro && <Erro mensagem={erro} />}
      {linhas !== null && linhas.length === 0 && (
        <p className="text-sm text-tinta-suave">
          A travessia é válida e não devolveu linha nenhuma. Declaração correta
          sobre dado que ainda não foi carregado tem exatamente esta cara.
        </p>
      )}
      {linhas !== null && linhas.length > 0 && (
        <div className="overflow-x-auto">
          <Tabela
            legenda={`Primeiras linhas de ${c.chave}`}
            colunas={colunas}
          >
            {linhas.map((l, i) => (
              <tr key={i} className="border-b border-borda last:border-0">
                {colunas.map((k) => (
                  <td key={k} className="px-3 py-1.5 text-xs whitespace-nowrap">
                    {l[k] === null || l[k] === undefined
                      ? "—"
                      : String(l[k])}
                  </td>
                ))}
              </tr>
            ))}
          </Tabela>
        </div>
      )}
    </div>
  );
}
