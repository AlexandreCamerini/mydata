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

export default defineRailway(() => {
  const repo = github("AlexandreCamerini/mydata", { checkSuites: false });

  const Postgres = postgres("Postgres", { region: "us-east4-eqdc4a" });
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
    domains: ["mydata.acamerini.app", "semente.dev"],
    env: {
      BRAPI_TOKEN: preserve(),
      DATABASE_URL: preserve(),
      PORTAL_ADMIN_TOKEN: preserve(),
      PORTAL_MIGRAR_NO_BOOT: preserve(),
      PORTAL_ORIGENS: preserve(),
      PORTAL_PAPEL: preserve(),
      PORTAL_URL_PUBLICA: preserve(),
    },
  });

  const cron = service("mydata-cron", {
    source: repo,
    start: "sh scripts/entrada.sh",
    replicas: { "us-east4-eqdc4a": 1 },
    // O horário do painel só ACORDA o processo; o que roda é decisão de
    // cfg_agendamento (docs/deploy-railway.md). A frequência de verdade é
    // decidida lá — este cron diário é o que estava no painel no import.
    deploy: { cronSchedule: "0 6 * * *", restartPolicyType: "NEVER" },
    env: {
      DATABASE_URL: preserve(),
      PORTAL_PAPEL: preserve(),
      PORTAL_WEBHOOK_ALERTAS: preserve(),
    },
  });

  return project("mydata", {
    resources: [web, Postgres, cron, postgresVolume],
  });
});
