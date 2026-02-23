# LeiMai Oracle

Historical in-sample crypto parameter research platform with multilingual SEO pages.

## Stack
- Next.js App Router + TypeScript
- API routes under `/api/v1/*`
- Middleware locale redirect (`en`, `zh-TW`, `ko`, `tr`, `vi`)
- Dynamic sitemap buckets
- Offline precompute pipeline for Top-10 coins
- Brand source-of-truth: root `logo.png`, `signature.jpg`

## Run
```bash
npm install
npm run dev
```

## Build
```bash
npm run build
```

`build` runs:
1. `prepare:brand` to generate favicon/icon assets
2. `precompute` to generate offline data artifacts in `public/precomputed`
3. `next build`

## Key routes
- `/{locale}`
- `/{locale}/{coin}/{timeframe}/best-{indicator}-settings`
- `/{locale}/atlas/{coin}`
- `/{locale}/methodology`
- `/{locale}/summaries`
- `/sitemap.xml`
- `/{locale}/sitemap/tier-1`

## API
- `/api/v1/page-data`
- `/api/v1/atlas`
- `/api/v1/methodology`
- `/api/v1/summaries`
- `/api/v1/verify`
- `/api/v1/health`

## Notes
- This product displays historical in-sample optimization only.
- Out-of-sample validation is not included in this phase.
- Not investment advice.
