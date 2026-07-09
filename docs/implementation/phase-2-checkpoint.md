# 阶段2 提案到项目 —— 完成检查点

日期：2026-07-09

状态：已通过本地验收（Task 2.8/2.9 代码待合入提交）

对应计划：`docs/superpowers/plans/2026-07-08-phase-2-opportunity-to-project.md`

对应测试矩阵：`docs/implementation/phase-2-test-matrix.md`

分支：`codex/phase-2-opportunity-to-project`

## 已交付能力概览

- **提案工作流**：创建草稿、四项核心内容校验、提交/撤回、版本链、成员邀请、额度账（WARN 模式）
- **重大阶段门**：`PROPOSAL_TO_CASE`、`CASE_TO_PROJECT`；经管会结论与老板最终决策可差异记录
- **拟立项方案**：负责人任命、八类 `CaseAssessment`、提交立项评审、合并/拆分、来源重确认
- **暂缓/复议**：`DeferRecord`、季度回看、`Reconsideration`、候选机会池查询
- **原子立项**：`ApproveAndCreateProject` 同事务创建 `Project`、`ProductAsset`、`ProductDraft`、来源关系、审计与 outbox
- **前端最小闭环**：我的提案、新建/工作台、重大决策页、候选池、生命周期看板首版
- **验收**：`test_opportunity_to_project.py` 串联 API；Playwright `opportunity-to-project.spec.ts` 串联 UI + 阶段门

## 提交记录（阶段2 后端主线，截至文档日）

```text
fa784bb feat: create project and product draft atomically
7cc6133 feat: add deferred reconsideration and candidate source flows
6b06125 feat: add project candidate assessment workflow
b276bcd feat: add proposal major stage gate
36a3d6f feat: add proposal submission workflow
25e2393 feat: add opportunity object identity and rule configuration
353051b feat: add opportunity proposal and quota models
7a4b6b5 feat: add phase 2 opportunity authorization actions
5e77e47 docs: establish phase 2 execution baseline
```

待合入（工作区已验收、尚未提交）：

- Task 2.8：`feat: add opportunity workflow UI`（前端模块、路由、OpenAPI 类型）
- Task 2.9：`test: add phase 2 opportunity to project acceptance`（生命周期看板 API、验收测试、E2E、`check.ps1`）

## 阶段2 补救（2026-07-09）

审计发现的 P1/P2 缺口已在本轮闭合：

| 项 | 修复 | 证据 |
|---|---|---|
| P1 暂缓决策链路 | `RecordMajorGateDecision` 在 `DEFERRED` 时同事务创建 `DeferRecord`；要求 `defer_reason` 或 `restart_trigger` | `test_deferred_gate_decision_creates_active_defer_record` |
| P1 MySQL 唯一约束 | `open_material_key`、`project_id`（无条件唯一）、`active_role_key` 替代条件唯一 | 迁移 `stage_gates/0002`、`opportunities/0004`、`projects/0002`；`test_material_uniqueness.py` |
| P1 阶段门权限 | 同时校验 `major_gate.management_conclusion.record` 与 `major_gate.final_decision.record` | `test_gate_decision_requires_management_and_final_permissions` |
| P2 季度回看 UPDATE_TRIGGER | `_apply_action` 更新活动 `DeferRecord.restart_trigger` / `next_review_quarter` | `test_quarterly_update_trigger_updates_active_defer_record` |
| P2 OpenAPI（部分） | 生命周期看板、重大决策、暂缓池 API 补 `extend_schema` / inline serializer | `openapi/schema.yaml` 含 `LifecycleBoardPage`；前端 `schema.d.ts` 已再生成 |

**仍待后续**：其余阶段二 API（提案/候选 CRUD 等）的 serializer 推断警告（约 137 条）；`spectacular --validate` 尚未作为硬失败门禁。

## 数据库迁移（阶段2 新增）

| 应用 | 迁移 |
|---|---|
| `opportunities` | `0001_initial`, `0002_…`, `0003_…`, `0004_remove_projectcandidate_opportunities_candidate_project_uniq_and_more` |
| `stage_gates` | `0001_initial`, `0002_remove_stagegateinstance_stage_gates_active_material_uniq_and_more` |
| `projects` | `0001_initial`, `0002_remove_projectmember_projects_member_active_uniq_and_more` |
| `products` | `0001_initial`, `0002_initial` |

## 自动化证据（本轮实际运行）

```text
scripts/preflight.ps1                          — 通过
scripts/verify-trd.ps1                         — 通过（6 份 TRD、92 项需求、4 个重大阶段门）
backend: ruff / mypy / pytest (MySQL, 阶段2+补救) — 55+ passed（opportunities/stage_gates/acceptance/projects）
backend: OpenAPI spectacular --validate        — schema 已再生成；阶段二关键端点有响应体；全量 serializer 推断警告仍为非阻塞
frontend: eslint / vue-tsc / vitest            — 16 passed
tests/e2e/opportunity-to-project.spec.ts       — 通过（开发登录 + 两次阶段门 + 看板）
tests/e2e/platform-kernel.spec.ts              — 未在本轮重跑（仍由 check.ps1 覆盖）
scripts/check.ps1                              — 本轮未完整执行（耗时门禁；子项已分别验证）
```

CI：`.github/workflows/ci.yml`（push/PR 触发；阶段2 E2E 纳入 `e2e` job 后需在远端 PR 上确认绿构建）。

## 阶段退出条件核对

| 条件 | 结果 |
|---|---|
| 产品经理/部门负责人可提交真实提案 | 通过（`test_submit_proposal.py`、E2E 新建提案） |
| 两个重大阶段门可完成决策 | 通过（`test_proposal_to_case.py`、`test_case_to_project_review.py`、E2E） |
| 立项通过只创建一个项目和正确产品草稿 | 通过（`test_project_creation.py`、验收测试） |
| 权限、文件版本和审计可完整追溯 | 通过（权限/审计测试 + 关键命令 append_event） |
| OPP-001–OPP-015、GLB-001–GLB-003 有自动化证据 | 通过（见测试矩阵） |

## 已知限制 / 后置项

- **产品**：仅 `ProductAsset`/`ProductDraft` 壳层，无完整产品档案发布（阶段3）
- **项目执行**：无 D1-L3 模板、`work_items`、任务依赖与交付物专业确认（阶段4）
- **额度 API**：前端 `ProposalQuotaPanel` 为静态提示；`GET /proposal-quotas/current` 未实现
- **工作台**：成员、评估、文件、来源关系的完整 UI 为占位说明
- **钉钉**：开发登录 + 假网关；真实企业验收留阶段6
- **经营/上市/退市**：`FIRST_LAUNCH`、`PRODUCT_RETIREMENT`、经营看板留后续阶段

## 下一阶段边界（阶段3）

阶段3 目标：产品—版本—SKU—渠道统一主模型、受控产品档案发布、存量迁移。不得将阶段2 的 `ProductDraft` 壳层扩展为完整档案发布逻辑而不经过阶段3 设计评审。
