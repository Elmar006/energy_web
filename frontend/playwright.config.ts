import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,
  expect: { timeout: 15_000 },
  reporter: "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.ENERGY_FRONTEND_URL ?? "http://127.0.0.1:53001",
    launchOptions: process.env.ENERGY_CHROME_PATH
      ? { executablePath: process.env.ENERGY_CHROME_PATH }
      : undefined,
    trace: "retain-on-failure",
  },
});
