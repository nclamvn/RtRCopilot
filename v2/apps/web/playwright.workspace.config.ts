import {defineConfig} from "@playwright/test";
export default defineConfig({
  testDir: "./tests/workspace", fullyParallel: false, workers: 1, reporter: "line",
  outputDir: "test-results/workspace", timeout: 45_000,
  use: {baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3110", extraHTTPHeaders: {origin: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3110"}, trace: "retain-on-failure", colorScheme: "light", acceptDownloads: true},
  // Root launches the real API and standard .next dev server. No per-task build directory.
});
