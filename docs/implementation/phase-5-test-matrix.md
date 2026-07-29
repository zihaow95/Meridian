# 阶段5 运营、迭代和退市 —— 测试矩阵

状态：**NO-GO / 八次双轴再复审待定** — 分支 `codex/phase-5-operations-iteration-retirement`；七次复验遗留证据及八次初审新增的冷库所有权保护、seed 稳定快照证据均已补齐。

对应计划：`docs/superpowers/plans/2026-07-20-phase-5-operations-iteration-retirement.md`

对应 TRD：`docs/trd/04-operations-iteration-retirement-trd.md`

对应 PRD：`docs/prd/04-operations-iteration-retirement-prd.md`

对应检查点：`docs/implementation/phase-5-checkpoint.md`

> 状态取值：`未实现` / `进行中` / `已通过：<测试位置>` / `后置：<阶段>`。
> 「已通过」必须对应本阶段5检出上的真实自动化证据。

## 权限动作裁决

| 动作码 | 来源 | 用途 | 状态 |
|---|---|---|---|
| `data_source.configure` | PRD + 计划 §1 | 配置/发布经营数据源与映射 | 已通过：`0008_seed_operations_actions` + `test_data_sources.py` |
| `monitoring_scope.manage` | PRD + 计划 §1 | 维护 MonitoringAssignment | 已通过：`test_monitoring_assignments.py` / `test_permissions.py` |

## OPS 需求追踪

| 需求 | 说明 | 领域 | 服务 | 权限 | API | 前端/E2E | 失败/并发证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| OPS-001 | SKU × 渠道 × 真实期间经营事实 | operations | `ConfirmOperatingIngestionBatch` | `operating_fact.read` | batches + summary | 看板 / E2E 主链一 | `test_operating_facts.py` / concurrency | 已通过：单元 + E2E |
| OPS-002 | API / Excel/CSV / 手工同一接入链 | integrations | `CreateIngestionBatch` | `ingestion_batch.create` | `POST .../batches` | 批次页 | `test_operating_ingestion.py` | 已通过 |
| OPS-003 | 暂存校验、幂等、结果报告 | integrations / operations | Validate / Confirm / Retry | `ingestion_batch.*` | confirm/retry/unmapped/validate | 批次页 / E2E | concurrency + E2E bad batch | 已通过 |
| OPS-004 | 人工有效值与原始事实分离 | operations | Create/Modify/RevokeManualEffectiveValue | `manual_effective_value.*` | overrides/revoke | 批次页 | `test_effective_values.py` | 已通过 |
| OPS-005 | 可重建汇总与下钻 | operations | `RecalculateMetricAggregates` | `operating_fact.read` | summary + recalculate | 经营看板 | `test_metric_aggregates.py` | 已通过 |
| OPS-006 | 版本化指标与受控计算器 | operations | `PublishMetricDefinition` | `metric_rule.configure` | operating-metrics | — | `test_metric_definitions.py` | 已通过 |
| OPS-007 | 风险规则、唯一信号、迟到重算 | operations | Evaluate / Recalculate | `risk_signal.*` | risk-rules/evaluate | 风险中心 / E2E | `test_risk_*.py` | 已通过 |
| OPS-008 | 经营议题、主关联、研判 | operations | Create / RecordDecision | `operating_issue.*` | operating-issues | 议题页 / E2E | `test_operating_issues.py` | 已通过 |
| OPS-009 | 议题转迭代 DRAFT 提案 | operations / opportunities | `ConvertIssueToIterationProposal` | `iteration_proposal.convert` | iteration-proposal | 议题页 / E2E | `test_issue_conversion.py` | 已通过 |
| OPS-010 | 产品发布事件回写议题 | operations consumers | `HandleProductVersionPublished` | outbox 幂等 | — | — | `test_iteration_result_consumer.py` | 已通过：单元（E2E 未全链路发布回写） |
| OPS-011 | PRODUCT_RETIREMENT 重大门 | stage_gates / operations | Validate/Submit/RecordRetirement* | `retirement.*` | retirement + stage-gates | 退市页 / E2E 主链二 | `test_retirement*.py` | 已通过 |
| OPS-012 | 退市计划执行与历史保留 | operations / products | `ExecuteRetirementPlan` | `retirement_plan.execute` | execute | E2E | `test_retirement_state.py` | 已通过 |
| OPS-013 | 看板、风险中心、议题工作台 | frontend / API | query services | 范围+数据等级 | summaries/signals/issues | operations 路由 | Vitest 14 + E2E UI smoke | 已通过 |
| OPS-014 | 对象范围、数据等级、导出 | authorization / operations | exports + visible_resources | `operating_detail.export` | exports | E2E 拒绝导出 | `test_operating_export.py` / query permissions | 已通过 |

## 领域 / 服务切片

| 切片 | 计划任务 | 测试位置 | 状态 |
|---|---|---|---|
| 监控范围与指标版本 | 5.1 | `test_monitoring_assignments.py`、`test_metric_definitions.py`、`test_permissions.py` | 已通过 |
| 数据源配置 | 5.1 | `test_data_sources.py` | 已通过 |
| 接入批次与经营事实 | 5.2 | `test_operating_ingestion.py`、`test_operating_facts.py`、`test_ingestion_concurrency.py` | 已通过 |
| 人工有效值 | 5.2 | `test_effective_values.py` | 已通过 |
| 汇总与快照 | 5.3 | `test_metric_aggregates.py`、`test_operating_snapshots.py`、`test_aggregate_tasks.py` | 已通过 |
| 风险信号与重算 | 5.4 | `test_risk_rules.py`、`test_risk_signals.py`、`test_signal_recalculation.py`、`test_risk_concurrency.py` | 已通过 |
| 经营议题 | 5.5 | `test_operating_issues.py`、`test_issue_permissions.py`、`test_issue_concurrency.py` | 已通过 |
| 迭代转换与回写 | 5.6 | `test_iteration_source_draft.py`、`test_issue_conversion.py`、`test_iteration_result_consumer.py` | 已通过 |
| 退市门与执行 | 5.7 | `test_retirement.py`、`test_retirement_state.py` | 已通过 |
| API / OpenAPI | 5.8 | `test_operating_api.py`、`test_phase5_openapi.py`、`test_operating_export.py`、`test_operating_query_permissions.py` | 已通过 |
| 前端工作台 | 5.9 | `frontend/src/modules/operations/*.spec.ts` | 已通过：14 Vitest |
| E2E 双主链 | 5.10 | `tests/e2e/operations-iteration-retirement.spec.ts` | 已通过：3 Playwright |

## API / OpenAPI

| 场景 | 证据 | 状态 |
|---|---|---|
| TRD 04 第14节路径 + 配置/执行入口 | `test_phase5_openapi.py`；`backend/openapi/schema.yaml` | 已通过 |
| 生成类型 `schema.d.ts` | `npm.cmd run api:generate` | 已通过 |
| 权限默认拒绝、404 风格、导出独立判权 | `test_operating_query_permissions.py` / `test_operating_export.py` | 已通过 |

## 前端

| 场景 | 证据 | 状态 |
|---|---|---|
| 批次 / 看板 / 风险 / 议题 / 退市 | `frontend/src/modules/operations/*` | 已通过 |
| 产品详情运营入口、todo 深链 | `ProductDetailView.vue`、`TodoListView.vue`、router | 已通过 |

## E2E

| 场景 | 证据 | 状态 |
|---|---|---|
| 老品运营 → 迭代 DRAFT | `operations-iteration-retirement.spec.ts` 主链一 | 已通过 |
| 老品运营 → 退市批准与执行 | 同上主链二 | 已通过 |
| 失败/权限：坏批次、未授权导出、同人双步骤 | 同上 + 主链二 | 已通过 |

## 门禁纳入

| 检查 | 结果 | 日期 |
|---|---|---|
| Playwright `operations-iteration-retirement.spec.ts` | **3 passed**（单独复验） | 2026-07-21 |
| Playwright 全量（`workers: 1`） | **19 passed** | 2026-07-21 |
| `scripts\verify-trd.ps1` | pass（92 requirements / 4 gates） | 2026-07-21 |
| `scripts\check.ps1` 全量 | 初验 tip `5c16ff8` 曾通过，但 Spec/Standards P1 未覆盖 → **NO-GO**；remediation 后待复验 | 2026-07-22 |
| 0010 → 0011 真实升级 + 唯一约束拒绝重复 ACTIVE | **passed**：`test_role_assignment_migration_0011.py`，纳入 focused / 全量 MySQL pytest | 2026-07-29 |
| 角色撤销后下一次授权立即拒绝 | **passed**：`test_deactivated_role_is_denied_on_next_authorization_request`，纳入 focused / 全量 MySQL pytest | 2026-07-29 |
| 空库 migrate + `seed_e2e_user` 重复执行 | **passed**：隔离临时 MySQL 数据库；11 条规范化角色分配，7 组关键资产逐行不变，范围键严格匹配，结束后删除临时库 | 2026-07-29 |
| 临时库所有权与失败清理 | **passed**：`test_create_failure_never_drops_database_not_owned_by_verifier` 证明 CREATE 失败不执行 DROP | 2026-07-29 |
| Focused MySQL pytest | **30 passed in 43.41s**（本轮实际执行） | 2026-07-29 |
| `scripts\check.cmd` 全量 | **All quality gates passed**；MySQL **487**、Vitest **59**、Playwright **19**、OpenAPI / Docker / legacy 均通过 | 2026-07-29 |
| `scripts\verify-trd.ps1` | pass（92 requirements / 4 gates，本轮实际执行） | 2026-07-29 |
