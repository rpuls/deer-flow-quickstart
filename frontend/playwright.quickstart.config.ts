import { defineConfig, devices } from "@playwright/test";

/**
 * Full-stack onboarding suite: a real Gateway, a real Postgres, and no API
 * keys anywhere — the exact shape of a fresh one-click deployment.
 *
 * It expects the stack to already be running, because building it is slow and
 * a developer usually wants to keep it up between runs:
 *
 *   docker compose -f docker/docker-compose.quickstart.yaml up -d --build
 *   pnpm --dir frontend exec playwright test -c playwright.quickstart.config.ts
 *
 * `make quickstart-e2e` from the repository root does both.
 */
export default defineConfig({
  testDir: "./tests/e2e-quickstart",
  // The suite mutates one shared deployment (admin account, provider list), so
  // parallel workers would fight over the same state.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? "github" : "list",
  timeout: 120_000,

  use: {
    baseURL: process.env.QUICKSTART_BASE_URL ?? "http://localhost:3000",
    locale: "en-US",
    trace: "on-first-retry",
    ignoreHTTPSErrors: true,
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
