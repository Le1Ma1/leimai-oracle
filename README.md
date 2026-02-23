# Project Panopticon

Day-1 i18n crypto in-sample optimization SEO engine.

## Stack
- Next.js App Router + TypeScript
- API routes under `/api/v1/*`
- Middleware locale redirect (`en`, `zh-TW`, `ko`, `tr`, `vi`)
- Dynamic sitemap buckets
- Brand source-of-truth: root `logo.png`, `signature.jpg`

## Run
```bash
npm install
npm run dev
```

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
- `/api/v1/health`

## Notes
- This MVP is in-sample only and friction-adjusted.
- No payment/member flow included.
