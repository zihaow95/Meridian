/**
 * Phase 6 E2E: legacy materials, real notification projection, pilot auth, feedback.
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

async function uploadControlledLabel(page: Page, filename: string): Promise<string> {
  const headers = await csrfHeaders(page)
  const buffer = Buffer.from(`%PDF-1.4 phase6-e2e-${filename}-${Date.now()}`)
  const upload = await page.request.post('/api/v1/documents/uploads', {
    headers,
    multipart: {
      file: {
        name: filename,
        mimeType: 'application/pdf',
        buffer,
      },
      original_filename: filename,
      declared_mime_type: 'application/pdf',
      catalog_item_code: 'PRODUCT_LABEL',
    },
  })
  expect(upload.status()).toBe(201)
  const session = await upload.json()

  const complete = await authedJson(
    page,
    'POST',
    `/api/v1/documents/uploads/${session.public_id}/complete`,
    {
      document_code: `E2E-P6-${Date.now()}`,
      title: 'E2E Phase6 Label',
    },
  )
  expect(complete.ok()).toBeTruthy()
  const body = await complete.json()
  expect(body.status).toBe('CONTROLLED')
  return body.version_public_id as string
}

test.describe('Phase 6 controlled files / notifications / pilot readiness', () => {
  test('legacy material chain, confirmation, and missing-material publish reject', async ({
    page,
  }) => {
    await devLogin(page, '/products')
    const stamp = Date.now()
    const idem = `e2e-p6-legacy-${stamp}`
    const payload = {
      name: 'E2E Phase6 酸奶',
      category_code: 'YOGURT',
      brand_code: 'MERIDIAN',
      business_no: `E2E-P6-${stamp}`,
      specification: '180g',
      sku_code: `SKU-E2E-P6-${stamp}`,
      barcode: `692${String(stamp).slice(-10)}`,
    }

    const first = await authedJson(page, 'POST', '/api/v1/legacy-baselines', {
      idempotency_key: idem,
      payload,
    })
    expect(first.status()).toBe(201)
    const firstBody = await first.json()
    expect(firstBody.created).toBe(true)
    const productPublicId = firstBody.product_public_id as string
    const changeSetPublicId = firstBody.change_set_public_id as string

    const replay = await authedJson(page, 'POST', '/api/v1/legacy-baselines', {
      idempotency_key: idem,
      payload,
    })
    expect([200, 201]).toContain(replay.status())
    expect((await replay.json()).change_set_public_id).toBe(changeSetPublicId)

    const blocked = await authedJson(
      page,
      'POST',
      `/api/v1/legacy-baselines/${changeSetPublicId}/publish`,
      { idempotency_key: `${idem}-publish-blocked` },
    )
    expect(blocked.status()).toBe(400)
    const blockedBody = await blocked.json()
    const blocks = blockedBody.details?.blocks ?? []
    expect(
      blocks.some((code: string) =>
        ['PRODUCT_MATERIAL_INCOMPLETE', 'PRODUCT_MATERIAL_NOT_CONFIRMED'].includes(code),
      ),
    ).toBeTruthy()

    const versionPublicId = await uploadControlledLabel(page, `label-${stamp}.pdf`)
    const submission = await authedJson(
      page,
      'POST',
      `/api/v1/products/${productPublicId}/legacy-material-submissions`,
      {
        document_version_public_id: versionPublicId,
        idempotency_key: `e2e-sub-${stamp}`,
        source_note: 'E2E historical label',
        claimed_version: 'V1',
      },
    )
    expect(submission.status()).toBe(201)
    const submissionBody = await submission.json()

    const verified = await authedJson(
      page,
      'POST',
      `/api/v1/legacy-materials/${submissionBody.public_id}/verify`,
      { decision: 'VERIFIED', note: 'E2E verified' },
    )
    expect(verified.status()).toBe(200)

    const chain = await authedJson(
      page,
      'POST',
      `/api/v1/products/${productPublicId}/material-chains`,
      {
        material_type_code: 'PRODUCT_LABEL',
        ordered_submission_ids: [submissionBody.public_id],
        current_submission_id: submissionBody.public_id,
      },
    )
    expect(chain.status()).toBe(201)
    const material = (await chain.json()).items[0]
    expect(material.sensitivity_level).toBeTruthy()

    const me = await (await page.request.get('/api/v1/me')).json()
    const confirmation = await authedJson(
      page,
      'POST',
      `/api/v1/product-materials/${material.public_id}/confirmations`,
      { confirmer_public_id: me.public_id, comment: 'E2E confirm' },
    )
    expect(confirmation.status()).toBe(201)
    const confirmationBody = await confirmation.json()

    // on_commit local dispatch must have projected todo + in-app notification.
    // Todos list is a bare array (not { items }).
    await expect
      .poll(async () => {
        const todos = await authedJson(page, 'GET', '/api/v1/todos/my')
        if (todos.status() !== 200) return false
        const items = (await todos.json()) as Array<{ title: string; status: string }>
        return items.some(
          (row) => row.status === 'OPEN' && String(row.title).includes('Confirm material'),
        )
      })
      .toBeTruthy()

    const notifications = await authedJson(
      page,
      'GET',
      '/api/v1/notifications/my?page_size=50',
    )
    expect(notifications.status()).toBe(200)
    const notifyBody = await notifications.json()
    const confirmNotice = notifyBody.items.find(
      (row: { summary: string; category: string; status: string }) =>
        row.category === 'ACTION_REQUIRED' &&
        row.status !== 'CLOSED' &&
        String(row.summary).includes('Confirm material'),
    )
    expect(confirmNotice?.public_id).toBeTruthy()

    const decided = await authedJson(
      page,
      'POST',
      `/api/v1/material-confirmations/${confirmationBody.public_id}/decide`,
      { decision: 'APPROVED', comment: 'E2E approved' },
    )
    expect(decided.status()).toBe(200)

    const confirmToken = String(confirmationBody.public_id)
    await expect
      .poll(async () => {
        const todosAfter = await authedJson(page, 'GET', '/api/v1/todos/my')
        if (todosAfter.status() !== 200) return false
        const items = (await todosAfter.json()) as Array<{
          title: string
          status: string
          deep_link: string
        }>
        const linked = items.filter((row) => String(row.deep_link).includes(confirmToken))
        return linked.length > 0 && linked.every((row) => row.status !== 'OPEN')
      })
      .toBeTruthy()

    await expect
      .poll(async () => {
        const noticeAfter = await authedJson(
          page,
          'GET',
          `/api/v1/notifications/my?page_size=50`,
        )
        if (noticeAfter.status() !== 200) return false
        const closedNotice = (await noticeAfter.json()).items.find(
          (row: { public_id: string }) => row.public_id === confirmNotice.public_id,
        )
        return closedNotice?.status === 'CLOSED'
      })
      .toBeTruthy()

    const published = await authedJson(
      page,
      'POST',
      `/api/v1/legacy-baselines/${changeSetPublicId}/publish`,
      { idempotency_key: `${idem}-publish` },
    )
    expect(published.status()).toBe(200)
    expect((await published.json()).product_public_id).toBeTruthy()
  })

  test('business-event notification read/close, todo sync, and deep-link deny', async ({
    page,
  }) => {
    await devLogin(page, '/notifications')
    await expect(page.getByRole('heading', { name: '站内通知' })).toBeVisible()

    // Seeded category fixtures are UNREAD; do not rely on a mixed page that can
    // bury older open rows under newer confirmation traffic from prior tests.
    const list = await authedJson(
      page,
      'GET',
      '/api/v1/notifications/my?status=UNREAD&page_size=50',
    )
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
    expect(body.items[0]).not.toHaveProperty('object_id')
    expect(body.items[0]).toHaveProperty('summary')

    const levels = new Set(
      body.items.map((row: { level: string }) => row.level).filter(Boolean),
    )
    expect(levels.has('URGENT')).toBe(true)
    expect(levels.has('IMPORTANT')).toBe(true)
    expect(levels.has('NORMAL')).toBe(true)

    const actionRequired = body.items.find(
      (row: { category: string; deep_link: string }) =>
        row.category === 'ACTION_REQUIRED' && String(row.deep_link).startsWith('/products/'),
    )
    expect(actionRequired?.deep_link).toBeTruthy()
    const productDeepLink = actionRequired.deep_link as string

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

    // Limited user hits the same real product deep link the notification pointed at.
    const productPublicId = productDeepLink.startsWith('/products/')
      ? productDeepLink.split('/')[2]
      : ''
    expect(productPublicId).toBeTruthy()
    await reloginAs(page, E2E_LIMITED_LOGIN_KEY, productDeepLink)
    const detailResponse = await page.request.get(`/api/v1/products/${productPublicId}`)
    // Existence-hiding: denied reads share the same 404 surface as missing ids.
    expect(detailResponse.status()).toBe(404)
    await expect(page.getByText('无权访问或内容不存在')).toBeVisible({ timeout: 15_000 })

    const limited = await authedJson(page, 'GET', '/api/v1/notifications/my')
    if (limited.status() === 200) {
      const limitedBody = await limited.json()
      expect(
        limitedBody.items.every(
          (row: { summary: string }) => !String(row.summary).includes('[ACTION_REQUIRED]'),
        ),
      ).toBeTruthy()
    } else {
      expect([403, 404]).toContain(limited.status())
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
    const capsBody = await caps.json()
    expect(capsBody.pilot_password_login).toBe(true)
    // E2E keeps DEV login; LAN pilot scripts force this false.
    expect(capsBody).toHaveProperty('dev_login')

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
