import { expect, test } from "@playwright/test";

const E2E_LOGIN_KEY = "e2e-active-user";
const E2E_APPROVER_LOGIN_KEY = "e2e-approver-user";
const E2E_LIMITED_LOGIN_KEY = "e2e-limited-user";
const E2E_LAUNCH_BUSINESS_NO = "E2E-LAUNCH";
const E2E_REPAIR_BUSINESS_NO = "E2E-REPAIR";
const E2E_REPAIR_RETRY_BUSINESS_NO = "E2E-REPAIR-RETRY";

const ASSESSMENT_CATEGORIES = [
  "PRODUCTION_PARTY",
  "COOPERATION",
  "FACTORY",
  "PROCESS",
  "RAW_PACKAGING",
  "COST",
  "SCHEDULE",
  "RISK",
];

async function devLogin(
  page: import("@playwright/test").Page,
  next: string,
  loginKey = E2E_LOGIN_KEY,
): Promise<void> {
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await page.getByPlaceholder("login_key").fill(loginKey);
  await page.getByRole("button", { name: "开发登录" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}

async function reloginAs(
  page: import("@playwright/test").Page,
  loginKey: string,
  next = "/projects",
): Promise<void> {
  await page.context().clearCookies();
  await devLogin(page, next, loginKey);
}

async function csrfHeaders(
  page: import("@playwright/test").Page,
): Promise<Record<string, string>> {
  await page.request.get("/api/v1/auth/csrf");
  const cookies = await page.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === "csrftoken")?.value;
  return csrf ? { "X-CSRFToken": csrf } : {};
}

async function authedJson(
  page: import("@playwright/test").Page,
  method: "POST" | "PATCH" | "GET",
  url: string,
  data?: unknown,
) {
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(await csrfHeaders(page)),
  };
  if (data !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  return page.request.fetch(url, {
    method,
    headers,
    data: data === undefined ? undefined : data,
  });
}

async function submitGateDecision(
  page: import("@playwright/test").Page,
  summary: string,
): Promise<void> {
  await page.locator('[data-test="decision-summary"]').fill(summary);
  await page.locator('[data-test="submit-decision"]').click();
  await expect(page.getByText("决策已记录：APPROVED")).toBeVisible();
}

async function createProjectFromOpportunity(
  page: import("@playwright/test").Page,
  uniqueTitle: string,
): Promise<string> {
  await page.goto("/opportunities/new");
  await page.locator('[data-test="title"]').fill(uniqueTitle);
  await page
    .locator('[data-test="market-analysis"]')
    .fill("Channel demand exists for protein snacks.");
  await page
    .locator('[data-test="core-selling-points"]')
    .fill("High protein and low sugar.");
  await page
    .locator('[data-test="target-users-needs"]')
    .fill("Breakfast replacement.");
  await page.locator('[data-test="suggested-retail-price"]').fill("9.90");
  await page
    .locator('[data-test="public-summary"]')
    .fill("High protein yogurt cup");
  await page.locator('[data-test="submit-proposal"]').click();
  await expect(
    page.locator('[data-test="opportunity-workbench"]'),
  ).toBeVisible();
  await page.locator('[data-test="submit-proposal"]').click();
  await expect(page.locator('[data-test="proposal-status"]')).toHaveText(
    "SUBMITTED",
  );
  await page.getByRole("button", { name: "开启提案评审" }).click();
  await expect(page.locator('[data-test="major-gate-decision"]')).toBeVisible();
  await submitGateDecision(page, "Approve proposal into case.");

  const boardAfterCase = await page.request.get("/api/v1/lifecycle-board");
  expect(boardAfterCase.ok()).toBeTruthy();
  const casePayload = await boardAfterCase.json();
  const caseItem = casePayload.items.find(
    (item: { title: string; lifecycle_stage: string }) =>
      item.title === uniqueTitle && item.lifecycle_stage === "CASE",
  );
  expect(caseItem?.candidate_public_id).toBeTruthy();
  const candidatePublicId = caseItem.candidate_public_id as string;

  const meResponse = await page.request.get("/api/v1/me");
  const me = await meResponse.json();
  const leadershipResponse = await authedJson(
    page,
    "POST",
    `/api/v1/project-candidates/${candidatePublicId}/leadership`,
    { version_no: 1, case_owner_public_id: me.public_id },
  );
  expect(leadershipResponse.ok()).toBeTruthy();
  const leadershipDetail = await leadershipResponse.json();
  const candidateVersionNo = leadershipDetail.version_no as number;

  for (const category of ASSESSMENT_CATEGORIES) {
    const assessmentResponse = await authedJson(
      page,
      "PATCH",
      `/api/v1/project-candidates/${candidatePublicId}/assessments/${category}`,
      { status: "CONFIRMED", conclusion: "Ready for review." },
    );
    expect(assessmentResponse.ok()).toBeTruthy();
  }

  const submitReviewResponse = await authedJson(
    page,
    "POST",
    `/api/v1/project-candidates/${candidatePublicId}/submit-review`,
    {
      version_no: candidateVersionNo,
      idempotency_key: `candidate-review-${Date.now()}`,
      resource_risk_summary: "Supply risk is mitigated.",
      proposed_schedule: { launch: "2026Q4" },
    },
  );
  expect(submitReviewResponse.ok()).toBeTruthy();
  const candidateDetail = await submitReviewResponse.json();
  const projectGateId = candidateDetail.active_stage_gate_public_id;
  expect(projectGateId).toBeTruthy();

  await page.goto(`/stage-gates/${projectGateId}/decide`);
  await submitGateDecision(page, "Approve project creation.");

  const projectsResponse = await page.request.get(
    "/api/v1/projects?page=1&page_size=100",
  );
  expect(projectsResponse.ok()).toBeTruthy();
  const projects = await projectsResponse.json();
  const created = projects.items.find(
    (item: { name: string }) => item.name === uniqueTitle,
  );
  expect(created?.public_id).toBeTruthy();
  return created.public_id as string;
}

async function findProjectByBusinessNo(
  page: import("@playwright/test").Page,
  businessNo: string,
): Promise<{ public_id: string; status: string }> {
  const response = await page.request.get(
    "/api/v1/projects?page=1&page_size=100",
  );
  expect(response.ok()).toBeTruthy();
  const payload = await response.json();
  const item = payload.items.find(
    (row: { business_no: string }) => row.business_no === businessNo,
  );
  expect(item?.public_id).toBeTruthy();
  return item;
}

async function stageGateIdFor(
  page: import("@playwright/test").Page,
  projectPublicId: string,
  stageCode: string,
): Promise<string> {
  const stages = await (
    await page.request.get(`/api/v1/projects/${projectPublicId}/stages`)
  ).json();
  const stage = stages.items.find(
    (item: { stage_code: string }) => item.stage_code === stageCode,
  );
  expect(stage?.stage_gate_public_id).toBeTruthy();
  return stage.stage_gate_public_id as string;
}

test("new product creates runtime stages and opens project workbench", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const uniqueTitle = `E2E Phase4 ${Date.now()}`;
  await devLogin(page, "/opportunities/new");
  const projectPublicId = await createProjectFromOpportunity(page, uniqueTitle);

  const stagesResponse = await page.request.get(
    `/api/v1/projects/${projectPublicId}/stages`,
  );
  expect(stagesResponse.ok()).toBeTruthy();
  const stages = await stagesResponse.json();
  const codes = stages.items.map(
    (item: { stage_code: string }) => item.stage_code,
  );
  expect(codes).toEqual(["D1", "D2", "D3", "D4", "D5", "L1", "L2", "L3"]);
  const l2 = stages.items.find(
    (item: { stage_code: string }) => item.stage_code === "L2",
  );
  expect(l2?.gate_code).toBe("FIRST_LAUNCH");
  expect(l2?.stage_gate_public_id).toBeTruthy();

  const tasksResponse = await page.request.get(
    `/api/v1/projects/${projectPublicId}/tasks`,
  );
  expect(tasksResponse.ok()).toBeTruthy();
  const tasks = await tasksResponse.json();
  expect(tasks.count).toBeGreaterThan(0);
  expect(
    tasks.items.some(
      (item: { task_code: string }) => item.task_code === "D1-CORE-BRIEF",
    ),
  ).toBeTruthy();

  const deliverablesResponse = await page.request.get(
    `/api/v1/projects/${projectPublicId}/deliverables`,
  );
  expect(deliverablesResponse.ok()).toBeTruthy();
  const deliverables = await deliverablesResponse.json();
  expect(deliverables.count).toBeGreaterThan(0);

  await page.goto(`/projects/${projectPublicId}`);
  await expect(page.locator('[data-test="project-workbench"]')).toBeVisible();
  await expect(page.getByText(uniqueTitle)).toBeVisible();
});

test("incomplete gate submission is blocked until core task completes", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await devLogin(page, "/projects");
  const project = await findProjectByBusinessNo(page, E2E_LAUNCH_BUSINESS_NO);
  const gateId = await stageGateIdFor(page, project.public_id, "D1");

  const validate = await authedJson(
    page,
    "POST",
    `/api/v1/stage-gates/${gateId}/validate`,
  );
  expect(validate.ok()).toBeTruthy();
  const body = await validate.json();
  expect(
    body.blocks.some(
      (b: { code: string }) => b.code === "CORE_TASK_INCOMPLETE",
    ),
  ).toBeTruthy();

  const submit = await authedJson(
    page,
    "POST",
    `/api/v1/stage-gates/${gateId}/submissions`,
    {
      idempotency_key: `e2e-block-${Date.now()}`,
    },
  );
  expect(submit.status()).toBe(409);
});

test("first launch publishes product and hands over monitoring", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await devLogin(page, "/projects");
  const project = await findProjectByBusinessNo(page, E2E_LAUNCH_BUSINESS_NO);
  if (project.status === "OPERATING") {
    await page.goto(`/projects/${project.public_id}`);
    await expect(page.locator('[data-test="project-workbench"]')).toBeVisible();
    return;
  }

  const gateId = await stageGateIdFor(page, project.public_id, "L2");
  const submit = await authedJson(page, "POST", `/api/v1/stage-gates/${gateId}/submissions`, {
    idempotency_key: `e2e-submit-launch-${project.public_id}`,
  });
  expect([201, 409]).toContain(submit.status());

  // Step 1: management-committee conclusion is recorded by the active user.
  const management = await authedJson(
    page,
    "POST",
    `/api/v1/stage-gates/${gateId}/first-launch-management-conclusion`,
    {
      management_conclusion: "APPROVED",
      decision_summary: "E2E first launch",
      idempotency_key: `e2e-first-launch-mgmt-${project.public_id}`,
    },
  );
  expect(management.status()).toBe(201);

  // Separation of duties: the same actor cannot also record the final decision.
  const selfFinal = await authedJson(
    page,
    "POST",
    `/api/v1/stage-gates/${gateId}/first-launch-final-decision`,
    {
      final_decision: "APPROVED",
      decision_summary: "self approval attempt",
      idempotency_key: `e2e-first-launch-self-${project.public_id}`,
    },
  );
  expect(selfFinal.status()).toBe(409);

  // Step 2: a distinct approver (boss) records the final decision.
  await reloginAs(page, E2E_APPROVER_LOGIN_KEY);
  const decision = await authedJson(
    page,
    "POST",
    `/api/v1/stage-gates/${gateId}/first-launch-final-decision`,
    {
      final_decision: "APPROVED",
      decision_summary: "E2E first launch",
      idempotency_key: `e2e-first-launch-final-${project.public_id}`,
    },
  );
  expect(decision.status()).toBe(201);
  const payload = await decision.json();
  expect(payload.final_decision).toBe("APPROVED");
  expect(payload.project_status).toBe("OPERATING");
  expect(payload.handover_error).toBeFalsy();

  const after = await page.request.get(`/api/v1/projects/${project.public_id}`);
  expect(after.ok()).toBeTruthy();
  expect((await after.json()).status).toBe("OPERATING");

  await page.goto(`/projects/${project.public_id}/launch-gate`);
  await expect(page.locator('[data-test="project-workbench"]')).toBeVisible();
});

test("publish pending repair is recorded when launch publish fails", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await devLogin(page, "/projects");
  const project = await findProjectByBusinessNo(page, E2E_REPAIR_BUSINESS_NO);
  if (project.status === "PUBLISH_PENDING_REPAIR") {
    await page.goto(`/projects/${project.public_id}`);
    await expect(page.locator(".el-alert__title")).toContainText(
      "PUBLISH_PENDING_REPAIR",
    );
    return;
  }

  const gateId = await stageGateIdFor(page, project.public_id, "L2");
  const submit = await authedJson(page, "POST", `/api/v1/stage-gates/${gateId}/submissions`, {
    idempotency_key: `e2e-submit-repair-${project.public_id}`,
  });
  expect([201, 409]).toContain(submit.status());

  const management = await authedJson(
    page,
    "POST",
    `/api/v1/stage-gates/${gateId}/first-launch-management-conclusion`,
    {
      management_conclusion: "APPROVED",
      decision_summary: "E2E repair path",
      idempotency_key: `e2e-repair-mgmt-${project.public_id}`,
    },
  );
  expect(management.status()).toBe(201);

  await reloginAs(page, E2E_APPROVER_LOGIN_KEY);
  const decision = await authedJson(
    page,
    "POST",
    `/api/v1/stage-gates/${gateId}/first-launch-final-decision`,
    {
      final_decision: "APPROVED",
      decision_summary: "E2E repair path",
      idempotency_key: `e2e-repair-final-${project.public_id}`,
    },
  );
  expect(decision.status()).toBe(201);
  const payload = await decision.json();
  expect(payload.project_status).toBe("PUBLISH_PENDING_REPAIR");
  expect(payload.handover_error).toBeTruthy();

  await reloginAs(page, E2E_LOGIN_KEY);
  await page.goto(`/projects/${project.public_id}`);
  await expect(page.locator(".el-alert__title")).toContainText(
    "PUBLISH_PENDING_REPAIR",
  );
});

test("publish pending repair retries with original decision to reach OPERATING", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await devLogin(page, "/projects");
  const project = await findProjectByBusinessNo(
    page,
    E2E_REPAIR_RETRY_BUSINESS_NO,
  );

  await page.goto(`/projects/${project.public_id}`);
  await expect(page.locator('[data-test="project-workbench"]')).toBeVisible();

  if (project.status !== "OPERATING") {
    await expect(
      page.locator('[data-test="retry-publish-repair"]'),
    ).toBeVisible();
    await page.locator('[data-test="retry-publish-repair"]').click();
    await expect(page.locator('[data-test="repair-message"]')).toContainText(
      "OPERATING",
    );
  }

  const after = await page.request.get(`/api/v1/projects/${project.public_id}`);
  expect(after.ok()).toBeTruthy();
  expect((await after.json()).status).toBe("OPERATING");

  // Retrying with the original decision is idempotent: it stays OPERATING and
  // does not re-enter repair (single product version is proven in unit tests).
  const retryAgain = await authedJson(
    page,
    "POST",
    `/api/v1/projects/${project.public_id}/publish-repair`,
  );
  expect(retryAgain.ok()).toBeTruthy();
  const retryPayload = await retryAgain.json();
  expect(retryPayload.status).toBe("OPERATING");
  expect(retryPayload.handover_error).toBeFalsy();
});

test("migration continue from D3 skips prior stages; archive creates no project", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await devLogin(page, "/projects");
  const stamp = Date.now();

  const continueBatch = await authedJson(
    page,
    "POST",
    "/api/v1/project-migration-batches",
    {
      batch_key: `e2e-continue-${stamp}`,
      rows: [
        {
          external_project_id: `EXT-D3-${stamp}`,
          name: `In-flight D3 ${stamp}`,
          current_stage_code: "D3",
          disposition: "CONTINUE",
          history_decision_summary: "D1/D2 approved offline.",
          history_tasks: [
            { task_code: "D1-LEGACY", name: "Legacy D1", stage_code: "D1" },
          ],
          history_files: [],
        },
      ],
    },
  );
  expect(continueBatch.status()).toBe(201);
  const continuePayload = await continueBatch.json();
  const continueBaselineId = continuePayload.baselines[0].public_id;

  const confirmContinue = await authedJson(
    page,
    "POST",
    `/api/v1/project-migration-baselines/${continueBaselineId}/confirm`,
    { disposition: "CONTINUE", idempotency_key: `confirm-continue-${stamp}` },
  );
  expect(confirmContinue.ok()).toBeTruthy();
  const continueResult = await confirmContinue.json();
  expect(continueResult.project_public_id).toBeTruthy();

  const continueStages = await page.request.get(
    `/api/v1/projects/${continueResult.project_public_id}/stages`,
  );
  expect(continueStages.ok()).toBeTruthy();
  const stageCodes = (await continueStages.json()).items.map(
    (item: { stage_code: string }) => item.stage_code,
  );
  expect(stageCodes[0]).toBe("D3");
  expect(stageCodes).not.toContain("D1");
  expect(stageCodes).not.toContain("D2");

  const archiveBatch = await authedJson(
    page,
    "POST",
    "/api/v1/project-migration-batches",
    {
      batch_key: `e2e-archive-${stamp}`,
      rows: [
        {
          external_project_id: `EXT-ARC-${stamp}`,
          name: `Archive only ${stamp}`,
          current_stage_code: "D3",
          disposition: "ARCHIVE_ONLY",
          history_decision_summary: "Closed offline.",
          history_tasks: [],
          history_files: [],
        },
      ],
    },
  );
  expect(archiveBatch.status()).toBe(201);
  const archivePayload = await archiveBatch.json();
  const archiveBaselineId = archivePayload.baselines[0].public_id;
  const confirmArchive = await authedJson(
    page,
    "POST",
    `/api/v1/project-migration-baselines/${archiveBaselineId}/confirm`,
    {
      disposition: "ARCHIVE_ONLY",
      idempotency_key: `confirm-archive-${stamp}`,
    },
  );
  expect(confirmArchive.ok()).toBeTruthy();
  const archiveResult = await confirmArchive.json();
  expect(archiveResult.project_public_id).toBeNull();
});

test("limited user cannot confirm migration or create emergency execution", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await devLogin(page, "/todos", E2E_LIMITED_LOGIN_KEY);

  const denyMigrate = await authedJson(
    page,
    "POST",
    "/api/v1/project-migration-batches",
    {
      batch_key: `deny-${Date.now()}`,
      rows: [
        {
          external_project_id: `EXT-DENY-${Date.now()}`,
          name: "Denied",
          current_stage_code: "D3",
          disposition: "ARCHIVE_ONLY",
          history_decision_summary: "n/a",
          history_tasks: [],
          history_files: [],
        },
      ],
    },
  );
  expect([403, 404]).toContain(denyMigrate.status());

  await page.context().clearCookies();
  await devLogin(page, "/projects", E2E_LOGIN_KEY);
  const project = await findProjectByBusinessNo(page, E2E_LAUNCH_BUSINESS_NO);

  await page.context().clearCookies();
  await devLogin(page, "/todos", E2E_LIMITED_LOGIN_KEY);
  const denyEmergency = await authedJson(
    page,
    "POST",
    `/api/v1/projects/${project.public_id}/emergency-executions`,
    {
      subject_summary: "Ship without paperwork",
      pending_confirmation: "Will file later",
      due_at: new Date(Date.now() + 86_400_000).toISOString(),
    },
  );
  expect([403, 404]).toContain(denyEmergency.status());
});
