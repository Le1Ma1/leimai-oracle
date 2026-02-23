import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { buildQueryKey, getPrecomputeSpace } from "../lib/catalog";
import { buildAtlasCoreFromCandles, buildPageDataCoreFromCandles } from "../lib/engine";
import { SUPPORTED_LOCALES } from "../lib/i18n";
import { fetchCandles, normalizeSymbol } from "../lib/market";
import type { AtlasCore, PageDataCore, PrecomputedManifest } from "../lib/types";

const OUTPUT_DIR = path.join(process.cwd(), "public", "precomputed");

function writeJson(filename: string, value: unknown) {
  writeFileSync(path.join(OUTPUT_DIR, filename), JSON.stringify(value));
}

async function run() {
  mkdirSync(OUTPUT_DIR, { recursive: true });

  const pageDataCore: Record<string, PageDataCore> = {};
  const atlasCore: Record<string, AtlasCore> = {};

  const failures: string[] = [];
  let marketSlices = 0;
  let processedCombos = 0;

  const space = getPrecomputeSpace();
  const totalMarketSlices = space.coins.length * space.timeframes.length * space.lookbacks.length;
  const totalCombos =
    space.coins.length *
    space.timeframes.length *
    space.lookbacks.length *
    space.regimes.length *
    space.indicatorSets.length;

  for (const coin of space.coins) {
    for (const timeframe of space.timeframes) {
      for (const lookback of space.lookbacks) {
        const marketLabel = `${coin}-${timeframe}-${lookback}`;
        try {
          const candles = await fetchCandles({
            symbol: normalizeSymbol(coin),
            timeframe,
            lookback
          });
          marketSlices += 1;

          for (const regime of space.regimes) {
            for (const indicatorSlug of space.indicatorSets) {
              const key = buildQueryKey({
                coin,
                timeframe,
                lookback,
                regime,
                indicatorSlug
              });
              try {
                pageDataCore[key] = buildPageDataCoreFromCandles({
                  coin,
                  timeframe,
                  lookback,
                  regime,
                  indicatorSlug,
                  candles
                });
                atlasCore[key] = buildAtlasCoreFromCandles({
                  coin,
                  timeframe,
                  lookback,
                  regime,
                  indicatorSlug,
                  candles
                });
              } catch (error) {
                failures.push(`${key}: ${error instanceof Error ? error.message : "unknown error"}`);
              }
              processedCombos += 1;
            }
          }
          console.log(`[precompute] ${marketLabel} done (${marketSlices}/${totalMarketSlices})`);
        } catch (error) {
          failures.push(`${marketLabel}: ${error instanceof Error ? error.message : "unknown error"}`);
          console.warn(`[precompute] ${marketLabel} failed`);
        }
      }
    }
  }

  if (!Object.keys(pageDataCore).length) {
    throw new Error("No precomputed rows were generated.");
  }

  const generatedAt = new Date().toISOString();
  const manifest: PrecomputedManifest = {
    brand: "LeiMai Oracle",
    version: 1,
    generatedAt,
    source: "binance_api",
    locales: [...SUPPORTED_LOCALES],
    dimensions: {
      coins: [...space.coins],
      timeframes: [...space.timeframes],
      lookbacks: [...space.lookbacks],
      regimes: [...space.regimes],
      indicatorSets: [...space.indicatorSets]
    },
    coverage: {
      marketSlices,
      pageDataCombos: Object.keys(pageDataCore).length,
      atlasCombos: Object.keys(atlasCore).length,
      summariesCoins: space.coins.length
    }
  };

  writeJson("manifest.json", manifest);
  writeJson("page-data-core.json", pageDataCore);
  writeJson("atlas-core.json", atlasCore);

  console.log(
    `[precompute] completed combos=${Object.keys(pageDataCore).length}/${totalCombos}, failures=${failures.length}, processed=${processedCombos}`
  );
  if (failures.length) {
    writeFileSync(path.join(OUTPUT_DIR, "failures.log"), failures.join("\n"));
    console.warn(`[precompute] wrote failures.log with ${failures.length} entries`);
  }
}

run().catch((error) => {
  console.error("[precompute] fatal", error);
  process.exitCode = 1;
});

