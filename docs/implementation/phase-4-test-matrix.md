# 阶段4 开发到首次上市 —— 测试矩阵

状态：进行中 / 尚未完成（2026-07-14 建立基线；`scripts\check.cmd` 复验通过：`All quality gates passed.`。EXE-001—014 与 API/前端/E2E 证据初始均为 `未实现`，随 Task 4.1—4.10 回填）

对应计划：`docs/superpowers/plans/2026-07-14-phase-4-development-first-launch.md`

对应 TRD：`docs/trd/03-development-launch-execution-trd.md`

对应阶段3检查点：`docs/implementation/phase-3-checkpoint.md`

> 状态取值：`未实现` / `进行中` / `已通过：<测试位置>` / `后置：<阶段>`。
>
> 每项证据列在实现前可为计划路径；闭合时改为真实测试位置与最近结果。

## EXE 需求追踪

| 需求 | 说明 | 领域 | 服务（计划） | 权限（计划） | API（计划） | 前端/E2E（计划） | 状态 |
|---|---|---|---|---|---|---|---|
| EXE-001 | 幂等项目初始化和模板快照 | projects / configuration | `InitializeProjectRuntime`；`CreateSnapshot` | 立项事务内调用；无独立公开写入口 | 经 `ApproveAndCreateProject` 间接触发 | 看板可见已初始化项目 | 未实现 |
| EXE-002 | D1—L3默认模板数据 | configuration / projects | 模板定义与发布校验；运行时展开 `ProjectStage` | 配置发布既有权限 | 查询阶段列表 | 工作台阶段视图 | 未实现 |
| EXE-003 | 责任模板、项目成员和唯一个人R | work_items / projects | `AssignTaskResponsible`；成员管理 | `member.manage`、`task.assign_department_member`；组长不能强占跨部门人员 | `POST .../members`、`POST .../tasks/{id}/assign` | 唯一人 R 分派控件 | 未实现 |
| EXE-004 | 任务状态、DAG依赖、计划和逾期扫描 | work_items | `TransitionTask`、`AddTaskDependency`；`scan_execution_overdue` | `task.create`、`task.update_own`；核心任务不可直接取消 | `GET/POST .../tasks`、`PATCH .../tasks/{id}` | 任务面板、逾期标红 | 未实现 |
| EXE-005 | 三层交付物和不可变修订 | work_items / documents | `CreateDeliverableRevision`；锁定 `DocumentVersion` | `deliverable.create`、`revision.submit`、`revision.download` | `GET/POST .../deliverables`、`POST .../revisions` | 交付物面板与修订链 | 未实现 |
| EXE-006 | 绑定具体修订的专业确认 | work_items | `SubmitRevisionForConfirmation`、`DecideProfessionalConfirmation` | `professional_confirmation.decide`、`confirmer.reassign` | 确认提交/通过/退回/改派端点 | 确认面板；新修订不继承旧确认 | 未实现 |
| EXE-007 | 阶段门提交快照、检查和统一结果 | stage_gates | `ValidateExecutionGate`、`SubmitExecutionGate`、`RecordNormalGateDecision` | `stage_gate.submit`、`normal_gate.decide` | validate / submissions / decision | 阶段门面板与阻塞项 | 未实现 |
| EXE-008 | ExecutionException及阶段处理策略 | projects | `RequestStageHandlingMode`、`ConfirmExecutionException` | `stage_handling.request`、`stage_handling.confirm`、`project_exception.confirm` | 阶段策略申请/确认端点 | 风险/例外视图 | 未实现 |
| EXE-009 | FIRST_LAUNCH重大阶段门 | stage_gates / projects | `RecordFirstLaunchDecision` | `first_launch.management_conclusion.record`、`first_launch.final_decision.record` | major-decision 端点 | 首次上市门页 | 未实现 |
| EXE-010 | PublishAndHandover | projects / products / operations | `PublishAndHandover` → `PublishProductChangeSet` + `InitializeMonitoringScope` | 终决人具备产品发布动作；总监可待修复重试 | 发布/交接与重试命令 | 待修复与运营交接反馈 | 未实现 |
| EXE-011 | PlanChange及资源升级 | projects | `ApplyPlanChange` | `plan_change.apply_minor`、`plan_change.confirm_important`、`plan.edit` | plan-changes 端点 | 计划调整入口 | 未实现 |
| EXE-012 | 异步逾期提醒和查询标红 | work_items / notifications | Celery `scan_execution_overdue`；查询派生标红 | 查询按对象身份过滤；写业务状态不变 | 任务/工作台查询字段 | 列表标红与待办深链 | 未实现 |
| EXE-013 | EmergencyExecution | projects | `CreateEmergencyExecution` | `emergency_execution.create`（非总监拒绝） | emergency-executions 端点 | 先执行后补确认入口 | 未实现 |
| EXE-014 | MigrationBaseline及当前阶段续跑 | projects | `ImportProjectMigrationBatch`、`ConfirmMigrationBaseline` | `project_migration.confirm` | project-migration-batches | 迁移确认（管理侧）；E2E 老品/在途续跑 | 未实现 |

## API / OpenAPI

| 场景 | 计划证据 | 状态 |
|---|---|---|
| 权限过滤查询与命令 API（Task 4.8） | `backend/tests/projects/test_workbench_permissions.py`、`backend/tests/api/test_phase4_openapi.py`；`backend/openapi/schema.yaml` | 未实现 |
| OpenAPI 与前端生成类型一致 | `frontend/src/api/generated/schema.d.ts`（禁手写重复契约） | 未实现 |

## 前端工作台

| 场景 | 计划证据 | 状态 |
|---|---|---|
| 生命周期看板与项目执行工作台（Task 4.9） | `frontend/src/modules/projects/*.spec.ts`（看板、工作台、任务、交付物、阶段门） | 未实现 |
| 首次上市门与待办深链 | `LaunchGate` 路由；`TodoListView` 深链回系统页 | 未实现 |

## E2E

| 场景 | 计划证据 | 状态 |
|---|---|---|
| 新品主链：立项→运行时→任务/修订/确认→普通门→FIRST_LAUNCH→发布→运营范围（Task 4.10） | `tests/e2e/development-first-launch.spec.ts` | 未实现 |
| 失败修复：缺确认阻断、发布待修复、同决定幂等重试 | 同上 | 未实现 |
| 老品策略与在途 D3 续跑；无权用户不能执行总监/老板动作 | 同上 | 未实现 |

## 基线门禁（Task 4.0）

| 检查 | 结果 | 日期 |
|---|---|---|
| `scripts\check.cmd` | 退出码 0；`All quality gates passed.`（含既有阶段0–3 回归，不含阶段4 EXE 新测） | 2026-07-14 |
