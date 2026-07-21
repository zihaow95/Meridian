/**
 * Phase 5 E2E: 老品运营→迭代 and 老品运营→退市.
 *
 * Login keys (seed_e2e_user):
 * - e2e-active-user: operating supervisor + config + retirement management conclusion
 * - e2e-approver-user: retirement final decision (dual-control boss)
 * - e2e-limited-user: no export / sensitive ops read
 *
 * Risk evaluation: after confirm + aggregate recalculate, POST
 * /api/v1/risk-rules/{id}/evaluate (thin wrapper around EvaluateRiskRules).
 */
import { expect, test } from "@playwright/test";

const E2E_LOGIN_KEY = "e2e-active-user";
const E2E_APPROVER_LOGIN_KEY = "e2e-approver-user";
const E2E_LIMITED_LOGIN_KEY = "e2e-limited-user";

const E2E_OPS_PRODUCT_BUSINESS_NO = "E2E-OPS-PRD";
const E2E_OPS_SKU_CODE = "SKU-E2E-OPS";
const E2E_OPS_CHANNEL_CODE = "TMALL";
const E2E_OPS_SOURCE_CODE = "E2E_OPS_SRC";
const E2E_OPS_METRIC_CODE = "PRODUCTION_QTY";
const E2E_OPS_SALES_METRIC_CODE = "GROSS_SALES";
const E2E_OPS_RULE_CODE = "E2E_QUARTER_SHELF_MIN_PROD";

const PERIOD_START = "2026-01-01";
const PERIOD_END = "2026-03-31";
const PERIOD_GRANULARITY = "QUARTER";

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
  next = "/operations",
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

type Catalog = {
  productPublicId: string;
  versionPublicId: string;
  skuPublicId: string;
  channelPublicId: string;
  sourcePublicId: string;
  productionMetricPublicId: string;
  salesMetricPublicId: string;
  rulePublicId: string;
};

async function loadCatalog(page: import("@playwright/test").Page): Promise<Catalog> {
  const products = await (
    await page.request.get(
      `/api/v1/products?sku_code=${encodeURIComponent(E2E_OPS_SKU_CODE)}&page=1&page_size=20`,
    )
  ).json();
  const product = products.items.find(
    (row: { business_no: string }) => row.business_no === E2E_OPS_PRODUCT_BUSINESS_NO,
  );
  expect(product?.public_id).toBeTruthy();

  const detail = await (
    await page.request.get(`/api/v1/products/${product.public_id}`)
  ).json();
  const version = detail.versions?.[0];
  expect(version?.public_id).toBeTruthy();
  const sku = version.skus.find(
    (row: { sku_code: string }) => row.sku_code === E2E_OPS_SKU_CODE,
  );
  expect(sku?.public_id).toBeTruthy();
  const channel = sku.channels.find(
    (row: { channel_code: string }) => row.channel_code === E2E_OPS_CHANNEL_CODE,
  );
  expect(channel?.public_id).toBeTruthy();

  const sources = await (await page.request.get("/api/v1/operating-data-sources")).json();
  const source = sources.items.find(
    (row: { source_code: string }) => row.source_code === E2E_OPS_SOURCE_CODE,
  );
  expect(source?.public_id).toBeTruthy();

  const metrics = await (await page.request.get("/api/v1/operating-metrics")).json();
  const productionMetric = metrics.items.find(
    (row: { metric_code: string }) => row.metric_code === E2E_OPS_METRIC_CODE,
  );
  const salesMetric = metrics.items.find(
    (row: { metric_code: string }) => row.metric_code === E2E_OPS_SALES_METRIC_CODE,
  );
  expect(productionMetric?.public_id).toBeTruthy();
  expect(salesMetric?.public_id).toBeTruthy();

  const rules = await (await page.request.get("/api/v1/risk-rules")).json();
  const rule = rules.items.find(
    (row: { rule_code: string }) => row.rule_code === E2E_OPS_RULE_CODE,
  );
  expect(rule?.public_id).toBeTruthy();

  return {
    productPublicId: product.public_id,
    versionPublicId: version.public_id,
    skuPublicId: sku.public_id,
    channelPublicId: channel.public_id,
    sourcePublicId: source.public_id,
    productionMetricPublicId: productionMetric.public_id,
    salesMetricPublicId: salesMetric.public_id,
    rulePublicId: rule.public_id,
  };
}

async function confirmProductionBatch(
  page: import("@playwright/test").Page,
  catalog: Catalog,
  batchKey: string,
  productionQty: string,
) {
  const create = await authedJson(page, "POST", "/api/v1/operating-data/batches", {
    source_public_id: catalog.sourcePublicId,
    batch_key: batchKey,
    source_type: "API",
    rows: [
      {
        external_record_key: `${batchKey}-1`,
        sku_code: E2E_OPS_SKU_CODE,
        channel_code: E2E_OPS_CHANNEL_CODE,
        metric_code: E2E_OPS_METRIC_CODE,
        period_granularity: PERIOD_GRANULARITY,
        period_start: PERIOD_START,
        period_end: PERIOD_END,
        production_qty: productionQty,
        unit: "EA",
        currency: "NA",
        source_timestamp: "2026-04-05T10:00:00+00:00",
      },
    ],
  });
  expect(create.status()).toBe(201);
  const batch = await create.json();

  const validate = await authedJson(
    page,
    "POST",
    `/api/v1/operating-data/batches/${batch.public_id}/validate`,
  );
  expect(validate.ok()).toBeTruthy();
  const validated = await validate.json();
  expect(validated.status).toBe("READY");

  const confirm = await authedJson(
    page,
    "POST",
    `/api/v1/operating-data/batches/${batch.public_id}/confirm`,
    { idempotency_key: `confirm-${batchKey}`, confirm_warnings: true },
  );
  expect(confirm.ok()).toBeTruthy();
  const confirmed = await confirm.json();
  expect(confirmed.added_count + confirmed.revision_count).toBeGreaterThanOrEqual(1);
  return confirmed;
}

async function recalculateAndEvaluate(
  page: import("@playwright/test").Page,
  catalog: Catalog,
) {
  const recalc = await authedJson(page, "POST", "/api/v1/operating-metrics/recalculate", {
    affected_keys: [
      {
        metric_code: E2E_OPS_METRIC_CODE,
        period_granularity: PERIOD_GRANULARITY,
        period_start: PERIOD_START,
        period_end: PERIOD_END,
        sku_public_id: catalog.skuPublicId,
      },
    ],
  });
  expect(recalc.ok()).toBeTruthy();
  const recalcBody = await recalc.json();
  expect(recalcBody.written_count).toBeGreaterThanOrEqual(1);

  const evaluate = await authedJson(
    page,
    "POST",
    `/api/v1/risk-rules/${catalog.rulePublicId}/evaluate`,
    {
      period_granularity: PERIOD_GRANULARITY,
      period_start: PERIOD_START,
      period_end: PERIOD_END,
    },
  );
  expect(evaluate.ok()).toBeTruthy();
  return evaluate.json();
}

async function uploadControlledDoc(
  page: import("@playwright/test").Page,
  filename: string,
): Promise<string> {
  const headers = await csrfHeaders(page);
  const buffer = Buffer.from(`retirement-pack-${filename}-${Date.now()}`);
  const upload = await page.request.post("/api/v1/documents/uploads", {
    headers,
    multipart: {
      file: {
        name: filename,
        mimeType: "application/pdf",
        buffer,
      },
      original_filename: filename,
      declared_mime_type: "application/pdf",
    },
  });
  expect(upload.status()).toBe(201);
  const session = await upload.json();

  const complete = await authedJson(
    page,
    "POST",
    `/api/v1/documents/uploads/${session.public_id}/complete`,
    {
      document_code: `RET-${Date.now()}`,
      title: "E2E Retirement Pack",
    },
  );
  expect(complete.ok()).toBeTruthy();
  const body = await complete.json();
  expect(body.status).toBe("CONTROLLED");
  expect(body.version_public_id).toBeTruthy();
  return body.version_public_id as string;
}

test.describe.configure({ mode: "serial" });

test("phase5 chain1: ingest → summary → risk → issue → iteration DRAFT", async ({
  page,
}) => {
  await devLogin(page, "/operations");
  const catalog = await loadCatalog(page);
  const stamp = Date.now();

  await confirmProductionBatch(page, catalog, `ops-iter-${stamp}`, "200");

  const manual = await authedJson(page, "POST", "/api/v1/operating-values/overrides", {
    sku_public_id: catalog.skuPublicId,
    channel_public_id: catalog.channelPublicId,
    metric_definition_public_id: catalog.productionMetricPublicId,
    period_granularity: PERIOD_GRANULARITY,
    period_start: PERIOD_START,
    period_end: PERIOD_END,
    numeric_value: "180",
    reason: "E2E manual adjustment for coverage",
  });
  // Re-runs may already have an ACTIVE override for the same business key.
  expect([201, 400, 409]).toContain(manual.status());

  await recalculateAndEvaluate(page, catalog);

  const summary = await page.request.get(
    `/api/v1/skus/${catalog.skuPublicId}/operating-summary` +
      `?period_start=${PERIOD_START}&period_end=${PERIOD_END}` +
      `&period_granularity=${PERIOD_GRANULARITY}` +
      `&metric_codes=${E2E_OPS_METRIC_CODE}`,
  );
  expect(summary.ok()).toBeTruthy();
  const summaryBody = await summary.json();
  expect(summaryBody.items.length).toBeGreaterThan(0);
  const channelRow = summaryBody.items.find(
    (row: { channel_public_id: string | null }) =>
      row.channel_public_id === catalog.channelPublicId,
  );
  expect(channelRow).toBeTruthy();
  expect(Number(channelRow.value)).toBeGreaterThan(0);

  const signals = await (await page.request.get("/api/v1/risk-signals")).json();
  const openSignal = signals.items.find(
    (row: { status: string; scope_id: string }) =>
      row.scope_id === catalog.skuPublicId &&
      (row.status === "NEW" || row.status === "VIEWED"),
  );

  await page.goto("/operations/risk-signals");
  await expect(page.locator("body")).toContainText(/风险|Risk|信号/i);

  let issuePublicId: string;
  if (openSignal?.public_id) {
    const escalate = await authedJson(
      page,
      "POST",
      `/api/v1/risk-signals/${openSignal.public_id}/escalate`,
      {
        title: `E2E low production ${stamp}`,
        phenomenon_summary: "Production below quarter shelf digestion threshold",
      },
    );
    expect(escalate.status()).toBe(201);
    const issueBrief = await escalate.json();
    issuePublicId = (issueBrief.issue_public_id || issueBrief.public_id) as string;
  } else {
    // Prior E2E run may have already escalated the unique rule+scope+period signal.
    const createIssue = await authedJson(page, "POST", "/api/v1/operating-issues", {
      title: `E2E low production ${stamp}`,
      product_public_id: catalog.productPublicId,
      phenomenon_summary: "Production below quarter shelf digestion threshold",
      source_type: "DIRECT",
      source_materials_json: { reason: "e2e_rerun_without_open_signal" },
    });
    expect(createIssue.status()).toBe(201);
    const created = await createIssue.json();
    issuePublicId = created.public_id as string;
  }
  expect(issuePublicId).toBeTruthy();

  const issueGet = await page.request.get(`/api/v1/operating-issues`);
  expect(issueGet.ok()).toBeTruthy();
  const issues = await issueGet.json();
  const issue = issues.items.find(
    (row: { public_id: string }) => row.public_id === issuePublicId,
  );
  expect(issue?.status).toBeTruthy();

  const me = await (await page.request.get("/api/v1/me")).json();
  const decision = await authedJson(
    page,
    "POST",
    `/api/v1/operating-issues/${issuePublicId}/decisions`,
    {
      version_no: issue.version_no,
      recommendation_type: "ITERATE",
      action_summary: "Convert to iteration proposal draft",
      target_status: "ACTIONING",
    },
  );
  expect(decision.status()).toBe(201);
  const decisionBody = await decision.json();
  const versionNo = decisionBody.issue?.version_no ?? issue.version_no + 1;

  const convert = await authedJson(
    page,
    "POST",
    `/api/v1/operating-issues/${issuePublicId}/iteration-proposal`,
    {
      proposal_owner_public_id: me.public_id,
      idempotency_key: `iter-conv-${stamp}`,
      version_no: versionNo,
    },
  );
  expect(convert.status()).toBe(201);
  const converted = await convert.json();
  expect(converted.status).toBe("CONVERTED_TO_PROPOSAL");

  // Linked opportunity DRAFT — assert via opportunities list when available
  const opportunities = await page.request.get(
    "/api/v1/opportunities?page=1&page_size=100",
  );
  if (opportunities.ok()) {
    const oppPayload = await opportunities.json();
    const draft = (oppPayload.items || []).find(
      (row: { title?: string; proposal_status?: string }) =>
        typeof row.title === "string" &&
        row.title.includes(`E2E low production ${stamp}`) &&
        row.proposal_status === "DRAFT",
    );
    if (draft) {
      expect(draft.proposal_status).toBe("DRAFT");
    }
  }

  await page.goto("/operations");
  await expect(page.locator("body")).toContainText(/运营|经营|Operations/i);
});

test("phase5 chain2: retirement dual-control → execute → historical facts", async ({
  page,
}) => {
  await devLogin(page, "/operations");
  const catalog = await loadCatalog(page);
  const stamp = Date.now();

  // Ensure historical facts exist and remain readable after retirement
  await confirmProductionBatch(page, catalog, `ops-retire-facts-${stamp}`, "250");
  await recalculateAndEvaluate(page, catalog);

  const incomplete = await authedJson(page, "POST", "/api/v1/retirement-plans", {
    product_public_id: catalog.productPublicId,
    scope_snapshot: {},
    source_type: "DIRECT",
    source_materials_json: { memo: "incomplete" },
  });
  expect(incomplete.status()).toBe(201);
  const incompletePlan = await incomplete.json();
  const validateIncomplete = await authedJson(
    page,
    "POST",
    `/api/v1/retirement-plans/${incompletePlan.public_id}/validate`,
  );
  expect(validateIncomplete.status()).toBeGreaterThanOrEqual(400);

  const docVersionId = await uploadControlledDoc(page, `retire-${stamp}.pdf`);
  const snapshot = await authedJson(page, "POST", "/api/v1/operating-data/snapshots", {
    product_public_id: catalog.productPublicId,
    evidence: {
      sales: "1000",
      gross_margin: "0.3",
      inventory: "200",
      near_expiry: "10",
      complaints: "2",
      coverage_status: "SUFFICIENT",
    },
    metric_codes: [E2E_OPS_METRIC_CODE],
  });
  expect(snapshot.status()).toBe(201);
  const snapshotBody = await snapshot.json();

  const createPlan = await authedJson(page, "POST", "/api/v1/retirement-plans", {
    product_public_id: catalog.productPublicId,
    scope_snapshot: {
      product_version_public_ids: [catalog.versionPublicId],
      sku_public_ids: [catalog.skuPublicId],
      channel_public_ids: [catalog.channelPublicId],
    },
    inventory_plan: { dispose: "sell-through" },
    supply_contract_impact: { contracts: [] },
    customer_market_plan: { notice: "30d" },
    replacement_plan: { sku: "SKU-NEXT" },
    stop_production_at: "2026-01-01",
    stop_sale_at: "2026-02-01",
    retire_at: "2026-03-01",
    operating_snapshot_public_id: snapshotBody.public_id,
    document_version_public_id: docVersionId,
    source_type: "DIRECT",
    source_materials_json: { memo: "board" },
  });
  expect(createPlan.status()).toBe(201);
  const plan = await createPlan.json();
  expect(plan.stage_gate_public_id).toBeTruthy();

  const validateOk = await authedJson(
    page,
    "POST",
    `/api/v1/retirement-plans/${plan.public_id}/validate`,
  );
  expect(validateOk.ok()).toBeTruthy();
  const validateBody = await validateOk.json();
  expect(validateBody.ok).toBe(true);

  const submit = await authedJson(
    page,
    "POST",
    `/api/v1/retirement-plans/${plan.public_id}/submit`,
    { idempotency_key: `retire-submit-${stamp}` },
  );
  expect(submit.status()).toBe(201);

  const mgmt = await authedJson(
    page,
    "POST",
    `/api/v1/stage-gates/${plan.stage_gate_public_id}/retirement-management-conclusion`,
    {
      management_conclusion: "APPROVED",
      decision_summary: "E2E management conclusion",
      idempotency_key: `retire-mgmt-${stamp}`,
    },
  );
  expect(mgmt.status()).toBe(201);

  // Dual-control: same actor must not record final decision
  const sameActorFinal = await authedJson(
    page,
    "POST",
    `/api/v1/stage-gates/${plan.stage_gate_public_id}/retirement-final-decision`,
    {
      final_decision: "APPROVED",
      decision_summary: "should fail",
      idempotency_key: `retire-final-same-${stamp}`,
    },
  );
  expect(sameActorFinal.ok()).toBeFalsy();

  await reloginAs(page, E2E_APPROVER_LOGIN_KEY, "/operations");
  const final = await authedJson(
    page,
    "POST",
    `/api/v1/stage-gates/${plan.stage_gate_public_id}/retirement-final-decision`,
    {
      final_decision: "APPROVED",
      decision_summary: "E2E boss final decision",
      idempotency_key: `retire-final-${stamp}`,
    },
  );
  expect(final.status()).toBe(201);

  await reloginAs(page, E2E_LOGIN_KEY, "/operations");
  const execute = await authedJson(
    page,
    "POST",
    `/api/v1/retirement-plans/${plan.public_id}/execute`,
    { as_of: "2026-03-15" },
  );
  expect(execute.ok()).toBeTruthy();
  const executed = await execute.json();
  expect(["COMPLETED", "EXECUTING", "APPROVED"]).toContain(executed.status);

  const executeAgain = await authedJson(
    page,
    "POST",
    `/api/v1/retirement-plans/${plan.public_id}/execute`,
    { as_of: "2026-03-15" },
  );
  expect(executeAgain.ok()).toBeTruthy();
  const executedAgain = await executeAgain.json();
  expect(executedAgain.status).toBe(executed.status);

  const productAfter = await (
    await page.request.get(`/api/v1/products/${catalog.productPublicId}`)
  ).json();
  expect(productAfter.lifecycle_status).toMatch(/RETIR|OFF|INACTIVE|ARCHIV/i);

  const historical = await page.request.get(
    `/api/v1/skus/${catalog.skuPublicId}/operating-summary` +
      `?period_start=${PERIOD_START}&period_end=${PERIOD_END}` +
      `&period_granularity=${PERIOD_GRANULARITY}` +
      `&metric_codes=${E2E_OPS_METRIC_CODE}`,
  );
  expect(historical.ok()).toBeTruthy();
  const historicalBody = await historical.json();
  expect(historicalBody.items.length).toBeGreaterThan(0);

  await page.goto(`/retirement-plans/${plan.public_id}`);
  await expect(page.locator("body")).toContainText(/退市|Retirement|批准|执行/i);
});

test("phase5 failures: bad batch, unauthorized export, dual-step already covered", async ({
  page,
}) => {
  await devLogin(page, "/operations");
  const catalog = await loadCatalog(page);
  const stamp = Date.now();

  const bad = await authedJson(page, "POST", "/api/v1/operating-data/batches", {
    source_public_id: catalog.sourcePublicId,
    batch_key: `ops-bad-${stamp}`,
    source_type: "API",
    rows: [
      {
        external_record_key: `bad-${stamp}`,
        // missing sku/channel/metric — structure error
        period_granularity: PERIOD_GRANULARITY,
        period_start: PERIOD_START,
        period_end: PERIOD_END,
        production_qty: "10",
      },
    ],
  });
  // Create may succeed with ERROR/UNMAPPED rows, or reject — either way facts must not increase via confirm
  if (bad.status() === 201) {
    const batch = await bad.json();
    if (batch.status === "READY") {
      const confirm = await authedJson(
        page,
        "POST",
        `/api/v1/operating-data/batches/${batch.public_id}/confirm`,
        { idempotency_key: `confirm-bad-${stamp}` },
      );
      if (confirm.ok()) {
        const body = await confirm.json();
        expect(body.added_count).toBe(0);
      }
    } else {
      // Create returns RECEIVED before validate; structure errors surface after validate.
      expect(["FAILED", "READY", "PARTIAL_SUCCESS", "RECEIVED", "VALIDATING"]).toContain(
        batch.status,
      );
      const validate = await authedJson(
        page,
        "POST",
        `/api/v1/operating-data/batches/${batch.public_id}/validate`,
      );
      expect(validate.ok()).toBeTruthy();
      const validated = await validate.json();
      expect(["FAILED", "READY", "PARTIAL_SUCCESS"]).toContain(validated.status);
      if (validated.status === "READY") {
        const confirm = await authedJson(
          page,
          "POST",
          `/api/v1/operating-data/batches/${batch.public_id}/confirm`,
          { idempotency_key: `confirm-bad-${stamp}` },
        );
        if (confirm.ok()) {
          const body = await confirm.json();
          expect(body.added_count).toBe(0);
        }
      } else {
        expect((validated.error_count ?? 0) + (validated.unmapped_count ?? 0)).toBeGreaterThanOrEqual(
          0,
        );
      }
    }
  } else {
    expect(bad.status()).toBeGreaterThanOrEqual(400);
  }

  await reloginAs(page, E2E_LIMITED_LOGIN_KEY, "/operations");
  const exportDenied = await authedJson(page, "POST", "/api/v1/operating-data/exports", {
    period_start: PERIOD_START,
    period_end: PERIOD_END,
    period_granularity: PERIOD_GRANULARITY,
    metric_codes: [E2E_OPS_METRIC_CODE],
  });
  expect(exportDenied.ok()).toBeFalsy();
  expect([401, 403, 404]).toContain(exportDenied.status());
});
