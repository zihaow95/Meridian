/**
 * Phase 6 E2E: legacy products, in-app notifications, pilot auth, feedback loop.
 *
 * Requires `seed_phase6_acceptance` (includes seed_e2e_user).
 */
import { expect, test, type Page } from '@playwright/test'

const E2E_LOGIN_KEY = 'e2e-active-user'
const E2E_LIMITED_LOGIN_KEY = 'e2e-limited-user'
const ORG_PUBLIC_ID = '6a6a6a6a-6b6b-6c6c-6d6d-6e6e6e6e6e6e'
const PILOT_EMPLOYEE_NO = 'P-E2E-001'
const PILOT_INACTIVE_NO = 'P-E2E-INACTIVE'
const PILOT_PASSWORD = 'phase6-pilot-secret'
const PHASE6_BATCH_NAME = 'Phase6 Internal Acceptance'

async function csrfHeaders(page: Page): Promise<Record<string, string>> {
  await page.request.get('/api/v1/auth/csrf')
  const cookies = await page.context().cookies()
  const csrf = cookies.find((cookie) => cookie.name === 'csrftoken')?.value
  return csrf ? { 'X-CSRFToken': csrf } : {}
}

async function authedJson(
  page: Page,
  method: 'POST' | 'PATCH' | 'GET',
  url: string,
  data?: unknown,
) {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(await csrfHeaders(page)),
  }
  if (data !== undefined) {
    headers['Content-Type'] = 'application/json'
  }
  return page.request.fetch(url, {
    method,
    headers,
    data: data === undefined ? undefined : data,
  })
}

async function devLogin(page: Page, next: string, loginKey = E2E_LOGIN_KEY): Promise<void> {
  await page.goto(`/login?next=${encodeURIComponent(next)}`)
  await page.getByPlaceholder('login_key').fill(loginKey)
  await page.getByRole('button', { name: '开发登录' }).click()
  await page.waitForURL((url) => !url.pathname.startsWith('/login'))
}

async function reloginAs(page: Page, loginKey: string, next = '/todos'): Promise<void> {
  await page.context().clearCookies()
  await devLogin(page, next, loginKey)
}

test.describe('Phase 6 controlled files / notifications / pilot readiness', () => {
  test('legacy baseline create is idempotent and publishable', async ({ page }) => {
    await devLogin(page, '/products')
    const idem = `e2e-p6-legacy-${Date.now()}`
    const payload = {
      name: 'E2E Phase6 酸奶',
      category_code: 'YOGURT',
      brand_code: 'MERIDIAN',
      business_no: `E2E-P6-${Date.now()}`,
      specification: '180g',
      sku_code: `SKU-E2E-P6-${Date.now()}`,
      barcode: `692${String(Date.now()).slice(-10)}`,
    }

    const first = await authedJson(page, 'POST', '/api/v1/legacy-baselines', {
      idempotency_key: idem,
      payload,
    })
    expect(first.status()).toBe(201)
    const firstBody = await first.json()
    expect(firstBody.created).toBe(true)

    const replay = await authedJson(page, 'POST', '/api/v1/legacy-baselines', {
      idempotency_key: idem,
      payload,
    })
    expect([200, 201]).toContain(replay.status())
    const replayBody = await replay.json()
    expect(replayBody.change_set_public_id).toBe(firstBody.change_set_public_id)
    expect(replayBody.created).toBe(false)

    const published = await authedJson(
      page,
      'POST',
      `/api/v1/legacy-baselines/${firstBody.change_set_public_id}/publish`,
      { idempotency_key: `${idem}-publish` },
    )
    expect(published.status()).toBe(200)
    const publishedBody = await published.json()
    expect(publishedBody.product_public_id).toBeTruthy()

    const republish = await authedJson(
      page,
      'POST',
      `/api/v1/legacy-baselines/${firstBody.change_set_public_id}/publish`,
      { idempotency_key: `${idem}-publish` },
    )
    expect(republish.status()).toBe(200)
    expect((await republish.json()).product_version_public_id).toBe(
      publishedBody.product_version_public_id,
    )
  })

  test('six notification categories, read/close, and deep-link allowlist', async ({ page }) => {
    await devLogin(page, '/notifications')
    await expect(page.getByRole('heading', { name: '站内通知' })).toBeVisible()

    const list = await authedJson(page, 'GET', '/api/v1/notifications/my?page_size=50')
    expect(list.status()).toBe(200)
    const body = await list.json()
    expect(body.unread_count).toBeGreaterThanOrEqual(1)
    const categories = new Set(
      body.items.map((row: { category: string }) => row.category).filter(Boolean),
    )
    for (const category of [
      'ACTION_REQUIRED',
      'DEADLINE',
      'BUSINESS_ALERT',
      'PROCESS_RESULT',
      'SYSTEM_FAILURE',
      'INFORMATION',
    ]) {
      expect(categories.has(category)).toBe(true)
    }
    // Response stays summary-only (no object body).
    expect(body.items[0]).not.toHaveProperty('object_id')
    expect(body.items[0]).toHaveProperty('summary')

    const target = body.items.find((row: { status: string }) => row.status === 'UNREAD')
    expect(target?.public_id).toBeTruthy()
    const read = await authedJson(
      page,
      'POST',
      `/api/v1/notifications/${target.public_id}/read`,
      {},
    )
    expect(read.status()).toBe(200)
    expect((await read.json()).status).toBe('READ')

    const closed = await authedJson(
      page,
      'POST',
      `/api/v1/notifications/${target.public_id}/close`,
      { close_reason: 'E2E_CLOSED' },
    )
    expect(closed.status()).toBe(200)
    expect((await closed.json()).status).toBe('CLOSED')

    // Limited user must not see the active user's notification rows.
    await reloginAs(page, E2E_LIMITED_LOGIN_KEY, '/notifications')
    const limited = await authedJson(page, 'GET', '/api/v1/notifications/my')
    // Either no permission (404) or empty list — never the seeded phase6 rows.
    if (limited.status() === 200) {
      const limitedBody = await limited.json()
      expect(
        limitedBody.items.every(
          (row: { summary: string }) => !String(row.summary).includes('[ACTION_REQUIRED]'),
        ),
      ).toBeTruthy()
    } else {
      expect(limited.status()).toBe(404)
    }
  })

  test('pilot password login success, wrong password, inactive user, non-prod label', async ({
    page,
  }) => {
    const capsWait = page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/auth/capabilities') && response.ok(),
    )
    await page.goto('/login')
    await capsWait
    const caps = await page.request.get('/api/v1/auth/capabilities')
    expect(caps.status()).toBe(200)
    expect((await caps.json()).pilot_password_login).toBe(true)
    await expect(page.locator('[data-test="pilot-login"]')).toBeVisible()
    await expect(page.locator('[data-test="pilot-login"]')).toContainText('非生产')

    const bad = await page.request.fetch('/api/v1/auth/pilot/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(await csrfHeaders(page)),
      },
      data: {
        organization_public_id: ORG_PUBLIC_ID,
        employee_no: PILOT_EMPLOYEE_NO,
        password: 'wrong-password',
      },
    })
    expect(bad.status()).toBe(401)

    const inactive = await page.request.fetch('/api/v1/auth/pilot/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(await csrfHeaders(page)),
      },
      data: {
        organization_public_id: ORG_PUBLIC_ID,
        employee_no: PILOT_INACTIVE_NO,
        password: PILOT_PASSWORD,
      },
    })
    expect([401, 403]).toContain(inactive.status())

    await page.locator('[data-test="pilot-org"]').fill(ORG_PUBLIC_ID)
    await page.locator('[data-test="pilot-employee-no"]').fill(PILOT_EMPLOYEE_NO)
    await page.locator('[data-test="pilot-password"]').fill(PILOT_PASSWORD)
    await page.locator('[data-test="pilot-submit"]').click()
    await page.waitForURL((url) => !url.pathname.startsWith('/login'))
    const me = await page.request.get('/api/v1/me')
    expect(me.status()).toBe(200)
    expect((await me.json()).display_name).toContain('Pilot')
  })

  test('feedback create → assign → handle → retest → close', async ({ page }) => {
    await devLogin(page, '/pilot/batches')
    await expect(page.locator('[data-test="pilot-batch-view"]')).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('[data-test="pilot-batch-view"]')).toContainText('非生产')

    const batches = await authedJson(page, 'GET', '/api/v1/pilot/batches')
    expect(batches.status()).toBe(200)
    const batch = (await batches.json()).items.find(
      (row: { name: string }) => row.name === PHASE6_BATCH_NAME,
    )
    expect(batch?.public_id).toBeTruthy()

    const externalKey = `e2e-feedback-${Date.now()}`
    const opened = await authedJson(
      page,
      'POST',
      `/api/v1/pilot/batches/${batch.public_id}/feedback`,
      {
        title: 'E2E feedback',
        reproduction_summary: 'Open pilot page and click create',
        external_key: externalKey,
      },
    )
    expect(opened.status()).toBe(201)
    const feedback = await opened.json()

    const replay = await authedJson(
      page,
      'POST',
      `/api/v1/pilot/batches/${batch.public_id}/feedback`,
      {
        title: 'E2E feedback replay',
        reproduction_summary: 'should not create a second row',
        external_key: externalKey,
      },
    )
    expect(replay.status()).toBe(201)
    expect((await replay.json()).public_id).toBe(feedback.public_id)

    const me = await (await page.request.get('/api/v1/me')).json()
    let current = feedback
    const assign = await authedJson(page, 'POST', `/api/v1/pilot/feedback/${current.public_id}/assign`, {
      severity: 'P1',
      assignee_public_id: me.public_id,
      expected_version: current.version_no,
    })
    expect(assign.status()).toBe(200)
    current = await assign.json()

    const handle = await authedJson(page, 'POST', `/api/v1/pilot/feedback/${current.public_id}/handle`, {
      expected_version: current.version_no,
    })
    expect(handle.status()).toBe(200)
    current = await handle.json()

    const submit = await authedJson(
      page,
      'POST',
      `/api/v1/pilot/feedback/${current.public_id}/submit-retest`,
      { target_version: '0.6.9', expected_version: current.version_no },
    )
    expect(submit.status()).toBe(200)
    current = await submit.json()

    const retest = await authedJson(page, 'POST', `/api/v1/pilot/feedback/${current.public_id}/retest`, {
      passed: true,
      expected_version: current.version_no,
    })
    expect(retest.status()).toBe(200)
    current = await retest.json()

    const close = await authedJson(page, 'POST', `/api/v1/pilot/feedback/${current.public_id}/close`, {
      expected_version: current.version_no,
    })
    expect(close.status()).toBe(200)
    expect((await close.json()).status).toBe('CLOSED')
  })
})
