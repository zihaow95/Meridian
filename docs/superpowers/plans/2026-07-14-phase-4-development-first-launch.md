# Project Meridian 阶段4开发到首次上市实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从阶段3受控产品档案继续，交付 D1—L3 项目执行、任务与交付物、普通阶段门、`FIRST_LAUNCH`、产品发布和运营交接闭环，覆盖 EXE-001 至 EXE-014。

**Architecture:** 保持 Django 模块化单体。`projects` 管项目运行时、阶段与计划，新增 `work_items` 管任务、交付物和专业确认，`stage_gates` 管不可变提交与决策，`products` 继续作为产品发布唯一写入口；新增最小 `operations` 交接接口，只保存阶段5继续扩展所需的监控范围，不实现经营事实和风险规则。所有命令通过应用服务在 MySQL 事务中重新判权、写审计和 outbox。

**Tech Stack:** Python 3.13、Django 5.2、DRF 3.16、MySQL 8.0、Redis、Celery 5.6、Vue 3、TypeScript、Pinia、Element Plus、Vitest、Playwright、OpenAPI 3、Docker Compose。

**Status:** 已完成（GO，2026-07-20）；Docker 镜像构建已补跑通过

**Date:** 2026-07-14

## Global Constraints

- 正式根目录固定为 `D:\Projects\Meridian`；旧 Node/SQLite 原型不得成为依赖。
- 阶段3完成证据以 `docs/implementation/phase-3-checkpoint.md` 为准；执行前仍须在当前检出重新运行门禁。
- 项目当前组长是唯一 A；原子任务最多一个有效个人 R；数据库事实必须能阻止重复有效责任。
- D1—L3 和 `FIRST_LAUNCH` 语义固定；任务、周期、交付物、部门责任来自已发布配置快照，不硬编码专业模板。
- 文件对象必须 `StorageStatus.ACTIVE` 才能形成修订；文档版本沿 `DRAFT → SUBMITTED → LOCKED → CONTROLLED`，历史版本不覆盖。
- 项目、产品、阶段门、交付物、模板和决策保持独立身份；Redis/Celery/前端状态不是唯一业务事实。
- 写命令必须事务内重新判权；权限默认拒绝；平台管理权不等于业务数据访问权。
- 审计失败必须回滚关键操作；通知失败只保留可重试失败，不回滚已提交业务事实。
- 并发编辑使用 `version_no`；阶段门决策和发布使用行锁、幂等键及 MySQL 唯一约束。
- API 使用 `/api/v1`、UUID `public_id`、统一错误结构；关键状态只能走动作端点。
- OpenAPI 是前端类型来源；不得长期维护重复的手写 API 类型。
- 每个切片先写失败测试；MySQL、权限允许/拒绝、并发最终事实、审计和失败回滚均不得用 SQLite 或纯 mock 替代。

---

## 1. 当前代码基线与冲突裁决

- `ApproveAndCreateProject.execute()` 已在同一事务创建阶段门决策、`Project`、`ProductChangeSet`、成员、审计和 outbox。阶段4在该事务内调用新接口 `InitializeProjectRuntime.execute()`；不建立第二个项目创建入口。
- `projects.models` 仍是阶段2最小模型，缺少模板快照、阶段、`PUBLISH_PENDING_REPAIR` 和 `OPERATING`；保留现有表和公开字段，以追加迁移演进。
- `stage_gates.RecordMajorGateDecision` 绑定 Opportunity/ProjectCandidate 和机会配置。保留其阶段2行为，阶段4新增 `SubmitExecutionGate`、`RecordNormalGateDecision`、`RecordFirstLaunchDecision`，共享固定结果码但不塞入旧服务。
- 现有 `GateMaterialReference` 锁提案/立项主材料；阶段4新增归属于 `GateSubmission` 的材料引用，不改变阶段2历史引用语义。
- 配置快照复用 `CreateSnapshot(version, reference_type="project", reference_id=project.public_id)`；运行时只读 `ConfigurationSnapshot.content_copy`。
- 产品发布只调用 `PublishProductChangeSet.execute()`；`PublishAndHandover` 不直接写产品版本/SKU/渠道表。
- 当前没有 `work_items`、`operations` 后端应用和 `frontend/src/modules/projects/`。`operations` 本阶段只提供 `InitializeMonitoringScope`，阶段5再实现事实、指标、信号和议题。
- 当前工作区已有阶段3测试矩阵和产品前端用户改动；实施本计划不得覆盖或顺手格式化这些文件。

## 2. 完成定义

1. 立项批准在原事务中幂等展开已发布模板快照、D1—L3、任务、依赖、交付物和阶段门；失败不留下半初始化项目。
2. 任务支持唯一 R、依赖 DAG、状态、计划、逾期派生标记和乐观锁；核心任务不能直接取消。
3. 三层交付物、不可变修订和绑定具体修订的专业确认可运行；新修订不继承旧确认。
4. REUSE/SIMPLIFY/EXEMPT/NOT_APPLICABLE/PARALLEL、计划调整、资源升级和先执行后补确认按权限留痕。
5. 阶段门预检返回结构化阻塞项；每次提交锁定任务、交付物、确认、产品草稿、计划和材料版本快照。
6. 普通阶段门和 `FIRST_LAUNCH` 使用固定结果；首次上市同时保存经管会结论和老板最终决策，以老板结果迁移。
7. 批准后产品发布、最小运营范围、项目状态和 outbox 成功时原子提交；发布失败保留决策、有效档案不变并进入 `PUBLISH_PENDING_REPAIR`，同依据可幂等重试。
8. 在途项目从真实阶段继续，不补造历史阶段门或专业确认；重复外部项目标识不重复导入。
9. 项目列表/工作台/阶段/任务/交付物/确认/阶段门 API 权限过滤、分页、OpenAPI 和生成类型一致。
10. 生命周期看板、项目工作台、阶段门页和我的待办完成最小闭环；409、无权、阻塞项和重复提交有明确反馈。
11. EXE-001—014 测试矩阵、MySQL迁移、后端/前端测试、OpenAPI、build、阶段4 E2E、全量门禁和检查点均有真实证据。

## 3. 需求与任务映射

| 需求 | 任务 |
|---|---|
| EXE-001、EXE-002 | Task 4.1 |
| EXE-003、EXE-004 | Task 4.2 |
| EXE-005、EXE-006 | Task 4.3 |
| EXE-008、EXE-011、EXE-012、EXE-013 | Task 4.4 |
| EXE-007 | Task 4.5 |
| EXE-009、EXE-010 | Task 4.6 |
| EXE-014 | Task 4.7 |
| API/OpenAPI | Task 4.8 |
| 前端 | Task 4.9 |
| E2E与退出证据 | Task 4.10 |

## 4. 文件与迁移顺序

- `backend/apps/projects/models.py`：追加模板快照、项目阶段、例外、计划变更、应急执行和迁移基线；不拆现有模型文件。
- `backend/apps/projects/services/`：初始化、阶段策略、计划变更、应急执行和在途迁移命令。
- `backend/apps/work_items/`：新应用，拥有任务、依赖、交付物、修订、专业确认、命令、查询、策略和 API。
- `backend/apps/stage_gates/`：扩展项目主体；新增提交、提交材料引用、普通/首次上市决策及验证服务。
- `backend/apps/operations/`：仅 `MonitoringScope` 与 `InitializeMonitoringScope`。
- `backend/apps/authorization/actions.py`、`migrations/0007_seed_execution_actions.py`：在首个受保护命令前一次性登记 TRD 03 第16节动作。
- `backend/config/settings/base.py`、`backend/config/urls.py`：注册 `work_items`、`operations` 和 API 开关。
- `frontend/src/modules/projects/`：store、看板、工作台、任务、交付物、阶段门组件及 Vitest。
- `tests/e2e/development-first-launch.spec.ts`：新品主链和失败修复链。
- 迁移按 `configuration 0002 → projects 0004 → authorization 0007 → work_items 0001/0002 → projects 0005/0006 → stage_gates 0003 → operations 0001` 执行；禁止形成跨应用循环依赖。

## 5. PR 拆分

| PR | 范围 | 独立验收结果 |
|---|---|---|
| PR1 | Task 4.0—4.2 | 模板快照、运行时初始化、任务和唯一 R |
| PR2 | Task 4.3—4.4 | 交付物/确认、策略、调整和逾期 |
| PR3 | Task 4.5—4.6 | 提交快照、普通门、首次上市和交接 |
| PR4 | Task 4.7—4.8 | 在途迁移、查询 API、OpenAPI |
| PR5 | Task 4.9—4.10 | 前端闭环、E2E和退出证据 |

## 6. Task 4.0：建立阶段4执行基线

**Files:** Create `docs/implementation/phase-4-test-matrix.md`; Modify `docs/development/01-phased-implementation-plan.md`.

**Interfaces:** Consumes `phase-3-checkpoint.md` and `scripts\check.cmd`; produces EXE-001—014 evidence matrix.

- [ ] 在不覆盖现有用户改动的前提下确认基线；工作区不干净时先分离用户改动，不执行 reset/checkout。
- [ ] 运行 `scripts\check.cmd`；预期退出码0和 `All quality gates passed.`。失败即记录阻塞，不带病声明阶段4基线通过。
- [ ] 创建测试矩阵，每项列出领域、服务、权限、API、前端/E2E证据，初始状态 `未实现`。
- [ ] 在主计划阶段4链接本计划和矩阵，不提前标记完成。
- [ ] 提交：`git commit -m "docs: establish phase 4 execution baseline"`。

## 7. Task 4.1：模板快照和项目运行时原子初始化

**Files:** Modify `backend/apps/configuration/schema_registry.py`, `backend/apps/projects/models.py`, `backend/apps/projects/services/create_project_from_candidate.py`; Create `backend/apps/configuration/migrations/0002_seed_project_template_definition.py`, `backend/apps/configuration/defaults/project_template_v1.json`, `backend/apps/projects/migrations/0004_project_runtime.py`, `backend/apps/projects/services/initialize_runtime.py`, `backend/tests/projects/test_runtime_initialization.py`.

**Interfaces:** `InitializeProjectRuntime(context, project, template_version).execute() -> ProjectRuntimeResult(snapshot, stages, gates)`；只由 `ApproveAndCreateProject` 在现有事务内调用。

- [ ] 先写 MySQL 测试：D1—L3存在、L2=`FIRST_LAUNCH`、快照隔离、重复调用返回同一运行时、任一步异常使项目/草稿/阶段整体回滚。
- [ ] 运行 `cd backend; uv run pytest tests/projects/test_runtime_initialization.py -q`；预期因模型/服务不存在失败。
- [ ] 增量实现 `ProjectTemplateSnapshot`、`ProjectStage`、项目状态和时间字段；登记 `PROJECT_EXECUTION_TEMPLATE` 配置定义和可由现有配置发布服务导入的 V1 JSON；发布校验阶段代码唯一、依赖引用存在且 D1—L3/L2不可删除。
- [ ] 在 `_create_members/_create_opportunity_sources` 后、候选状态提交前调用初始化服务；服务使用 `CreateSnapshot`，展开运行表并登记 `project.initialized` 审计/outbox。
- [ ] 运行迁移漂移、空库迁移和目标测试；预期无漂移、测试通过。
- [ ] 提交：`git commit -m "feat: initialize project runtime from template snapshot"`。

## 8. Task 4.2：任务、依赖和唯一个人R

**Files:** Create `backend/apps/authorization/migrations/0007_seed_execution_actions.py`, `backend/apps/work_items/__init__.py`, `backend/apps/work_items/apps.py`, `backend/apps/work_items/models.py`, `backend/apps/work_items/errors.py`, `backend/apps/work_items/services/manage_tasks.py`, `backend/apps/work_items/policies/identity_provider.py`, `backend/apps/work_items/migrations/__init__.py`, `backend/apps/work_items/migrations/0001_initial.py`, `backend/tests/work_items/test_tasks.py`, `backend/tests/work_items/test_task_permissions.py`, `backend/tests/work_items/test_task_concurrency.py`; Modify `backend/apps/authorization/actions.py`, `backend/config/settings/base.py` and `backend/apps/projects/services/initialize_runtime.py`.

**Interfaces:** `AssignTaskResponsible(context, task_public_id, user_public_id, version_no)`、`TransitionTask(context, task_public_id, target_status, version_no)`、`AddTaskDependency(...)`；返回更新后的 `Task`。

动作目录固定登记：`project.read`、`plan.edit`、`member.manage`、`task.create`、`task.assign_department_member`、`task.update_own`、`deliverable.create`、`revision.submit`、`revision.download`、`professional_confirmation.decide`、`confirmer.reassign`、`stage_handling.request`、`stage_handling.confirm`、`stage_gate.submit`、`normal_gate.decide`、`first_launch.management_conclusion.record`、`first_launch.final_decision.record`、`project_exception.confirm`、`plan_change.apply_minor`、`plan_change.confirm_important`、`emergency_execution.create`、`project_migration.confirm`。

- [ ] 先写测试：一个任务最多一个R、只有执行部门负责人可分派、项目组长不能强占跨部门人员、停用R派生待分派、强依赖阻止启动、依赖环拒绝、核心任务不能取消、旧 `version_no` 返回409。
- [ ] 运行 work_items 测试；预期导入应用失败。
- [ ] 先登记完整阶段4动作目录，再实现任务/依赖模型、MySQL唯一约束和 DAG 检查；初始化服务从快照展开任务，A始终实时取 `Project.leader`。
- [ ] 每个命令事务内 `authorize()`，写审计/outbox；注册对象身份 provider，不通过前端隐藏代替后端拒绝。
- [ ] 用两个独立连接验证并发改任务只有一个成功，并查询最终版本号、R和审计数量。
- [ ] 提交：`git commit -m "feat: add project tasks and accountable assignment"`。

## 9. Task 4.3：交付物修订和专业确认

**Files:** Modify `backend/apps/work_items/models.py`; Create `backend/apps/work_items/migrations/0002_deliverables.py`, `backend/apps/work_items/services/deliverables.py`, `backend/apps/work_items/services/professional_confirmations.py`, `backend/tests/work_items/test_deliverables.py`, `backend/tests/work_items/test_professional_confirmations.py`.

**Interfaces:** `CreateDeliverableRevision(..., document_version_public_id)`, `SubmitRevisionForConfirmation(...)`, `DecideProfessionalConfirmation(..., decision, comment)`；均绑定具体修订与内容哈希。

- [ ] 先写测试：三层删除规则、核心交付物只能有效豁免、文件对象非ACTIVE拒绝、修订号唯一递增、提交后锁定、新修订不继承确认、无权确认拒绝、审计失败整体回滚。
- [ ] 运行目标测试；预期模型/命令不存在失败。
- [ ] 实现 Deliverable/Revision/ProfessionalConfirmation；引用现有 `DocumentVersion`，不复制文件二进制或更新历史行。
- [ ] 确认通过/退回仅迁移当前修订；新修订把旧确认标为 `SUPERSEDED` 但不删除。
- [ ] 运行文件回归和 work_items 测试；预期历史文件下载/版本链不退化。
- [ ] 提交：`git commit -m "feat: add controlled deliverables and confirmations"`。

## 10. Task 4.4：阶段策略、计划调整、逾期和先执行后补确认

**Files:** Modify `backend/apps/projects/models.py`; Create `backend/apps/projects/migrations/0005_execution_controls.py`, `backend/apps/projects/services/exceptions.py`, `backend/apps/projects/services/plan_changes.py`, `backend/apps/projects/services/emergency_execution.py`, `backend/apps/work_items/tasks.py`, `backend/tests/projects/test_execution_controls.py`, `backend/tests/work_items/test_overdue.py`.

**Interfaces:** `RequestStageHandlingMode`、`ConfirmExecutionException`、`ApplyPlanChange`、`CreateEmergencyExecution`；`scan_execution_overdue(now)` 只发事件/待办。

- [ ] 先写测试：REUSE/SIMPLIFY/PARALLEL需产品总监确认，EXEMPT可升级，不适用只来自快照；策略变化不删记录并重算阻塞项；MINOR组长生效，IMPORTANT需总监；非总监不能先执行；逾期不改业务状态。
- [ ] 运行目标测试；预期失败。
- [ ] 实现 ExecutionException/PlanChange/EmergencyExecution 和服务；前后值、依据、资格快照、截止时间及状态完整审计。
- [ ] 定时任务只传ID并重读MySQL，幂等产生 todo/outbox；Redis丢失后可从 outbox 恢复。
- [ ] 运行项目、通知、outbox目标回归；预期通过且无重复待办。
- [ ] 提交：`git commit -m "feat: govern execution exceptions and schedule changes"`。

## 11. Task 4.5：阶段门预检、不可变提交和普通决策

**Files:** Modify `backend/apps/stage_gates/models.py`, `backend/apps/stage_gates/errors.py`; Create `backend/apps/stage_gates/migrations/0003_execution_submissions.py`, `backend/apps/stage_gates/services/validate_execution_gate.py`, `backend/apps/stage_gates/services/submit_execution_gate.py`, `backend/apps/stage_gates/services/record_normal_decision.py`, `backend/tests/stage_gates/test_execution_submission.py`, `backend/tests/stage_gates/test_normal_decision.py`, `backend/tests/stage_gates/test_execution_gate_concurrency.py`.

**Interfaces:** `ValidateExecutionGate(...).execute() -> GateValidationResult(blocks, warnings)`；`SubmitExecutionGate(..., idempotency_key) -> GateSubmission`；`RecordNormalGateDecision(...) -> GateDecision`。

- [ ] 先写测试覆盖 TRD 03 第10节全部阻塞项、提交版本递增、材料引用锁定、后续新修订不污染旧提交、待补充创建新提交、带例外通过仅总监、两个并发决策只有一个数据库事实。
- [ ] 运行目标测试；预期提交模型和服务不存在失败。
- [ ] 扩展项目主体和执行门状态；新增 GateSubmission/GateSubmissionMaterialReference/GateDecision，保留阶段2 `MajorGateDecision` 与旧服务行为。
- [ ] 通过查询接口收集任务/确认/草稿/文件事实，保存不可变 JSON 摘要、UUID引用和内容哈希；API层不得拼多表快照。
- [ ] 运行阶段2重大门回归和阶段4目标测试；预期两者通过。
- [ ] 提交：`git commit -m "feat: add immutable execution gate submissions"`。

## 12. Task 4.6：FIRST_LAUNCH、产品发布和运营交接

**Files:** Create `backend/apps/stage_gates/services/record_first_launch_decision.py`, `backend/apps/projects/services/publish_and_handover.py`, `backend/apps/operations/__init__.py`, `backend/apps/operations/apps.py`, `backend/apps/operations/models.py`, `backend/apps/operations/services/initialize_monitoring_scope.py`, `backend/apps/operations/migrations/__init__.py`, `backend/apps/operations/migrations/0001_initial.py`, `backend/tests/projects/test_launch_handover.py`, `backend/tests/stage_gates/test_first_launch.py`; Modify `backend/config/settings/base.py`.

**Interfaces:** `RecordFirstLaunchDecision(...) -> FirstLaunchDecisionResult`；`PublishAndHandover(context, project_public_id, decision_public_id, idempotency_key).execute() -> HandoverResult`；内部只调用 `PublishProductChangeSet` 和 `InitializeMonitoringScope`。

- [ ] 先写测试：L2固定 `FIRST_LAUNCH`、经管会结论必填、老板决定必填且最终权威、材料锁定、非批准不发布、成功时版本/监控范围/项目OPERATING/outbox原子、重复调用不重复创建。
- [ ] 写失败测试：产品发布异常时阶段门决定保留、有效档案不变、无运营范围、项目为 `PUBLISH_PENDING_REPAIR`；同一决定修复重试成功。
- [ ] 实现项目专用决策服务，不扩张机会配置服务；批准决定提交后调用 handover，使用产品公开发布服务；角色配置必须让首次上市最终决策人具备对应产品发布动作，并让产品总监具备待修复重试动作，不能通过内部绕权参数跳过授权。
- [ ] 对 `ValidationFailedError` 和 `ProductPublicationFailed` 利用内层 savepoint 回滚产品写入，外层保存决定和待修复状态；事务提交后再返回稳定 `PRODUCT_PUBLICATION_FAILED`，重试使用 `decision_public_id + change_set_public_id` 联合幂等键。
- [ ] `operations` 只保存项目、产品版本、实际生效时间、责任人和状态；不实现阶段5指标/事实/信号。
- [ ] 运行产品发布回归、首次上市和并发测试；预期通过。
- [ ] 提交：`git commit -m "feat: publish approved launch and hand over operations"`。

## 13. Task 4.7：在途项目迁移和真实阶段续跑

**Files:** Modify `backend/apps/projects/models.py`; Create `backend/apps/projects/migrations/0006_migration_baseline.py`, `backend/apps/projects/services/import_migration_baseline.py`, `backend/apps/projects/api/migrations.py`, `backend/tests/projects/test_inflight_migration.py`, `backend/tests/projects/test_migration_api.py`.

**Interfaces:** `ImportProjectMigrationBatch`、`ConfirmMigrationBaseline`；外部项目标识 + 批次键幂等，`CONTINUE` 或 `ARCHIVE_ONLY`。

- [ ] 先写测试：D3继续只创建D3及后续运行项、历史任务/文件标记来源、不生成D1/D2门和专业确认、未确认不能续跑、重复批次不重复、失败无半成品、ARCHIVE_ONLY不产生待办。
- [ ] 运行目标测试；预期失败。
- [ ] 实现 MigrationBatch/MigrationBaseline/历史引用和确认服务；历史决策只保存摘要，不伪造操作者或时间。
- [ ] API采用分批校验和结构化行错误；确认动作事务内判 `project_migration.confirm`、写审计/outbox。
- [ ] 执行一次全量模拟导入和同批次增量重跑，核对源行数、正式行数和错误数。
- [ ] 提交：`git commit -m "feat: migrate in-flight projects from their real stage"`。

## 14. Task 4.8：权限过滤查询、命令 API 和 OpenAPI

**Files:** Modify `backend/config/urls.py`, `backend/apps/projects/api/urls.py`, `backend/apps/stage_gates/api/urls.py`, `backend/openapi/schema.yaml`; Create `backend/apps/projects/queries/workbench.py`, `backend/apps/projects/api/workbench.py`, `backend/apps/work_items/api/urls.py`, `backend/apps/work_items/api/tasks.py`, `backend/apps/work_items/api/deliverables.py`, `backend/apps/stage_gates/api/execution.py`, `backend/tests/api/test_phase4_openapi.py`, `backend/tests/projects/test_workbench_permissions.py`.

**Interfaces:** 精确提供 `GET /api/v1/projects`、`GET /api/v1/projects/{id}`、`GET /api/v1/projects/{id}/stages`、`POST /api/v1/projects/{id}/members`、`GET/POST /api/v1/projects/{id}/tasks`、`PATCH /api/v1/tasks/{id}`、`POST /api/v1/tasks/{id}/assign`、`GET/POST /api/v1/projects/{id}/deliverables`、`POST /api/v1/deliverables/{id}/revisions`、确认提交/通过/退回、阶段策略申请、阶段门 validate/submissions/decision/major-decision、plan-changes、emergency-executions 和 project-migration-batches；列表分页稳定排序，命令只调用 Task 4.1—4.7 服务。

- [ ] 先写 API/权限测试：无对象身份默认拒绝、项目成员不可看其他项目、任务R只能改本人任务、确认人只能处理指定修订、平台管理员不能读取敏感材料、拒绝不泄露存在性。
- [ ] 运行 API 测试；预期404/未注册端点失败。
- [ ] 注册 URLs 并复用 Task 4.2 已登记的动作与对象身份；为请求/响应/409/业务错误补 `extend_schema`，项目列表/工作台由查询服务做权限过滤。
- [ ] 生成 `backend/openapi/schema.yaml`，运行 `frontend npm.cmd run api:generate`；提交生成的 `schema.d.ts`，禁止手写重复契约类型。
- [ ] 运行 OpenAPI 漂移、API、权限和审计测试；预期通过。
- [ ] 提交：`git commit -m "feat: expose governed project execution APIs"`。

## 15. Task 4.9：生命周期看板和项目执行工作台

**Files:** Create `frontend/src/modules/projects/store.ts`, `frontend/src/modules/projects/LifecycleBoardView.vue`, `frontend/src/modules/projects/LifecycleBoardView.spec.ts`, `frontend/src/modules/projects/ProjectWorkbenchView.vue`, `frontend/src/modules/projects/ProjectWorkbenchView.spec.ts`, `frontend/src/modules/projects/TaskPanel.vue`, `frontend/src/modules/projects/TaskPanel.spec.ts`, `frontend/src/modules/projects/DeliverablePanel.vue`, `frontend/src/modules/projects/DeliverablePanel.spec.ts`, `frontend/src/modules/projects/StageGatePanel.vue`, `frontend/src/modules/projects/StageGatePanel.spec.ts`; Modify `frontend/src/router/index.ts` and `frontend/src/modules/todos/TodoListView.vue`.

**Interfaces:** 仅使用生成的 `components['schemas'][...]` 和 Task 4.8 API；store按项目域组织，不缓存敏感正文。

- [ ] 先写 Vitest：筛选分页、唯一R分派、任务409提示、修订确认、新版本确认失效、阶段门阻塞项、按钮防重、无权动作隐藏但仍处理403、待修复发布状态。
- [ ] 运行 `cd frontend; npm.cmd run test:unit -- --run src/modules/projects`；预期组件不存在失败。
- [ ] 实现看板和工作台标签：概览、阶段、任务、交付物、产品草稿、确认、阶段门、风险/例外、文件/审计；命令完成后重新拉取权威状态。
- [ ] 增加 `/projects/:publicId` 和 `/projects/:publicId/launch-gate` 路由；todo深链接回系统页面并重新判权。
- [ ] 运行 lint、format check、typecheck、项目单测和 build；预期全部通过。
- [ ] 提交：`git commit -m "feat: add project execution workbench"`。

## 16. Task 4.10：阶段4 E2E、全量门禁和退出证据

**Files:** Create `tests/e2e/development-first-launch.spec.ts`, `docs/implementation/phase-4-checkpoint.md`; Modify `phase-4-test-matrix.md`, `scripts/check.ps1`, `README.md`, phased plan.

**Interfaces:** Playwright走真实API/MySQL；检查点只记录本轮实际证据。

- [ ] E2E覆盖新品：立项→运行时→任务/修订/确认→普通门→FIRST_LAUNCH→产品发布→运营范围；断言数据库可观察结果而非只看页面文字。
- [ ] E2E覆盖失败修复：缺确认阻止提交；发布失败显示待修复；按同决定重试后只生成一个产品版本和运营范围。
- [ ] E2E覆盖老品策略和在途D3续跑，不伪造历史门；权限用户不能执行总监/老板动作。
- [ ] 更新 `scripts/check.ps1` 纳入新E2E后运行 `scripts\check.cmd`；预期 `All quality gates passed.` 且无跳过/xfail。
- [ ] 运行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-trd.ps1`；预期92项需求、4个重大阶段门仍通过。
- [ ] 更新测试矩阵为真实测试路径和最近结果；检查点记录提交哈希、迁移、pytest/Vitest/Playwright数量、OpenAPI漂移、镜像和阻塞项。
- [ ] 仅在上述证据均满足后更新 README 和主计划为“阶段4已完成，阶段5尚未开始”。
- [ ] 提交：`git commit -m "docs: record phase 4 completion evidence"`。

## 17. 明确不实现

- 不建设通用BPM/低代码流程设计器、自动排程引擎或资源优化器。
- 不实现阶段5经营事实、指标计算、风险信号、经营议题、迭代提案和退市。
- 不把钉钉通知成功当业务成功，不在钉钉内迁移状态。
- 不自动冻结、处罚或回滚逾期/先执行事项。
- 不重构阶段2机会重大门服务，不拆分现有产品大模型文件作为顺手清理。

## 18. 停线条件与自检

- 默认模板缺少 D1—L3、L2不是 `FIRST_LAUNCH`、唯一A/R无法由MySQL事实保障：停线并回到设计/迁移评审。
- 调用产品发布需要跨模块直接写模型、或运营交接只能异步最终一致：停线，修正公开应用服务/事务边界。
- MySQL迁移不能从空库和阶段3库两条路径成功：不得进入API/前端任务。
- 任一权限拒绝、审计失败回滚、并发最终事实、OpenAPI漂移或E2E主链无证据：不得宣布阶段完成。
- 覆盖自检：EXE-001—014均映射；无待填内容或模糊后续项；所有新接口在首次消费前定义；阶段2/3公开服务保持兼容。
