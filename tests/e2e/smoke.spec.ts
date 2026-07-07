import { expect, test } from '@playwright/test'

// Smoke test: the served application identifies itself as Project Meridian.
// No business flows are exercised in phase 0.
test('application shell renders the Meridian identity', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Project Meridian')
})

test('unauthenticated user is redirected to login when opening todos', async ({ page }) => {
  await page.goto('/todos')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Project Meridian')
  await expect(page.getByText('开发登录（仅 DEV/TEST）')).toBeVisible()
})
