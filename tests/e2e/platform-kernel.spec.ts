import { expect, test } from '@playwright/test'

test('platform kernel UI: redirects to login and shows dev login hint', async ({ page }) => {
  await page.goto('/todos')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Project Meridian')
  await expect(page.getByText('开发登录（仅 DEV/TEST）')).toBeVisible()
})

