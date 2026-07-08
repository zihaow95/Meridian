import { expect, test } from '@playwright/test'

const E2E_LOGIN_KEY = 'e2e-active-user'

test('unauthenticated user is redirected to login when opening todos', async ({ page }) => {
  await page.goto('/todos')
  await expect(page.locator('.login__title')).toHaveText('登录')
  await expect(page.getByRole('button', { name: '钉钉登录' })).toBeVisible()
})

test('dev login succeeds and todos page loads backend data', async ({ page }) => {
  await page.goto('/login?next=/todos')
  await page.getByPlaceholder('login_key').fill(E2E_LOGIN_KEY)
  await page.getByRole('button', { name: '开发登录' }).click()
  await expect(page.getByRole('heading', { name: '我的待办' })).toBeVisible()
  await expect(page.getByText('E2E Todo')).toBeVisible()
})

test('configurations page shows list or empty state after login', async ({ page }) => {
  await page.goto('/login?next=/admin/configurations')
  await page.getByPlaceholder('login_key').fill(E2E_LOGIN_KEY)
  await page.getByRole('button', { name: '开发登录' }).click()
  await expect(page.getByRole('heading', { name: '配置发布管理' })).toBeVisible()
  const hasTable = await page.locator('.el-table').count()
  const hasEmpty = await page.getByText('暂无配置定义').count()
  expect(hasTable + hasEmpty).toBeGreaterThan(0)
})

test('protected document deep link shows access denied without leaking secrets', async ({
  page,
}) => {
  await page.goto('/login?next=/documents/secret-id')
  await page.getByPlaceholder('login_key').fill(E2E_LOGIN_KEY)
  await page.getByRole('button', { name: '开发登录' }).click()
  await expect(page.getByText('无权访问或内容不存在')).toBeVisible()
  await expect(page.getByText('secret-id')).toHaveCount(0)
})
