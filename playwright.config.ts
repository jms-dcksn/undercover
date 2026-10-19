import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  outputDir: "e2e/test-results",
  reporter: "list",
  workers: 1,
  use: { baseURL: "http://localhost:5174" },
  webServer: [
    {
      command: "uv run -m e2e.server",
      url: "http://127.0.0.1:8010/api/health",
      reuseExistingServer: false,
    },
    {
      command: "npx vite dashboard --port 5174 --strictPort",
      url: "http://localhost:5174",
      env: { VITE_API_PROXY: "http://127.0.0.1:8010" },
      reuseExistingServer: false,
    },
  ],
});
