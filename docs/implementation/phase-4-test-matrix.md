# 阶段4 开发到首次上市 —— 测试矩阵

状态：第十三轮 NO-GO（相对 `b147eb0`）已本地修复：ARCHIVE_ONLY 锁内重读历史列表 + 同键并发唯一事实（Barrier）。域内 `test_inflight_migration` 26 passed；全量门禁/Docker 本切片未重跑。

对应计划：`docs/superpowers/plans/2026-07-14-phase-4-development-first-launch.md`

对应 TRD：`docs/trd/03-development-launch-execution-trd.md`

对应阶段4检查点：`docs/implementation/phase-4-checkpoint.md`

> 状态取值：`未实现` / `进行中` / `已通过：<测试位置>` / `后置：<阶段>`。
> 「已通过」指该场景在既有提交中有对应自动化覆盖；**不等于**本轮修复切片已重跑全量门禁。

## EXE 需求追踪

| 需求 | 说明 | 领域 | 服务 | 权限 | API | 前端/E2E | 状态 |
|---|---|---|---|---|---|---|---|
| EXE-001 | 幂等项目初始化和模板快照 | projects / configuration | `InitializeProjectRuntime` | 立项事务内 | 经 `ApproveAndCreateProject` | 看板可见 | 已通过：`test_initialize_runtime` + E2E 新品阶段列表 |
| EXE-002 | D1—L3默认模板数据 | configuration / projects | 模板校验与展开 | 配置发布 | `GET .../stages` | 工作台阶段 | 已通过：`seed_e2e_user` + E2E stages == D1–L3 |
| EXE-003 | 责任模板、成员和唯一人 R | work_items / projects | `AssignTaskResponsible` | `task.assign_department_member` | assign API | TaskPanel | 已通过：`test_tasks` + TaskPanel Vitest |
| EXE-004 | 任务状态、DAG、逾期 | work_items | `TransitionTask`、`scan_execution_overdue` | task.* | tasks API | 任务面板 | 已通过：`test_tasks` / `test_overdue` |
| EXE-005 | 三层交付物和不可变修订 | work_items | `CreateDeliverableRevision` | deliverable.* | revisions API | DeliverablePanel | 已通过：`test_deliverables` + Vitest |
| EXE-006 | 修订绑定专业确认 | work_items | `DecideProfessionalConfirmation` | professional_confirmation.* | decide API | DeliverablePanel | 已通过：`test_professional_confirmations` |
| EXE-007 | 阶段门提交与决策 | stage_gates | Validate/Submit/RecordNormal | stage_gate.* | validate/submissions/decision | StageGatePanel | 已通过：`test_execution_submission` + E2E 409 阻断 |
| EXE-008 | ExecutionException | projects | Request/Confirm | stage_handling.* | handling API | 例外入口 | 已通过：`test_execution_controls` |
| EXE-009 | FIRST_LAUNCH | stage_gates | `RecordFirstLaunchDecision` | first_launch.* | first-launch-decision | launch-gate | 已通过：`test_first_launch` + E2E |
| EXE-010 | PublishAndHandover | projects / products / operations | `PublishAndHandover` | product.publish_* | via first-launch | 待修复横幅 | 已通过：`test_launch_handover` + E2E OPERATING/REPAIR |
| EXE-011 | PlanChange | projects | `ApplyPlanChange` | plan_change.* | plan-changes | — | 已通过：`test_execution_controls` |
| EXE-012 | 逾期提醒 | work_items | Celery scan | 查询过滤 | tasks | — | 已通过：`test_overdue` |
| EXE-013 | EmergencyExecution | projects | `CreateEmergencyExecution` | emergency_execution.create | emergency-executions | — | 已通过：`test_execution_controls` + E2E 拒绝 |
| EXE-014 | MigrationBaseline | projects | Import/Confirm + stream stage | project_migration.confirm | migration files/stage + batches | DeliverablePanel 下载 | 已通过：`test_inflight_migration`（锁内重读 / 同键并发唯一事实 / 中途失败 consume）+ E2E D3/ARCHIVE |

## API / OpenAPI

| 场景 | 证据 | 状态 |
|---|---|---|
| 权限过滤与命令 API | `test_workbench_permissions.py`、`test_phase4_openapi.py` | 已通过 |
| OpenAPI ↔ schema.d.ts | `frontend/src/api/generated/schema.d.ts` | 已通过（含 typed `MigrationBaselineConfirmHistoryFile.document_version_public_id`；本切片再生契约） |

## 前端工作台

| 场景 | 证据 | 状态 |
|---|---|---|
| 看板与工作台 | `frontend/src/modules/projects/*.spec.ts` | 已通过 |
| 交付物下载入口 | `DeliverablePanel.vue`（per-version `can_download` → download-ticket；无权隐藏 + 403） | 已通过：DeliverablePanel Vitest |
| 修订确认与冲突 | `DeliverablePanel.spec.ts`（submit / 409 DELIVERABLE_REVISION_CONFLICT） | 已通过 |
| 首次上市路由与 todo 深链 | `router/index.ts`；`TodoListView.vue` | 已通过 |

## E2E

| 场景 | 证据 | 状态 |
|---|---|---|
| 新品主链与运行时 | `tests/e2e/development-first-launch.spec.ts` | 已通过（本轮 Playwright 复跑） |
| 发布失败→待修复→按原决定重试→OPERATING（唯一版本/运营范围） | 同上（`retries=0`；每次种子经真实双人决策+失败发布；响应断言 `product_version_count`/`monitoring_scope_count` == 1） | 已通过（本轮 Playwright 复跑） |
| 在途 D3 与权限拒绝 | 同上 | 已通过（本轮 Playwright 复跑） |
| ARCHIVE_ONLY 归档下载 | 同上（confirm `history_files` → download-ticket） | 已通过（本轮 Playwright 复跑，16 passed） |

## 门禁纳入

| 检查 | 结果 | 日期 |
|---|---|---|
| `scripts\check.ps1` 含 `development-first-launch.spec.ts` | 本轮除 Docker Hub 拉镜像超时外全绿（pytest 317 / Playwright 16 / mypy 261）；Docker 步骤环境阻断 | 2026-07-20 |
