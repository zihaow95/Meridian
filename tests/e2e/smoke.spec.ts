import { expect, test } from '@playwright/test'

test('application shell renders the Meridian identity', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Project Meridian')
})
