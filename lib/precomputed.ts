import { readFile } from "node:fs/promises";
import path from "node:path";

import { buildQueryKey, DEFAULT_QUERY } from "@/lib/catalog";
import { hydrateAtlas, hydratePageData } from "@/lib/engine";
import type { SupportedLocale } from "@/lib/i18n";
import { SUPPORTED_COINS } from "@/lib/market";
import type {
  AtlasCore,
  AtlasResult,
  Coin,
  IndicatorSetSlug,
  Lookback,
  PageDataCore,
  PageDataResult,
  PrecomputedManifest,
  Regime,
  SummariesResult,
  Timeframe
} from "@/lib/types";

type PrecomputedBundle = {
  manifest: PrecomputedManifest;
  pageDataCore: Record<string, PageDataCore>;
  atlasCore: Record<string, AtlasCore>;
};

const PRECOMPUTED_DIR = path.join(process.cwd(), "public", "precomputed");

let bundlePromise: Promise<PrecomputedBundle | null> | null = null;

async function readJson<T>(filename: string): Promise<T> {
  const absolute = path.join(PRECOMPUTED_DIR, filename);
  const raw = await readFile(absolute, "utf8");
  return JSON.parse(raw) as T;
}

async function loadBundle(): Promise<PrecomputedBundle | null> {
  try {
    const [manifest, pageDataCore, atlasCore] = await Promise.all([
      readJson<PrecomputedManifest>("manifest.json"),
      readJson<Record<string, PageDataCore>>("page-data-core.json"),
      readJson<Record<string, AtlasCore>>("atlas-core.json")
    ]);
    return { manifest, pageDataCore, atlasCore };
  } catch {
    return null;
  }
}

async function getBundle(): Promise<PrecomputedBundle | null> {
  if (!bundlePromise) {
    bundlePromise = loadBundle();
  }
  return bundlePromise;
}

function toKey(input: {
  coin: Coin;
  timeframe: Timeframe;
  lookback: Lookback;
  regime: Regime;
  indicatorSlug: IndicatorSetSlug;
}): string {
  return buildQueryKey(input);
}

export async function getPrecomputedManifest(): Promise<PrecomputedManifest | null> {
  const bundle = await getBundle();
  return bundle?.manifest ?? null;
}

export async function getPrecomputedPageData(input: {
  locale: SupportedLocale;
  coin: Coin;
  timeframe: Timeframe;
  lookback: Lookback;
  regime: Regime;
  indicatorSlug: IndicatorSetSlug;
}): Promise<PageDataResult | null> {
  const bundle = await getBundle();
  if (!bundle) {
    return null;
  }
  const core = bundle.pageDataCore[toKey(input)];
  if (!core) {
    return null;
  }
  return hydratePageData(core, input.locale, bundle.manifest.generatedAt);
}

export async function getPrecomputedAtlas(input: {
  locale: SupportedLocale;
  coin: Coin;
  timeframe: Timeframe;
  lookback: Lookback;
  regime: Regime;
  indicatorSlug: IndicatorSetSlug;
}): Promise<AtlasResult | null> {
  const bundle = await getBundle();
  if (!bundle) {
    return null;
  }
  const core = bundle.atlasCore[toKey(input)];
  if (!core) {
    return null;
  }
  return hydrateAtlas(core, input.locale, bundle.manifest.generatedAt);
}

export async function getPrecomputedSummaries(input: { locale: SupportedLocale; coin?: Coin | null }): Promise<SummariesResult | null> {
  const bundle = await getBundle();
  if (!bundle) {
    return null;
  }

  const coins = input.coin ? [input.coin] : SUPPORTED_COINS;
  const cards = coins
    .map((coin) => {
      const key = toKey({
        coin,
        timeframe: DEFAULT_QUERY.timeframe,
        lookback: DEFAULT_QUERY.lookback,
        regime: DEFAULT_QUERY.regime,
        indicatorSlug: DEFAULT_QUERY.indicatorSlug
      });
      const core = bundle.pageDataCore[key];
      if (!core) {
        return null;
      }
      return {
        key,
        title: `${core.symbol} ${core.timeframe.toUpperCase()} ${core.indicatorSet.join("+").toUpperCase()}`,
        headline_return_is: core.headlineReturnIS,
        headline_return_after_friction: core.headlineReturnAfterFriction,
        proof_id: core.proofId
      };
    })
    .filter((item): item is NonNullable<typeof item> => item !== null)
    .sort((a, b) => b.headline_return_after_friction - a.headline_return_after_friction);

  return {
    locale: input.locale,
    cards
  };
}
