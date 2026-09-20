import { existsSync } from "node:fs";
import { defineConfig, devices } from "@playwright/test";

// Some managed sandboxes pre-install Chromium at this fixed path instead of
// the versioned cache dir @playwright/test normally manages. When it's
// present, use it directly to skip a browser download that may be blocked
// there. On a normal machine this path doesn't exist, so Playwright falls
// back to its own browser resolution (run `npx playwright install chromium`
// once if you haven't already).
const SANDBOX_CHROMIUM = "/opt/pw-browsers/chromium";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    ...(existsSync(SANDBOX_CHROMIUM)
      ? { launchOptions: { executablePath: SANDBOX_CHROMIUM } }
      : {}),
  },
  webServer: [
    {
      command:
        "apps/api/.venv/bin/uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port 8000",
      url: "http://localhost:8000/healthz",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      env: { ARIAD_DB_PATH: "./apps/api/data/e2e.db", ARIAD_AUDIO_DIR: "./apps/api/data/e2e_audio" },
    },
    {
      command: "npm run dev --prefix apps/web -- --port 3000",
      url: "http://localhost:3000",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: { NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000" },
    },
  ],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
