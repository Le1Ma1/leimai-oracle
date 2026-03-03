# Token Rotation Sync Checklist

This checklist is for post-rotation rebind only. Non-token business config can remain unchanged.

## 1) Update Local Files

- `support/.env`
  - Fill only token/secret fields:
    - `SUPABASE_URL`
    - `SUPABASE_ANON_KEY`
    - `SUPABASE_SERVICE_ROLE_KEY`
    - `SUPPORT_SESSION_SECRET`
    - `CRON_SECRET`
    - `SUPPORT_ADMIN_TOKEN`
    - `SUPPORT_TRONGRID_API_KEY` (optional)
    - `ALCHEMY_API_KEY` (optional if ETH/L2 verification is needed)

- `.env` (repo root)
  - Fill only token/secret fields:
    - `GITHUB_TOKEN`
    - `VERCEL_TOKEN`
    - `CLOUDFLARE_API_TOKEN`
    - `SUPABASE_URL`
    - `SUPABASE_ANON_KEY`
    - `SUPABASE_SERVICE_ROLE_KEY`
    - `SUPPORT_TRONGRID_API_KEY`
    - `ALCHEMY_API_KEY`

## 2) GitHub Repository Settings

### Secrets

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `VERCEL_TOKEN`
- `CLOUDFLARE_API_TOKEN`
- `GITHUB_TOKEN`
- `SUPPORT_TRONGRID_API_KEY` (optional)
- `ALCHEMY_API_KEY` (optional)

### Variables

- `GITHUB_OWNER`
- `GITHUB_REPO`
- `VERCEL_PROJECT_ID`
- `VERCEL_TEAM_ID`
- `SUPPORT_BASE_URL`
- `SUPPORT_SITE_URL`
- `SUPPORT_MAIN_SITE_URL`
- `TRON_USDT_RECIPIENT`
- `ETH_L1_ERC20_RECIPIENT`
- `L2_NETWORK`
- `L2_USDC_RECIPIENT`

## 3) Re-sync Order

1. Run workflow: `vercel-env-sync`
2. Run workflow: `ingest-market-4h`
3. Run workflow: `harvest-payments-5m`

## 4) Smoke Checks

- `/api/v1/payment/create` returns `invoice_id`
- `/api/v1/payment/status?invoice_id=...` returns `pending|paid|expired`
- `vercel-env-sync` workflow finishes without env sync errors

## 5) Alchemy Extra Setup

- Enable networks used by the harvester:
  - Ethereum Mainnet
  - Arbitrum Mainnet
- Ensure API key policy does not block GitHub Actions runners.
- If ERC20/L2 rails are intended to be active, set:
  - Secret: `ALCHEMY_API_KEY`
  - Variables: `ETH_L1_ERC20_RECIPIENT`, `L2_NETWORK`, `L2_USDC_RECIPIENT`
