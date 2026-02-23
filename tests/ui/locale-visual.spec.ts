import { expect, test } from "@playwright/test";

const LOCALES = ["en", "zh-TW", "zh-CN"] as const;

const ROUTES = [
  { name: "home", path: "" },
  { name: "methodology", path: "/methodology" },
  { name: "summaries", path: "/summaries" },
  { name: "atlas", path: "/atlas/btc?tf=1h&lookback=90d&regime=all&indicator=macd-rsi" },
  { name: "detail", path: "/btc/1h/best-macd-rsi-settings?lookback=90d&regime=all" }
] as const;

function normalizeDynamicText(raw: string): string {
  return raw
    .replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z/g, "<ISO_TS>")
    .replace(/[a-f0-9]{24}/gi, "<PROOF_ID>")
    .replace(/-?\d+(?:\.\d+)?%/g, "<PERCENT>")
    .replace(/v=\d+/g, "v=<NUM>");
}

test.describe("locale visual snapshots", () => {
  for (const locale of LOCALES) {
    for (const route of ROUTES) {
      test(`${locale} ${route.name}`, async ({ page }) => {
        const target = `/${locale}${route.path}`;
        await page.goto(target, { waitUntil: "networkidle" });

        await page.evaluate(() => {
          const normalize = (value: string) =>
            value
              .replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z/g, "<ISO_TS>")
              .replace(/[a-f0-9]{24}/gi, "<PROOF_ID>")
              .replace(/-?\d+(?:\.\d+)?%/g, "<PERCENT>")
              .replace(/v=\d+/g, "v=<NUM>");
          for (const node of document.querySelectorAll(".mono, .muted")) {
            if (node.textContent) {
              node.textContent = normalize(node.textContent);
            }
          }
        });

        const html = await page.content();
        const normalized = normalizeDynamicText(html);
        expect(normalized).not.toContain("{{");

        await expect(page).toHaveScreenshot(`${locale}-${route.name}.png`, {
          fullPage: true
        });
      });
    }
  }
});
