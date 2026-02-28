import { pollChainNow } from "../../support/server.mjs";

function getBearerToken(req) {
  const auth = String(req.headers?.authorization || "");
  const m = auth.match(/^Bearer\s+(.+)$/i);
  return m ? m[1].trim() : "";
}

function isAuthorized(req) {
  const secret = String(process.env.CRON_SECRET || "");
  if (!secret) return false;
  const headerSecret = String(req.headers?.["x-cron-secret"] || "");
  const bearer = getBearerToken(req);
  return headerSecret === secret || bearer === secret;
}

export default async function cronPollHandler(req, res) {
  if (!["GET", "POST"].includes(String(req.method || "GET").toUpperCase())) {
    res.statusCode = 405;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.end(JSON.stringify({ ok: false, error: "method_not_allowed" }));
    return;
  }
  if (!isAuthorized(req)) {
    res.statusCode = 401;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.end(JSON.stringify({ ok: false, error: "unauthorized_cron" }));
    return;
  }
  try {
    const summary = await pollChainNow();
    res.statusCode = 200;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.end(JSON.stringify({ ok: true, ...summary }));
  } catch (error) {
    res.statusCode = 500;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.end(JSON.stringify({ ok: false, error: "poll_failed", detail: String(error?.message || error) }));
  }
}
