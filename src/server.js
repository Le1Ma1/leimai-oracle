const http = require("node:http");
const path = require("node:path");
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

const CHECKOUT_PROVIDER_ERROR_STATUS = {
  RPC_TIMEOUT: 504,
  RPC_RATE_LIMITED: 429,
  RPC_BAD_RESPONSE: 502,
  RPC_TX_NOT_FOUND: 404,
  RPC_UNSUPPORTED_CHAIN: 400,
};

function pickIdempotencyKey(headers, body) {
  const fromHeader = headers["x-idempotency-key"];
  if (fromHeader !== undefined && String(fromHeader).trim() !== "") {
    return String(fromHeader).trim();
  }
  if (
    body &&
    typeof body === "object" &&
    body.idempotency_key !== undefined &&
    String(body.idempotency_key).trim() !== ""
  ) {
    return String(body.idempotency_key).trim();
  }
  return "";
}

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

function requireMemberHeader(headers) {
  const value = headers["x-member-id"];
  if (value === undefined || String(value).trim() === "") {
    return {
      ok: false,
      error: createErrorEnvelope(
        "UNAUTHORIZED",
        "member authentication is required",
        401
      ),
    };
  }
  return {
    ok: true,
    member_id: String(value).trim(),
  };
}

function toCheckoutErrorEnvelope(error) {
  const code = String(error && error.code ? error.code : "").trim();
  if (Object.prototype.hasOwnProperty.call(CHECKOUT_PROVIDER_ERROR_STATUS, code)) {
    return createErrorEnvelope(code, code, CHECKOUT_PROVIDER_ERROR_STATUS[code]);
  }
  if (code.startsWith("RPC_CONFIG_MISSING_")) {
    return createErrorEnvelope("BAD_REQUEST", code, 400);
  }
  if (code === "ACCESS_DENIED_BY_MEMBER") {
    return createErrorEnvelope("FORBIDDEN", code, 403);
  }
  return createErrorEnvelope(
    "BAD_REQUEST",
    error && error.message ? error.message : "BAD_REQUEST",
    400
  );
}

function createAppServer(options = {}) {
  const limiter = options.limiter || new MinuteRateLimiter(10);
  const checkoutLimiter =
    options.checkoutLimiter || new MinuteRateLimiter(10);
  const monetization =
    options.monetization ||
    new MonetizationService({
      persistence_path:
        options.persistencePath ||
        (options.enablePersistence
          ? path.join(
              process.cwd(),
              "artifacts",
              "state",
              "monetization_state.json"
            )
          : null),
      enable_reconcile_timer: options.enableReconcileTimer || false,
      reconcile_interval_ms: options.reconcileIntervalMs || 15_000,
      getConfirmationsByUniqueId: options.getConfirmationsByUniqueId,
      chain_provider: options.chainProvider,
      chain_mock: options.chainMock,
      chain_mode: options.chainMode,
      chain_fixtures_dir: options.chainFixturesDir,
      tron_rpc_url: options.tronRpcUrl,
      arbitrum_rpc_url: options.arbitrumRpcUrl,
      ethereum_rpc_url: options.ethereumRpcUrl,
      rpc_fetch_impl: options.rpcFetchImpl,
      tron_api_key: options.tronApiKey,
      rpc_request_timeout_ms: options.rpcRequestTimeoutMs,
      rpc_max_attempts: options.rpcMaxAttempts,
      rpc_base_backoff_ms: options.rpcBaseBackoffMs,
      rpc_rate_limit_per_minute: options.rpcRateLimitPerMinute,
      rpc_sleep_impl: options.rpcSleepImpl,
      rpc_now_fn: options.rpcNowFn,
    });
  const buildCommitRaw =
    options.buildCommit !== undefined ? options.buildCommit : process.env.BUILD_COMMIT;
  const buildCommit =
    buildCommitRaw === undefined || buildCommitRaw === null || String(buildCommitRaw).trim() === ""
      ? null
      : String(buildCommitRaw).trim();
  const providerSoT = monetization.getProviderOperationalStatus({
    now_ms: Date.now(),
  });

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

    if (url.pathname.startsWith("/checkout")) {
      const checkoutRate = checkoutLimiter.check(memberId, nowMs);
      if (!checkoutRate.allowed) {
        const limited = createErrorEnvelope(
          "RATE_LIMITED",
          "checkout per-member per-minute limit exceeded",
          429
        );
        return sendJson(res, limited.status, limited.payload);
      }
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

    if (req.method === "GET" && url.pathname === "/ops/health") {
      return sendJson(res, 200, {
        ok: true,
        data: {
          chain_mode: providerSoT.chain_mode,
          provider_ready: providerSoT.provider_ready,
          rpc_config_present: {
            arbitrum: providerSoT.rpc_config_present.arbitrum,
            tron: providerSoT.rpc_config_present.tron,
          },
          build_commit: buildCommit,
          provider_config_hash: providerSoT.provider_config_hash,
          now_epoch: nowMs,
        },
      });
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

    if (req.method === "GET" && url.pathname === "/checkout/status") {
      const memberAuth = requireMemberHeader(req.headers);
      if (!memberAuth.ok) {
        return sendJson(
          res,
          memberAuth.error.status,
          memberAuth.error.payload
        );
      }
      const orderId = query.order_id;
      if (!orderId) {
        const err = createErrorEnvelope("BAD_REQUEST", "order_id is required", 400);
        return sendJson(res, err.status, err.payload);
      }
      try {
        const status = monetization.getOrderStatus({
          order_id: orderId,
          member_id: memberAuth.member_id,
        });
        if (!status) {
          const err = createErrorEnvelope("NOT_FOUND", "order not found", 404);
          return sendJson(res, err.status, err.payload);
        }
        return sendJson(res, 200, status);
      } catch (error) {
        const err = toCheckoutErrorEnvelope(error);
        return sendJson(res, err.status, err.payload);
      }
    }

    if (req.method === "POST" && url.pathname === "/checkout/create") {
      try {
        const body = await readJsonBody(req);
        const idempotencyKey = pickIdempotencyKey(req.headers, body);
        const memberIdForCheckout = body.member_id || req.headers["x-member-id"] || "anon";
        const wrapped = monetization.executeIdempotent({
          scope: "checkout/create",
          member_id: memberIdForCheckout,
          idempotency_key: idempotencyKey,
          request_body: {
            ...body,
            member_id: memberIdForCheckout,
          },
          handler: () =>
            monetization.createOrder({
              ...body,
              member_id: memberIdForCheckout,
              created_at_ms: nowMs,
            }),
        });
        return sendJson(res, wrapped.status_code, wrapped.response);
      } catch (error) {
        const err = createErrorEnvelope("BAD_REQUEST", error.message, 400);
        return sendJson(res, err.status, err.payload);
      }
    }

    if (req.method === "POST" && url.pathname === "/checkout/pay") {
      try {
        const body = await readJsonBody(req);
        const idempotencyKey = pickIdempotencyKey(req.headers, body);
        const memberIdForCheckout = req.headers["x-member-id"] || "anon";
        const wrapped = monetization.executeIdempotent({
          scope: "checkout/pay",
          member_id: memberIdForCheckout,
          idempotency_key: idempotencyKey,
          request_body: body,
          handler: () =>
            monetization.submitPayment({
              ...body,
              occurred_at_ms: body.occurred_at_ms || nowMs,
            }),
        });
        return sendJson(res, wrapped.status_code, wrapped.response);
      } catch (error) {
        const err = createErrorEnvelope("BAD_REQUEST", error.message, 400);
        return sendJson(res, err.status, err.payload);
      }
    }

    if (req.method === "POST" && url.pathname === "/checkout/confirm") {
      try {
        const body = await readJsonBody(req);
        const idempotencyKey = pickIdempotencyKey(req.headers, body);
        const memberIdForCheckout = req.headers["x-member-id"] || "anon";
        const wrapped = monetization.executeIdempotent({
          scope: "checkout/confirm",
          member_id: memberIdForCheckout,
          idempotency_key: idempotencyKey,
          request_body: body,
          handler: () => monetization.confirmOrder(body),
        });
        return sendJson(res, wrapped.status_code, wrapped.response);
      } catch (error) {
        const err = toCheckoutErrorEnvelope(error);
        return sendJson(res, err.status, err.payload);
      }
    }

    if (req.method === "POST" && url.pathname === "/claim/create") {
      const memberAuth = requireMemberHeader(req.headers);
      if (!memberAuth.ok) {
        return sendJson(
          res,
          memberAuth.error.status,
          memberAuth.error.payload
        );
      }
      try {
        const body = await readJsonBody(req);
        const idempotencyKey = pickIdempotencyKey(req.headers, body);
        const wrapped = monetization.executeIdempotent({
          scope: "claim/create",
          member_id: memberAuth.member_id,
          idempotency_key: idempotencyKey,
          request_body: body,
          handler: () =>
            monetization.createClaim({
              member_id: memberAuth.member_id,
              order_id: body.order_id,
              signature: body.signature,
            }),
        });
        return sendJson(res, wrapped.status_code, wrapped.response);
      } catch (error) {
        const err = toCheckoutErrorEnvelope(error);
        return sendJson(res, err.status, err.payload);
      }
    }

    if (req.method === "POST" && url.pathname === "/claim/submit") {
      const memberAuth = requireMemberHeader(req.headers);
      if (!memberAuth.ok) {
        return sendJson(
          res,
          memberAuth.error.status,
          memberAuth.error.payload
        );
      }
      try {
        const body = await readJsonBody(req);
        const idempotencyKey = pickIdempotencyKey(req.headers, body);
        const wrapped = monetization.executeIdempotent({
          scope: "claim/submit",
          member_id: memberAuth.member_id,
          idempotency_key: idempotencyKey,
          request_body: body,
          handler: () =>
            monetization.submitClaim({
              member_id: memberAuth.member_id,
              order_id: body.order_id,
              tx_id: body.tx_id || body.tx_hash,
              chain: body.chain,
            }),
        });
        return sendJson(res, wrapped.status_code, wrapped.response);
      } catch (error) {
        const err = toCheckoutErrorEnvelope(error);
        return sendJson(res, err.status, err.payload);
      }
    }

    const notFound = createErrorEnvelope("NOT_FOUND", "endpoint not found", 404);
    return sendJson(res, notFound.status, notFound.payload);
  });
}

if (require.main === module) {
  const port = Number(process.env.PORT || "3000");
  const server = createAppServer({
    enablePersistence: true,
    enableReconcileTimer: true,
  });
  server.listen(port, () => {
    // Keep stdout minimal for automation.
    process.stdout.write(`mdp server listening on ${port}\n`);
  });
}

module.exports = {
  createAppServer,
};
