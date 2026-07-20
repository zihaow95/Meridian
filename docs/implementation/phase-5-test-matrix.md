# 阶段5 运营、迭代和退市 —— 测试矩阵

状态：**执行基线已建立 / OPS 未实现** — 分支自阶段4 GO tip `edd50ce`（`codex/phase-4-development-first-launch`）。本轮 Task 5.0 仅建立证据矩阵与主计划链接；不得将阶段4文档旧结果冒充阶段5实现通过。

对应计划：`docs/superpowers/plans/2026-07-20-phase-5-operations-iteration-retirement.md`

对应 TRD：`docs/trd/04-operations-iteration-retirement-trd.md`

对应 PRD：`docs/prd/04-operations-iteration-retirement-prd.md`

对应阶段4退出依据：`docs/implementation/phase-4-checkpoint.md`、`docs/implementation/phase-4-test-matrix.md`

> 状态取值：`未实现` / `进行中` / `已通过：<测试位置>` / `后置：<阶段>`。
> 「已通过」必须对应本阶段5检出上的真实自动化证据；阶段4门禁复验只证明开工基线，不关闭任何 OPS。

## 权限动作裁决（Task 5.0）

TRD 04 第15节动作清单未单列数据源配置与监控范围维护，但 PRD 明确要求：

- 系统管理员可维护数据源、指标和同步任务（不默认读取敏感经营值）；
- 经营监督人及其产品/SKU/渠道范围可配置。

本计划裁决：新增两个支持动作，其余动作严格沿用 TRD 04 第15节；**不扩张为平台管理员业务读取权**。

| 动作码 | 来源 | 用途 | 状态 |
|---|---|---|---|
| `data_source.configure` | PRD 角色表 + 前置条件「数据源已发布」；计划 §1 裁决 | 配置/发布经营数据源与映射（经 ConfigurationVersion） | 未实现 |
| `monitoring_scope.manage` | PRD「经营监督人及其产品/渠道范围已配置」；计划 §1 裁决 | 维护 MonitoringAssignment 有效监督范围 | 未实现 |

若产品负责人拒绝新增上述支持动作，停线并先修订 TRD 04 权限目录，不得静默用平台管理员角色替代。

## OPS 需求追踪

| 需求 | 说明 | 领域 | 服务 | 权限 | API | 前端/E2E | 失败/并发证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| OPS-001 | SKU × 渠道 × 真实期间经营事实 | operations | `ConfirmOperatingIngestionBatch` / `OperatingFact` | `operating_fact.read` | batches + summary | 看板下钻 | 迟到修订 SUPERSEDED；active_slot 唯一 | 未实现 |
| OPS-002 | API / Excel/CSV / 手工同一接入链 | integrations | `CreateIngestionBatch` / parsers | `ingestion_batch.create` | `POST .../batches` | 批次页 | 结构错误阻行；文件须 ACTIVE DocumentVersion | 未实现 |
| OPS-003 | 暂存校验、幂等、结果报告 | integrations / operations | Validate / Confirm / Retry | `ingestion_batch.*` / `mapping.resolve` | confirm/retry/unmapped | 批次页错误行 | `source_id+batch_key`；两连接只一组事实 | 未实现 |
| OPS-004 | 人工有效值与原始事实分离 | operations | Create/Modify/RevokeManualEffectiveValue | `manual_effective_value.*` | overrides/revoke | 看板人工标记 | 同键并发仅一 ACTIVE | 未实现 |
| OPS-005 | 可重建汇总与下钻 | operations | `RecalculateMetricAggregates` / queries | `operating_fact.read` | product/sku summary | 经营看板 | NOT_COMPARABLE / INSUFFICIENT | 未实现 |
| OPS-006 | 版本化指标与受控计算器 | operations / configuration | `PublishMetricDefinition` | `metric_rule.configure` | operating-metrics | — | 发布后不可改；拒任意脚本 | 未实现 |
| OPS-007 | 风险规则、唯一信号、迟到重算 | operations | PublishRiskRule / Evaluate / Recalculate | `risk_signal.*` | risk-signals | 风险中心 | rule+scope+period 唯一；历史信号不改写 | 未实现 |
| OPS-008 | 经营议题、主关联、研判 | operations | CreateOperatingIssue / RecordDecision | `operating_issue.*` / escalate | operating-issues | 议题工作台 | 活动主议题唯一；version_no 409 | 未实现 |
| OPS-009 | 议题转迭代 DRAFT 提案 | operations / opportunities | `ConvertIssueToIterationProposal` | `iteration_proposal.convert` | iteration-proposal | 议题页 | `issue_id+conversion_type`；资格事务内确认 | 未实现 |
| OPS-010 | 产品发布事件回写议题 | operations consumers | `HandleProductVersionPublished` | outbox 幂等 | — | 议题关联版本 | event_id 重放只回写一次 | 未实现 |
| OPS-011 | PRODUCT_RETIREMENT 重大门 | stage_gates / operations | Validate/Submit/RecordRetirement* | `retirement.*` | retirement + stage-gates | 退市页 | 双步骤分认证；批准≠执行 | 未实现 |
| OPS-012 | 退市计划执行与历史保留 | operations / products | `ExecuteRetirementPlan` / `ApplyApprovedRetirementAction` | `retirement_plan.execute` | execute | 退市执行状态 | 动作幂等重试；不物理删除 | 未实现 |
| OPS-013 | 看板、风险中心、议题工作台 | frontend / API | query services | 范围+数据等级 | summaries/signals/issues | operations 路由 | 403/409/数据不足反馈 | 未实现 |
| OPS-014 | 对象范围、数据等级、导出 | authorization / operations | exports + visible_resources | `operating_detail.export` 等 | exports | 导出票据 | 平台管理员默认不可读敏感值；导出独立审计 | 未实现 |

## 领域 / 服务切片

| 切片 | 计划任务 | 预期测试位置（待实现） | 状态 |
|---|---|---|---|
| 监控范围与指标版本 | Task 5.1 | `test_monitoring_assignments.py`、`test_metric_definitions.py`、`test_permissions.py` | 未实现 |
| 数据源配置 | Task 5.1 | `test_data_sources.py` | 未实现 |
| 接入批次与经营事实 | Task 5.2 | `test_operating_ingestion.py`、`test_operating_facts.py`、`test_ingestion_concurrency.py` | 未实现 |
| 人工有效值 | Task 5.2 | `test_effective_values.py` | 未实现 |
| 汇总与快照 | Task 5.3 | `test_metric_aggregates.py`、`test_operating_snapshots.py`、`test_aggregate_tasks.py` | 未实现 |
| 风险信号与重算 | Task 5.4 | `test_risk_rules.py`、`test_risk_signals.py`、`test_signal_recalculation.py`、`test_risk_concurrency.py` | 未实现 |
| 经营议题 | Task 5.5 | `test_operating_issues.py`、`test_issue_permissions.py`、`test_issue_concurrency.py` | 未实现 |
| 迭代转换与回写 | Task 5.6 | `test_iteration_source_draft.py`、`test_issue_conversion.py`、`test_iteration_result_consumer.py` | 未实现 |
| 退市门与执行 | Task 5.7 | `test_retirement*.py`、`test_retirement_gate.py`、`test_retirement_state.py` | 未实现 |
| API / OpenAPI | Task 5.8 | `test_operating_api.py`、`test_phase5_openapi.py`、`test_operating_export.py` | 未实现 |
| 前端工作台 | Task 5.9 | `frontend/src/modules/operations/*.spec.ts` | 未实现 |
| E2E 双主链 | Task 5.10 | `tests/e2e/operations-iteration-retirement.spec.ts` | 未实现 |

## API / OpenAPI

| 场景 | 证据 | 状态 |
|---|---|---|
| TRD 04 第14节路径 + 配置/执行入口 | Task 5.8；`backend/openapi/schema.yaml` | 未实现 |
| 生成类型 `frontend/src/api/generated/schema.d.ts` | `npm.cmd run api:generate` | 未实现 |
| 权限默认拒绝、404 风格不泄露、导出独立判权 | `test_operating_query_permissions.py` | 未实现 |

## 前端

| 场景 | 证据 | 状态 |
|---|---|---|
| 批次 / 看板 / 风险 / 议题 / 退市 | `frontend/src/modules/operations/*` | 未实现 |
| 产品详情运营入口、todo 深链 | `ProductDetailView.vue`、`TodoListView.vue`、router | 未实现 |

## E2E

| 场景 | 证据 | 状态 |
|---|---|---|
| 老品运营 → 迭代 DRAFT / 发布回写 | `operations-iteration-retirement.spec.ts` 主链一 | 未实现 |
| 老品运营 → 退市批准与执行 | 同上主链二 | 未实现 |
| 失败/权限：结构错误、数据不足、未授权导出、同人双步骤、执行重试 | 同上 | 未实现 |

## Task 5.0 基线门禁

| 检查 | 结果 | 日期 |
|---|---|---|
| 分支基线 | `codex/phase-5-operations-iteration-retirement` @ `edd50ce`（阶段4 GO tip） | 2026-07-20 |
| `scripts\check.cmd`（阶段5检出复验） | **通过** — `All quality gates passed.`（exit 0）；pytest 319；Vitest 48；Playwright 16；mypy 261；Docker `meridian-backend:ci` / `meridian-frontend:ci` | 2026-07-20 |
| OPS-001—014 | 全部 `未实现`；未提前关闭 | 2026-07-20 |
