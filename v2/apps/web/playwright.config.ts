import {defineConfig} from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  testIgnore: "ai-surrogate.spec.ts",
  fullyParallel: true,
  reporter: "line",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    // No-cookie pages follow prefers-color-scheme; pin it to dark so the
    // default matrix stays on the shipped identity (light tests set the cookie).
    colorScheme: "dark",
  },
});
