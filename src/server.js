const http = require("node:http");
const { URL } = require("node:url");

const {
  buildMethodologyPayload,
  buildRankingsLikePayload,
  createErrorEnvelope,
  maybeRequireAuth,
} = require("./api");
const { stripLockedData } = require("./denylist");
const { MonetizationService } = require("./monetization");
const { MinuteRateLimiter } = require("./ratelimit");

const limiter = new MinuteRateLimiter(10);
const monetization = new MonetizationService();

function sendJson(res, status, payload) {
  const body = JSON.stringify(stripLockedData(payload));
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
  });
  res.end(body);
}

function queryToObject(searchParams) {
  const out = {};
  for (const [key, value] of searchParams.entries()) {
    out[key] = value;
  }
  return out;
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      if (chunks.length === 0) {
        resolve({});
        return;
      }
      try {
        const parsed = JSON.parse(Buffer.concat(chunks).toString("utf8"));
        resolve(parsed);
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}

function createAppServer() {
  return http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://localhost");
    const query = queryToObject(url.searchParams);
    const nowMsHeader = req.headers["x-now-ms"];
    const nowMs =
      nowMsHeader !== undefined && /^\d+$/.test(String(nowMsHeader))
        ? Number(nowMsHeader)
        : Date.now();
    const now = new Date(nowMs);
    const memberId = req.headers["x-member-id"] || "anon";

    const rate = limiter.check(memberId, nowMs);
    if (!rate.allowed) {
      const limited = createErrorEnvelope(
        "RATE_LIMITED",
        "per-member per-minute limit exceeded",
        429
      );
      return sendJson(res, limited.status, limited.payload);
    }

    if (!query.tier && req.headers["x-tier"]) {
      query.tier = req.headers["x-tier"];
    }

    const authError = maybeRequireAuth(query, req.headers);
    if (authError) {
      return sendJson(res, authError.status, authError.payload);
    }

    if (req.method === "GET" && url.pathname === "/rankings") {
      const result = buildRankingsLikePayload(query, now, "rankings");
      return sendJson(res, result.status, result.payload);
    }

    if (req.method === "GET" && url.pathname === "/summaries") {
      const result = buildRankingsLikePayload(query, now, "summaries");
      return sendJson(res, result.status, result.payload);
    }

    if (req.method === "GET" && url.pathname === "/methodology") {
      const result = buildMethodologyPayload(now);
      return sendJson(res, result.status, result.payload);
    }

    if (req.method === "GET" && url.pathname === "/plan") {
      try {
        const payload = monetization.buildPlanPayload({
          locale: query.locale,
        });
        return sendJson(res, 200, payload);
      } catch (error) {
        const err = createErrorEnvelope("BAD_REQUEST", error.message, 400);
        return sendJson(res, err.status, err.payload);
      }
    }

    if (req.method === "GET" && url.pathname === "/checkout") {
      const orderId = query.order_id;
      if (!orderId) {
        const err = createErrorEnvelope("BAD_REQUEST", "order_id is required", 400);
        return sendJson(res, err.status, err.payload);
      }
      const order = monetization.getOrder(orderId);
      if (!order) {
        const err = createErrorEnvelope("NOT_FOUND", "order not found", 404);
        return sendJson(res, err.status, err.payload);
      }
      return sendJson(res, 200, order);
    }

    if (req.method === "POST" && url.pathname === "/checkout/create") {
      try {
        const body = await readJsonBody(req);
        const created = monetization.createOrder({
          ...body,
          member_id: body.member_id || req.headers["x-member-id"] || "anon",
          created_at_ms: nowMs,
        });
        return sendJson(res, 200, created);
      } catch (error) {
        const err = createErrorEnvelope("BAD_REQUEST", error.message, 400);
        return sendJson(res, err.status, err.payload);
      }
    }

    if (req.method === "POST" && url.pathname === "/checkout/pay") {
      try {
        const body = await readJsonBody(req);
        const result = monetization.submitPayment({
          ...body,
          occurred_at_ms: body.occurred_at_ms || nowMs,
        });
        return sendJson(res, 200, result);
      } catch (error) {
        const err = createErrorEnvelope("BAD_REQUEST", error.message, 400);
        return sendJson(res, err.status, err.payload);
      }
    }

    if (req.method === "POST" && url.pathname === "/checkout/confirm") {
      try {
        const body = await readJsonBody(req);
        const result = monetization.confirmOrder(body);
        return sendJson(res, 200, result);
      } catch (error) {
        const err = createErrorEnvelope("BAD_REQUEST", error.message, 400);
        return sendJson(res, err.status, err.payload);
      }
    }

    const notFound = createErrorEnvelope("NOT_FOUND", "endpoint not found", 404);
    return sendJson(res, notFound.status, notFound.payload);
  });
}

if (require.main === module) {
  const port = Number(process.env.PORT || "3000");
  const server = createAppServer();
  server.listen(port, () => {
    // Keep stdout minimal for automation.
    process.stdout.write(`mdp server listening on ${port}\n`);
  });
}

module.exports = {
  createAppServer,
  monetization,
};
