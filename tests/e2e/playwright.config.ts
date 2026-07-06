import { defineConfig, devices } from '@playwright/test'

// Phase 0 smoke only: verifies the built frontend serves the application shell.
// The config starts the Vite preview server serving the production build, so
// `npm run build` must have produced frontend/dist beforehand.
// Vite preview binds to `localhost`, so the readiness probe and baseURL must
// use `localhost` (not 127.0.0.1) to match on hosts where localhost is IPv6.
const PORT = Number(process.env.E2E_PORT ?? 4173)
const BASE_URL = process.env.E2E_BASE_URL ?? `http://localhost:${PORT}`

export default defineConfig({
  testDir: './',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'line' : 'list',
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: `npm --prefix ../../frontend run preview -- --port ${PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
