// Playwright smoke test against a RUNNING PodPoll (local/up.sh dev, or any deployed URL):
//   BASE_URL=http://localhost:8081 npx playwright test
// scripts/test-e2e.sh runs it inside the official Playwright container (no local browsers needed).
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.BASE_URL || "http://localhost:8081",
    viewport: { width: 1280, height: 900 },
    colorScheme: "dark",
  },
});
