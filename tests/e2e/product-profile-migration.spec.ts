import { expect, test } from '@playwright/test'

const E2E_LOGIN_KEY = 'e2e-active-user'

async function devLogin(page: import('@playwright/test').Page, next: string): Promise<void> {
  await page.goto(`/login?next=${encodeURIComponent(next)}`)
  await page.getByPlaceholder('login_key').fill(E2E_LOGIN_KEY)
  await page.getByRole('button', { name: '开发登录' }).click()
}

test('product dossier list and import workbench are reachable', async ({ page }) => {
  await devLogin(page, '/products')
  await expect(page.getByRole('heading', { name: '产品档案' })).toBeVisible()
  await expect(page.getByRole('button', { name: '存量导入' })).toBeVisible()

  await page.getByRole('button', { name: '存量导入' }).click()
  await expect(page.getByRole('heading', { name: '存量产品导入' })).toBeVisible()
  await expect(page.locator('[data-test="parse-import"]')).toBeVisible()
  await expect(page.locator('[data-test="confirm-import"]')).toBeVisible()
})
