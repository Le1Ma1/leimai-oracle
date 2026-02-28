import { handleRequest } from "../support/server.mjs";

function rebuildOriginalUrl(req) {
  const base = "http://localhost";
  const reqUrl = new URL(req.url || "/", base);
  const rewrittenPath = reqUrl.searchParams.get("__path");
  if (rewrittenPath == null) return;

  reqUrl.searchParams.delete("__path");
  const pathPart = String(rewrittenPath || "").replace(/^\/+/, "");
  const pathname = pathPart ? `/${pathPart}` : "/";
  const qs = reqUrl.searchParams.toString();
  req.url = qs ? `${pathname}?${qs}` : pathname;
}

export default async function vercelHandler(req, res) {
  try {
    rebuildOriginalUrl(req);
    await handleRequest(req, res);
  } catch (error) {
    res.statusCode = 500;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.end(JSON.stringify({ ok: false, error: "internal_error", detail: String(error?.message || error) }));
  }
}
