import { expect, test } from '@playwright/test'

const E2E_LOGIN_KEY = 'e2e-active-user'
const E2E_APPROVER_LOGIN_KEY = 'e2e-approver-user'

async function devLogin(
  page: import('@playwright/test').Page,
  next: string,
  loginKey = E2E_LOGIN_KEY,
): Promise<void> {
  await page.goto(`/login?next=${encodeURIComponent(next)}`)
  await page.getByPlaceholder('login_key').fill(loginKey)
  await page.getByRole('button', { name: '开发登录' }).click()
  await page.waitForURL((url) => !url.pathname.startsWith('/login'))
}

async function importAndPublishProduct(
  page: import('@playwright/test').Page,
  productName: string,
  businessNo: string,
  barcode: string,
): Promise<void> {
  const csv =
    'name,category_code,business_no,brand_code,sku_code,barcode,specification\n' +
    `${productName},YOGURT,${businessNo},BRAND-A,SKU-${businessNo},${barcode},120g\n`

  await expect(page.getByRole('heading', { name: '存量产品导入' })).toBeVisible()
  await page.locator('[data-test="import-csv"]').fill(csv)
  await page.locator('[data-test="parse-import"]').click()
  await expect(page.locator('[data-test="import-status"]')).toContainText('已解析')

  const decideButton = page.locator('[data-test="decide-create"]').first()
  if (await decideButton.isVisible()) {
    await decideButton.click()
    await expect(page.locator('[data-test="import-status"]')).toContainText('已决定为新建')
  }

  await page.locator('[data-test="confirm-import"]').click()
  await expect(page.locator('[data-test="import-status"]')).toContainText('已确认导入')
  await expect(page.locator('[data-test="import-report"]')).toBeVisible()
  await page.locator('[data-test="publish-baseline"]').click()
  await expect(page.locator('[data-test="import-status"]')).toContainText('基线已发布')
}

test('product dossier list and import workbench are reachable', async ({ page }) => {
  await devLogin(page, '/products')
  await expect(page.getByRole('heading', { name: '产品档案' })).toBeVisible()
  await expect(page.getByRole('button', { name: '存量导入' })).toBeVisible()

  await page.getByRole('button', { name: '存量导入' }).click()
  await expect(page.getByRole('heading', { name: '存量产品导入' })).toBeVisible()
  await expect(page.locator('[data-test="parse-import"]')).toBeVisible()
  await expect(page.locator('[data-test="confirm-import"]')).toBeVisible()
  await expect(page.locator('[data-test="publish-baseline"]')).toBeVisible()
})

test('legacy import can confirm baseline, publish, and search product', async ({ page }) => {
  const uniqueNo = `LEG-E2E-${Date.now()}`
  const productName = `E2E Legacy Yogurt ${Date.now()}`
  const barcode = `69${String(Date.now()).slice(-10)}`

  await devLogin(page, '/products/import')
  await importAndPublishProduct(page, productName, uniqueNo, barcode)

  await page.goto(`/products?search=${encodeURIComponent(productName)}`)
  await expect(page.getByRole('heading', { name: '产品档案' })).toBeVisible()
  await expect(page.getByText(productName)).toBeVisible()
})

test('published product detail shows version sku channel and supports iteration workbench', async ({
  page,
}) => {
  test.setTimeout(120_000)
  const stamp = Date.now()
  const productName = `E2E Iter Yogurt ${stamp}`
  const businessNo = `ITER-${stamp}`
  const barcode = `68${String(stamp).slice(-10)}`

  await devLogin(page, '/products/import')
  await importAndPublishProduct(page, productName, businessNo, barcode)

  await page.goto(`/products?search=${encodeURIComponent(productName)}`)
  await page.getByText(productName).click()
  await expect(page.locator('[data-test="product-name"]')).toHaveText(productName)
  await expect(page.locator('[data-test="product-version"]').first()).toBeVisible()
  await expect(page.locator('[data-test="product-sku"]').first()).toBeVisible()
  await expect(page.locator('[data-test="product-channel"]').first()).toBeVisible()

  await page.locator('[data-test="start-iteration"]').click()
  await expect(page.locator('[data-test="change-set-title"]')).toBeVisible()
  await expect(page.locator('[data-test="attribute-editor"]')).toBeVisible()
  await expect(page.locator('[data-test="change-set-diff"]')).toBeVisible()

  await page
    .locator('[data-test="edit-group-values"]')
    .fill('{"core_selling_points":"Iteration protein boost"}')
  await page.locator('[data-test="save-attribute-group"]').click()
  await expect(page.locator('[data-test="change-set-status-message"]')).toContainText('属性组已保存')
  await expect(page.locator('[data-test="attribute-groups"]')).toBeVisible()

  await page.locator('[data-test="reassign-confirmer"]').first().click()
  await expect(page.locator('[data-test="change-set-status-message"]')).toContainText('已改派确认人')
  await page.locator('[data-test="approve-attribute-group"]').first().click()
  await expect(page.locator('[data-test="change-set-status-message"]')).toContainText('已确认')
  await expect(page.locator('[data-test="change-set-status"]')).toHaveText('DRAFT')

  const iterationBarcode = `67${String(stamp).slice(-10)}`
  const iterationSkuCode = `SKU-ITER-V2-${stamp}`
  await page.getByRole('textbox', { name: 'SKU 编码' }).fill(iterationSkuCode)
  await page.getByRole('textbox', { name: '条码' }).fill(iterationBarcode)
  await page.getByRole('textbox', { name: 'SKU 名称' }).fill('Iteration cup')
  await page.getByRole('textbox', { name: '规格' }).fill('150g')
  await page.locator('[data-test="save-scope"]').click()
  await expect(page.locator('[data-test="change-set-status-message"]')).toContainText('范围已更新')

  await page.locator('[data-test="submit-confirmation"]').click()
  await expect(page.locator('[data-test="change-set-status-message"]')).toContainText('已提交确认')
  await expect(page.locator('[data-test="change-set-status"]')).toHaveText('IN_CONFIRMATION')

  const changeSetPath = new URL(page.url()).pathname
  await page.context().clearCookies()
  await devLogin(page, changeSetPath, E2E_APPROVER_LOGIN_KEY)
  await expect(page.locator('[data-test="change-set-status"]')).toHaveText('IN_CONFIRMATION')
  await expect(page.getByRole('textbox', { name: 'SKU 编码' })).toHaveValue(iterationSkuCode)
  await expect(page.getByRole('textbox', { name: '条码' })).toHaveValue(iterationBarcode)
  await page.locator('[data-test="approve-change-set"]').click()
  await expect(page.locator('[data-test="change-set-status"]')).toHaveText('APPROVED')
  await expect(page.locator('[data-test="publication-ready"]')).toBeVisible({ timeout: 15000 })
  await page.locator('[data-test="publish-change-set"]').click()
  await expect(page.getByText('发布成功')).toBeVisible({ timeout: 15000 })
})

test('import duplicate candidates support link and skip decisions', async ({ page }) => {
  test.setTimeout(90_000)
  const stamp = Date.now()
  const productName = `E2E Dup Yogurt ${stamp}`
  const businessNo = `DUP-${stamp}`
  const barcode = `66${String(stamp).slice(-10)}`

  await devLogin(page, '/products/import')
  await importAndPublishProduct(page, productName, businessNo, barcode)

  const csv =
    'name,category_code,business_no,brand_code,sku_code,barcode,specification\n' +
    `${productName} Copy,YOGURT,${businessNo}-COPY,BRAND-A,SKU-${businessNo}-COPY,${barcode},120g\n` +
    `Skip Me,YOGURT,SKIP-${stamp},BRAND-A,SKU-SKIP-${stamp},65${String(stamp).slice(-10)},100g\n`

  await page.goto('/products/import')
  await expect(page.getByRole('heading', { name: '存量产品导入' })).toBeVisible()
  await page.locator('[data-test="import-csv"]').fill(csv)
  await page.locator('[data-test="parse-import"]').click()
  await expect(page.locator('[data-test="import-status"]')).toContainText('已解析')
  await expect(page.locator('[data-test="duplicate-candidates"]').first()).not.toHaveText('[]')

  await page.locator('[data-test="link-target"]').first().click()
  await page.locator('.el-select-dropdown__item').first().click()
  await page.locator('[data-test="decide-link"]').first().click()
  await expect(page.locator('[data-test="import-status"]')).toContainText('已关联既有产品')

  await page.locator('[data-test="decide-skip"]').nth(1).click()
  await expect(page.locator('[data-test="import-status"]')).toContainText('已跳过')
})
