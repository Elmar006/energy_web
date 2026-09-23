import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,
  expect: { timeout: 15_000 },
  reporter: "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.ENERGY_FRONTEND_URL ?? "http://127.0.0.1:53001",
    trace: "retain-on-failure",
  },
});
