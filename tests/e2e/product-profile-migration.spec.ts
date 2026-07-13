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

test('legacy import can confirm baseline, publish, and search product', async ({ page }) => {
  const uniqueNo = `LEG-E2E-${Date.now()}`
  const productName = `E2E Legacy Yogurt ${Date.now()}`
  const csv =
    'name,category_code,business_no,brand_code,sku_code,barcode,specification\n' +
    `${productName},YOGURT,${uniqueNo},BRAND-A,SKU-${uniqueNo},69${String(Date.now()).slice(-10)},120g\n`

  await devLogin(page, '/products/import')
  await page.locator('[data-test="import-csv"]').fill(csv)
  await page.locator('[data-test="parse-import"]').click()
  await expect(page.locator('[data-test="import-status"]')).toContainText('已解析')

  const decideButton = page.locator('[data-test="decide-create"]').first()
  if (await decideButton.isVisible()) {
    await decideButton.click()
  }

  await page.locator('[data-test="confirm-import"]').click()
  await expect(page.locator('[data-test="import-status"]')).toContainText('已确认导入')

  await page.locator('[data-test="publish-baseline"]').click()
  await expect(page.locator('[data-test="import-status"]')).toContainText('基线已发布')

  await page.goto(`/products?search=${encodeURIComponent(productName)}`)
  await expect(page.getByRole('heading', { name: '产品档案' })).toBeVisible()
  await expect(page.getByText(productName)).toBeVisible()
})
