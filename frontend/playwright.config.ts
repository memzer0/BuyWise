import { defineConfig } from "@playwright/test";

// End-to-end tests run the real backend with a test-only provider (backend/tests/e2e_server.py)
// on port 8001 and the frontend dev server on port 5174, so they never touch real retailer APIs.
const py = process.platform === "win32" ? ".venv\\Scripts\\python" : ".venv/bin/python";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: { baseURL: "http://127.0.0.1:5174" },
  webServer: [
    { command: `${py} -m tests.e2e_server`, cwd: "../backend", url: "http://127.0.0.1:8001/api/health", reuseExistingServer: false },
    {
      command: "npx vite --port 5174 --strictPort",
      url: "http://127.0.0.1:5174",
      env: { VITE_API_BASE_URL: "http://127.0.0.1:8001" },
      reuseExistingServer: false,
    },
  ],
});
