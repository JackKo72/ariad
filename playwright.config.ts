import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    // Use the browser pre-installed in this environment instead of the
    // revision @playwright/test would otherwise try to download.
    launchOptions: { executablePath: "/opt/pw-browsers/chromium" },
  },
  webServer: [
    {
      command:
        "apps/api/.venv/bin/uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port 8000",
      url: "http://localhost:8000/healthz",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      env: { ARIAD_DB_PATH: "./apps/api/data/e2e.db" },
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
