// The usage-count endpoint (TELEMETRY.md). It takes a ping only when it is exactly the documented shape, stores the
// counts with the day it arrived, and never reads or stores the sender's IP address.
const APPS = new Set(["claude-code", "codex", "cursor", "windsurf", "gemini", "copilot", "qwen-code", "kimi-code",
  "qoder", "iflow", "cline"]);
const BUCKET = /^(0|1-9|10-99|100-999|1000-9999|10000\+)$/;
const FIELDS = ["schema", "id", "cli", "engine", "macos", "arch", "cohort", "apps", "backend", "week", "memories"];
const WEEK = ["sessions", "saves", "recalls", "forgets"];
const VERSION = /^\d{1,3}\.\d{1,3}\.\d{1,4}([.+-][0-9A-Za-z.]{1,20})?$/;

const nullOr = (v, ok) => v === null || ok(v);
const str = (re) => (v) => typeof v === "string" && re.test(v);
const sameKeys = (o, keys) => o && typeof o === "object" && !Array.isArray(o) &&
  Object.keys(o).length === keys.length && keys.every((k) => k in o);

export function valid(p) {
  return sameKeys(p, FIELDS) && p.schema === 1 &&
    str(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)(p.id) &&
    nullOr(p.cli, str(VERSION)) && nullOr(p.engine, str(VERSION)) &&
    nullOr(p.macos, str(/^\d{2}\.\d{1,2}$/)) && nullOr(p.arch, (v) => v === "arm64" || v === "x86_64") &&
    nullOr(p.cohort, str(/^20\d{2}-W\d{2}$/)) &&
    Array.isArray(p.apps) && p.apps.length <= APPS.size && p.apps.every((a) => APPS.has(a)) &&
    nullOr(p.backend, (v) => ["claude-cli", "anthropic-api", "none"].includes(v)) &&
    sameKeys(p.week, WEEK) && WEEK.every((k) => nullOr(p.week[k], str(BUCKET))) &&
    nullOr(p.memories, str(BUCKET));
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== "POST" || url.pathname !== "/v1/ping") return new Response(null, { status: 404 });
    const text = await request.text();
    if (text.length > 2048) return new Response(null, { status: 413 });
    let p;
    try { p = JSON.parse(text); } catch { return new Response(null, { status: 400 }); }
    if (!valid(p)) return new Response(null, { status: 400 });
    const day = new Date().toISOString().slice(0, 10);
    await env.DB.prepare(
      "insert or ignore into pings(day, id, cli, engine, macos, arch, cohort, apps, backend, sessions, saves, " +
      "recalls, forgets, memories) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
      .bind(day, p.id, p.cli, p.engine, p.macos, p.arch, p.cohort, JSON.stringify([...p.apps].sort()), p.backend,
        p.week.sessions, p.week.saves, p.week.recalls, p.week.forgets, p.memories).run();
    return new Response(null, { status: 204 });
  },
  async scheduled(_event, env) {
    const cutoff = new Date(Date.now() - 395 * 86400e3).toISOString().slice(0, 10);
    await env.DB.prepare("delete from pings where day < ?").bind(cutoff).run();
  },
};
