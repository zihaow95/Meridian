# 阶段2 提案到项目 —— 测试矩阵

状态：已通过（2026-07-09）

日期：2026-07-08（建立） / 2026-07-09（闭合）

对应计划：`docs/superpowers/plans/2026-07-08-phase-2-opportunity-to-project.md`

对应 PRD：`docs/prd/01-opportunity-case-project-prd.md`

对应 TRD：`docs/trd/01-opportunity-case-project-trd.md`

对应检查点：`docs/implementation/phase-2-checkpoint.md`

> 状态取值：`未实现` / `进行中` / `已通过：<测试位置>` / `后置：<阶段>`。

## OPP 需求追踪

| 需求 | 说明 | 计划证据位置 | 状态 |
|---|---|---|---|
| OPP-001 | 按人工配置的资格控制正式提案提交 | `backend/tests/opportunities/test_opportunity_permissions.py`, `test_submit_proposal.py` | 已通过：`test_opportunity_permissions.py`, `test_submit_proposal.py` |
| OPP-002 | 支持联合提案及成员协作 | `backend/tests/opportunities/test_submit_proposal.py`, `test_opportunity_api.py` | 已通过：`test_submit_proposal.py`, `test_opportunity_api.py` |
| OPP-003 | 支持个人/部门季度额度统计 | `backend/tests/opportunities/test_quota.py` | 已通过：`test_quota.py` |
| OPP-004 | 强制校验四项提案核心内容 | `backend/tests/opportunities/test_submit_proposal.py` | 已通过：`test_submit_proposal.py` |
| OPP-005 | 支持提案版本和撤回/退回 | `backend/tests/opportunities/test_opportunity_models.py`, `test_submit_proposal.py` | 已通过：`test_opportunity_models.py`, `test_submit_proposal.py` |
| OPP-006 | 支持提案进入立案重大阶段门 | `backend/tests/stage_gates/test_major_decision.py`, `test_proposal_to_case.py` | 已通过：`test_major_decision.py`, `test_proposal_to_case.py` |
| OPP-007 | 支持立案负责人和副组长任命 | `backend/tests/opportunities/test_candidate_assessment.py` | 已通过：`test_candidate_assessment.py` |
| OPP-008 | 支持立案评估任务和受控交付物 | `backend/tests/opportunities/test_candidate_assessment.py` | 已通过：`test_candidate_assessment.py` |
| OPP-009 | 支持立案进入立项重大阶段门 | `backend/tests/opportunities/test_case_to_project_review.py` | 已通过：`test_case_to_project_review.py` |
| OPP-010 | 立项通过后原子化创建项目和产品对象 | `backend/tests/opportunities/test_project_creation.py`, `backend/tests/projects/`, `backend/tests/products/` | 已通过：`test_project_creation.py`, `tests/projects/`, `tests/products/` |
| OPP-011 | 支持待补充、暂缓、Pass 和复议 | `backend/tests/opportunities/test_deferred_reconsideration.py`, `backend/tests/stage_gates/test_major_decision.py` | 已通过：`test_deferred_gate_decision_creates_active_defer_record`、`test_gate_decision_requires_management_and_final_permissions` |
| OPP-012 | 支持候选机会池季度回看 | `backend/tests/opportunities/test_deferred_reconsideration.py` | 已通过：`test_quarterly_update_trigger_updates_active_defer_record` |
| OPP-013 | 支持提案与项目多对多关系 | `backend/tests/opportunities/test_combine_split.py`, `test_project_creation.py` | 已通过：`test_combine_split.py`, `test_project_creation.py` |
| OPP-014 | 支持提案合并和拆分 | `backend/tests/opportunities/test_combine_split.py` | 已通过：`test_combine_split.py` |
| OPP-015 | 按阶段和身份控制内容、文件及导出权限 | `backend/tests/opportunities/test_opportunity_permissions.py`, `test_opportunity_api.py` | 已通过：`test_opportunity_permissions.py`, `test_opportunity_api.py` |

## GLB 需求追踪

| 需求 | 说明 | 计划证据位置 | 状态 |
|---|---|---|---|
| GLB-001 | 关键命令幂等、事务和唯一约束 | `backend/tests/opportunities/test_project_creation.py`, `test_quota.py`, `backend/tests/stage_gates/test_material_uniqueness.py` | 已通过：`test_project_creation.py`、`test_major_decision.py`、`test_material_uniqueness.py` |
| GLB-002 | 提案/立案/立项对象独立、来源关系可追溯 | `backend/tests/opportunities/test_project_creation.py`, `test_combine_split.py` | 已通过：`test_project_creation.py`, `test_combine_split.py` |
| GLB-003 | 生命周期看板统一展示机会与项目 | `backend/tests/acceptance/test_opportunity_to_project.py`, `tests/e2e/opportunity-to-project.spec.ts` | 已通过：`test_opportunity_to_project.py`, `opportunity-to-project.spec.ts` |

## 阶段2验收

- 后端验收链路：`backend/tests/acceptance/test_opportunity_to_project.py`（128 项后端测试全量通过时一并执行）
- E2E 真实前后端链路：`tests/e2e/opportunity-to-project.spec.ts`（`scripts/check.ps1` 与 CI `e2e` job）
- 前端单元：`frontend/src/modules/opportunities/*.spec.ts`、`frontend/src/modules/stage-gates/MajorGateDecisionView.spec.ts`

## 延后验收说明

- 真实钉钉企业登录与通知投递：阶段6；阶段2沿用开发登录与假网关。
- 完整产品档案、SKU、渠道、营养与素材：阶段3；阶段2仅创建最小 `ProductDraft` 壳层。
- D1-L3 项目执行模板、`work_items`、任务依赖与交付物专业确认：阶段4；阶段2仅实现轻量 `CaseAssessment` 与受控文件引用。
