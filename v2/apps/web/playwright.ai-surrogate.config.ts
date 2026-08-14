import {defineConfig} from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  testMatch: "ai-surrogate.spec.ts",
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  timeout: 180_000,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    colorScheme: "dark",
  },
});
