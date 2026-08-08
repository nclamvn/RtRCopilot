import {defineConfig} from "@playwright/test";

export default defineConfig({
  testDir: "./tests/live",
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  timeout: 180_000,
  expect: {timeout: 150_000},
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3101",
    trace: "retain-on-failure",
    colorScheme: "dark",
  },
});
