# LeiMai Throne Support Site

Standalone support + leaderboard property for `support.leimaitech.com`.

## Scope

- Highest single verified `USDT (TRC20)` transfer leaderboard.
- `en / zh-tw / zh-cn` localized pages.
- Declaration submission with pre-moderation queue.
- Approved declaration ads slots.
- SEO/GEO stack: `sitemap.xml`, `robots.txt`, `llms.txt`, JSON-LD, hreflang, `/api/v1/knowledge`.
- Dual-source chain verification: `Tronscan + TronGrid`.

## Local Run

1. Create env file:

```powershell
copy support\.env.example support\.env
```

2. One-command start (server + worker):

```powershell
npm run support:run-local
```

3. Open:

- `http://localhost:4310/en`
- `http://localhost:4310/zh-tw`
- `http://localhost:4310/zh-cn`
- `http://localhost:4310/preview/` (template hub)
- `http://localhost:4310/preview/a`
- `http://localhost:4310/preview/b`
- `http://localhost:4310/preview/c`

4. One-command stop:

```powershell
npm run support:stop-local
```

## Manual Run

```powershell
node support/server.mjs
node support/worker.mjs
```

## Vercel Deployment (Serverless)

- Entry function: `api/index.mjs`
- Rewrite all routes to `api/index` via `vercel.json`
- Cron refresh endpoint: `api/internal/poll-chain.mjs`

Required env on Vercel:

- `SUPPORT_TRC20_ADDRESS`
- `SUPPORT_MIN_AMOUNT`
- `SUPPORT_MIN_CONFIRMATIONS`
- `SUPPORT_TRONSCAN_API_BASE`
- `SUPPORT_TRONGRID_API_BASE`
- `SUPPORT_TRONGRID_API_KEY` (optional)
- `CRON_SECRET`

Notes:

- If `SUPPORT_RUNTIME_DIR` is not set in Vercel, runtime state falls back to `/tmp/support-runtime`.
- `/tmp` is ephemeral; for production-grade persistence, replace JSON runtime storage with managed DB/KV.

## Admin Endpoints

Use header `x-admin-token: <SUPPORT_ADMIN_TOKEN>`.

- `GET /api/v1/admin/moderation/queue`
- `POST /api/v1/admin/declarations/:id/approve`
- `POST /api/v1/admin/declarations/:id/reject`
- `POST /api/v1/admin/blacklist`
- `POST /api/v1/admin/fetch-now`

## Runtime State

Runtime files live in `support/runtime/`:

- `chain-state.json`
- `app-state.json`
- `support-local-pids.json` (local helper)
- `logs/*` (local helper)
