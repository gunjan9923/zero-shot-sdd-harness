import { defineConfig, devices } from '@playwright/test'

// Phase 1 E2E config for the Analyst Workspace.
// The app is a Python (FastAPI) stack that serves the built Next.js static
// export at /app. We launch it via `uv run python -m src` and reuse an already
// running server if one is up. Gemini answers can take ~30s, so timeouts are
// generous.
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [['list']],
  // Each test gets up to 120s — an upload + a real Gemini round-trip + sandbox
  // execution can take a while on the first cold call.
  timeout: 120_000,
  expect: {
    // Waiting for the real answer to render after Ask.
    timeout: 60_000,
  },
  use: {
    baseURL: 'http://localhost:8001/app/',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  // Launch the real Python app. The static export at frontend/out/ is already
  // built, so /app is served as soon as the server is up. reuseExistingServer
  // lets you run the server yourself and just point Playwright at it.
  webServer: {
    command: 'uv run python -m src',
    url: 'http://localhost:8001/health',
    reuseExistingServer: true,
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
})
