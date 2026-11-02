// A configuração de deploy, importada do projeto real por `railway config
// pull` e corrigida à mão:
//
// - o import gerava dois `const mydata` (repo e serviço) — nem compilava;
// - start, healthcheck e política de restart moravam no railway.json
//   (deprecado, corte em 2026-12-01) e o `railway config migrate` PERDIA o
//   restart na tradução — aqui estão os três, explícitos;
// - `PORTAL_WEBHOOK_ALERTAS` só existe no cron, que é quem empurra alerta.
//
// `railway config plan` antes de todo apply. O que não está aqui continua
// gerido pelo painel.
import { defineRailway, github, postgres, preserve, project, service, volume } from "railway/iac";

// PARTIAL nomeado desde 2026-09-27. Este projeto Railway hospeda também os
// serviços `mcp` (repo ~/dev/MCP) e `semente-id` (repo ~/dev/semente-id),
// criados depois deste arquivo e ausentes dele. Sem partial, este arquivo é
// "o projeto inteiro" e um `railway config apply` proporia DESTRUIR os dois
// (num arquivo de projeto, recurso omitido é recurso apagado). Com o nome,
// este repo só governa o que declara: mydata, mydata-cron, Postgres e o
// volume. Os outros dois repos exportam os partials `mcp` e `semente-id`.
// O primeiro `apply` depois desta linha registra a posse — rodar `plan`
// antes e conferir que não há "destroy" de serviço alheio.
export const partial = "mydata";

export default defineRailway(() => {
  const repo = github("AlexandreCamerini/mydata", { checkSuites: false });

  // Limite de memória de 1 GB (FinOps F1, docs/finops-mydata.md, 2026-11-02).
  // Sem limite, o cache de página do kernel enchia até ~2–2,6 GB e o Railway
  // cobra memory.current — 65–81 % da conta do projeto. O Postgres precisa de
  // ~250 MB (anon + shared_buffers + kernel); sob limite o kernel devolve
  // cache antes de matar processo. Tirar daqui = um apply volta a 24 GB.
  // Forma que o `railway config pull` gera: limite fora das opções do construtor.
  const Postgres = postgres("Postgres", { region: "us-east4-eqdc4a" });
  Postgres.deploy = { limitOverride: { containers: { cpu: 24, memoryBytes: 1_000_000_000 } } };
  const postgresVolume = volume("postgres-volume", {
    alerts: { usage: { "100": {}, "80": {}, "95": {} } },
    allowOnlineResize: true,
    region: "us-east4-eqdc4a",
    sizeMB: 50000,
  });

  const web = service("mydata", {
    source: repo,
    start: "sh scripts/entrada.sh",
    healthcheck: "/health",
    healthcheckTimeout: 30,
    // `restartPolicyType` aplica com sucesso e relê `null` — a plataforma
    // guarda o default (ON_FAILURE) como nulo, e o plan acusa este diff
    // para sempre. Comportamento efetivo é o declarado; ignorar o resíduo.
    deploy: { restartPolicyType: "ON_FAILURE", restartPolicyMaxRetries: 3 },
    replicas: { "us-east4-eqdc4a": 1 },
    // Os domínios são intencionais (decisão do Alex, 26/08/2026, mais
    // `mydata.semente.dev` anexado em 29/08 — Fase 2 do ADR-23) — não
    // "corrigir" nenhum deles fora daqui. `mydata.acamerini.app` convive
    // até o Alex decidir o corte; `PORTAL_URL_PUBLICA` já aponta para
    // `mydata.semente.dev`, que é o endereço primário a partir de agora.
    // `semente.dev` (ápice) saiu daqui em 2026-09-27: não está registrado no
    // painel do serviço (a API lista só os dois abaixo) e IaC não registra
    // domínio — com ele, `railway config plan` nem compila. Se o ápice for
    // apontado para o mydata um dia: registrar no painel, `railway config
    // pull`, e ele volta para esta lista.
    domains: ["mydata.acamerini.app", "mydata.semente.dev"],
    env: {
      BRAPI_TOKEN: preserve(),
      // Console central (ADR-25), criadas no painel em 2026-09-27/28 e
      // ausentes daqui até 2026-11-02 — um apply nesse intervalo as apagaria.
      CONSOLE_BORIS_OBS_CHAVE: preserve(),
      CONSOLE_BORIS_URL: preserve(),
      CONSOLE_CLIENT_ID: preserve(),
      CONSOLE_CLIENT_SECRET: preserve(),
      CONSOLE_COLETOR: preserve(),
      CONSOLE_MCP_URL: preserve(),
      CONSOLE_PORTAL_URL: preserve(),
      CONSOLE_RAILWAY_PROJETOS: preserve(),
      CONSOLE_RAILWAY_TOKEN: preserve(),
      DATABASE_URL: preserve(),
      PORTAL_ADMIN_TOKEN: preserve(),
      PORTAL_MIGRAR_NO_BOOT: preserve(),
      PORTAL_ORIGENS: preserve(),
      PORTAL_PAPEL: preserve(),
      PORTAL_URL_PUBLICA: preserve(),
      // Fase 2 do ADR-23: MyData como relying party do portal semente.id.
      SEMENTE_ID_CLIENT_ID: preserve(),
      SEMENTE_ID_CLIENT_SECRET: preserve(),
      SEMENTE_ID_EMAIL_DONO: preserve(),
    },
  });

  const cron = service("mydata-cron", {
    source: repo,
    start: "sh scripts/entrada.sh",
    replicas: { "us-east4-eqdc4a": 1 },
    // O horário do painel só ACORDA o processo; o que roda é decisão de
    // cfg_agendamento (docs/deploy-railway.md). 1×/dia às 06:00 UTC é
    // cadência DECIDIDA (Alex, 26/08/2026), não resíduo de import — o
    // pregão de D chega ~03:00 de São Paulo em D+1, e está aceito. A folga
    // do alerta de agendamento (app/motor/alertas.py) é calibrada para
    // isto; apertar este cron pede recalibrar lá.
    deploy: { cronSchedule: "0 6 * * *", restartPolicyType: "NEVER" },
    env: {
      DATABASE_URL: preserve(),
      PORTAL_MAX_JANELAS_POR_DISPARO: preserve(),
      PORTAL_PAPEL: preserve(),
      PORTAL_WEBHOOK_ALERTAS: preserve(),
    },
  });

  return project("mydata", {
    resources: [web, Postgres, cron, postgresVolume],
  });
});
