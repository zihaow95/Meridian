import { defineConfig, devices } from '@playwright/test'

const PORT = Number(process.env.E2E_PORT ?? 5173)
const BASE_URL = process.env.E2E_BASE_URL ?? `http://localhost:${PORT}`
const BACKEND_URL = process.env.E2E_BACKEND_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  testDir: './',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  // Retries are disabled so a first-run failure cannot be masked by a re-run
  // that skips the core path (e.g. a project already advanced to OPERATING).
  retries: 0,
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
  webServer: [
    {
      command:
        'uv run python manage.py migrate --settings=config.settings.test && uv run python manage.py seed_e2e_user --settings=config.settings.test && uv run python manage.py runserver 127.0.0.1:8000 --settings=config.settings.test',
      cwd: '../../backend',
      url: `${BACKEND_URL}/api/v1/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
    {
      command: `npm --prefix ../../frontend run dev -- --port ${PORT} --host localhost --strictPort`,
      url: BASE_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: {
        ...process.env,
        VITE_ENABLE_DEV_LOGIN: 'true',
      },
    },
  ],
})
