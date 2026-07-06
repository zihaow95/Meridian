import { expect, test } from '@playwright/test'

// Smoke test: the served application identifies itself as Project Meridian.
// No business flows are exercised in phase 0.
test('application shell renders the Meridian identity', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Project Meridian')
})
