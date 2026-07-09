import { expect, test } from '@playwright/test'

const E2E_LOGIN_KEY = 'e2e-active-user'
const ASSESSMENT_CATEGORIES = [
  'PRODUCTION_PARTY',
  'COOPERATION',
  'FACTORY',
  'PROCESS',
  'RAW_PACKAGING',
  'COST',
  'SCHEDULE',
  'RISK',
]

async function devLogin(page: import('@playwright/test').Page, next: string): Promise<void> {
  await page.goto(`/login?next=${encodeURIComponent(next)}`)
  await page.getByPlaceholder('login_key').fill(E2E_LOGIN_KEY)
  await page.getByRole('button', { name: '开发登录' }).click()
}

async function csrfHeaders(page: import('@playwright/test').Page): Promise<Record<string, string>> {
  await page.request.get('/api/v1/auth/csrf')
  const cookies = await page.context().cookies()
  const csrf = cookies.find((cookie) => cookie.name === 'csrftoken')?.value
  return csrf ? { 'X-CSRFToken': csrf } : {}
}

async function authedJson(
  page: import('@playwright/test').Page,
  method: 'POST' | 'PATCH',
  url: string,
  data: unknown,
) {
  const headers = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    ...(await csrfHeaders(page)),
  }
  return page.request.fetch(url, { method, headers, data })
}

async function submitGateDecision(page: import('@playwright/test').Page, summary: string): Promise<void> {
  await page.locator('[data-test="decision-summary"]').fill(summary)
  await page.locator('[data-test="submit-decision"]').click()
  await expect(page.getByText('决策已记录：APPROVED')).toBeVisible()
}

test('product manager can create proposal, pass two gates, and see project on lifecycle board', async ({
  page,
}) => {
  const uniqueTitle = `E2E Yogurt ${Date.now()}`

  await devLogin(page, '/opportunities/new')
  await page.locator('[data-test="title"]').fill(uniqueTitle)
  await page.locator('[data-test="market-analysis"]').fill('Channel demand exists for protein snacks.')
  await page.locator('[data-test="core-selling-points"]').fill('High protein and low sugar.')
  await page.locator('[data-test="target-users-needs"]').fill('Breakfast replacement.')
  await page.locator('[data-test="suggested-retail-price"]').fill('9.90')
  await page.locator('[data-test="public-summary"]').fill('High protein yogurt cup')
  await page.locator('[data-test="submit-proposal"]').click()

  await expect(page.locator('[data-test="opportunity-workbench"]')).toBeVisible()
  await expect(page.locator('[data-test="proposal-status"]')).toHaveText('DRAFT')
  await page.locator('[data-test="submit-proposal"]').click()
  await expect(page.locator('[data-test="proposal-status"]')).toHaveText('SUBMITTED')

  await page.getByRole('button', { name: '开启提案评审' }).click()
  await expect(page.locator('[data-test="major-gate-decision"]')).toBeVisible()
  await submitGateDecision(page, 'Approve proposal into case.')

  const boardAfterCase = await page.request.get('/api/v1/lifecycle-board')
  expect(boardAfterCase.ok()).toBeTruthy()
  const casePayload = await boardAfterCase.json()
  const caseItem = casePayload.items.find(
    (item: { title: string; lifecycle_stage: string }) =>
      item.title === uniqueTitle && item.lifecycle_stage === 'CASE',
  )
  expect(caseItem?.candidate_public_id).toBeTruthy()
  const candidatePublicId = caseItem.candidate_public_id as string

  const meResponse = await page.request.get('/api/v1/me')
  const me = await meResponse.json()

  const leadershipResponse = await authedJson(
    page,
    'POST',
    `/api/v1/project-candidates/${candidatePublicId}/leadership`,
    {
      version_no: 1,
      case_owner_public_id: me.public_id,
    },
  )
  expect(leadershipResponse.ok()).toBeTruthy()
  const leadershipDetail = await leadershipResponse.json()
  const candidateVersionNo = leadershipDetail.version_no as number

  for (const category of ASSESSMENT_CATEGORIES) {
    const assessmentResponse = await authedJson(
      page,
      'PATCH',
      `/api/v1/project-candidates/${candidatePublicId}/assessments/${category}`,
      { status: 'CONFIRMED', conclusion: 'Ready for review.' },
    )
    expect(assessmentResponse.ok()).toBeTruthy()
  }

  const submitReviewResponse = await authedJson(
    page,
    'POST',
    `/api/v1/project-candidates/${candidatePublicId}/submit-review`,
    {
      version_no: candidateVersionNo,
      idempotency_key: `candidate-review-${Date.now()}`,
      resource_risk_summary: 'Supply risk is mitigated.',
      proposed_schedule: { launch: '2026Q4' },
    },
  )
  expect(submitReviewResponse.ok()).toBeTruthy()
  const candidateDetail = await submitReviewResponse.json()
  const projectGateId = candidateDetail.active_stage_gate_public_id
  expect(projectGateId).toBeTruthy()

  await page.goto(`/stage-gates/${projectGateId}/decide`)
  await submitGateDecision(page, 'Approve project creation.')
  await expect(page.getByText('决策已记录：APPROVED')).toBeVisible()

  await page.goto('/lifecycle-board')
  await expect(page.locator('[data-test="lifecycle-board"]')).toBeVisible()
  await expect(page.locator('[data-test="lifecycle-board-table"]')).toContainText(uniqueTitle)
  await expect(page.locator('[data-test="lifecycle-board-table"]')).toContainText('PROJECT')
})
