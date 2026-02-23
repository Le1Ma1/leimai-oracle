import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3000";

export default defineConfig({
  testDir: "./tests/ui",
  fullyParallel: false,
  timeout: 45_000,
  expect: {
    toHaveScreenshot: {
      maxDiffPixelRatio: 0.01
    }
  },
  use: {
    baseURL,
    trace: "on-first-retry"
  },
  projects: [
    {
      name: "chromium-desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 }
      }
    },
    {
      name: "chromium-mobile",
      use: {
        ...devices["Pixel 7"],
        browserName: "chromium"
      }
    }
  ],
  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: "npx next dev -p 3000",
        url: `${baseURL}/en`,
        reuseExistingServer: !process.env.CI,
        timeout: 180_000,
        env: {
          NEXT_TELEMETRY_DISABLED: "1"
        }
      }
});
