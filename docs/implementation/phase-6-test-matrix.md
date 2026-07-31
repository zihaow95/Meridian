# 阶段6 存量产品、受控文件、站内通知与试用准备 —— 测试矩阵

状态：**未开始实现** — 分支 `codex/phase-6-controlled-files-notifications-pilot-readiness`，基线提交 `a39414b`（阶段5 GO tip `41717b2` 的文档后继）。

对应范围：`docs/superpowers/specs/2026-07-30-phase-6-internal-pilot-scope.md`

对应计划：`docs/superpowers/plans/2026-07-30-phase-6-controlled-files-notifications-pilot-readiness.md`

对应 PRD：`docs/prd/02-product-information-management-prd.md`、`docs/prd/05-platform-foundation-prd.md`

对应 TRD：`docs/trd/02-product-information-management-trd.md`、`docs/trd/05-platform-foundation-trd.md`

对应检查点：`docs/implementation/phase-6-checkpoint.md`（Task 6.9 产出，尚未创建）

> 状态取值：`未实现` / `进行中` / `已通过：<测试位置>` / `后置：<阶段>` / `阻塞：<原因>`。
> 「已通过」必须对应本阶段6检出上的真实自动化证据，不得引用阶段5或更早的历史结果。

## 1. 阶段6基线（Task 6.0 本轮实际执行）

| 检查 | 命令 | 结果 | 日期 |
|---|---|---|---|
| 环境预检 | `scripts\preflight.cmd` | 通过（Git 2.54.0 / uv 0.11.26 / Python 3.13 / Node 24.17.0 / npm 11.13.0 / Docker 29.5.3 / Compose v5.1.4 / daemon 在线） | 2026-07-31 |
| 依赖服务 | `docker compose -f deploy/compose/compose.dev.yml --env-file .env ps` | mysql 与 redis 均 `healthy` | 2026-07-31 |
| 全量门禁 | `scripts\check.cmd` | **All quality gates passed**（退出码 0，24 步全通过）：后端 MySQL pytest **488 passed in 137.00s**、前端 Vitest **22 文件 / 59 用例**、Playwright **19 passed (50.7s)**、mypy 317 源文件无问题、迁移无漂移、OpenAPI 与生成类型无漂移、冷库种子 11 条规范化角色分配 / 7 组稳定资产、Docker 前后端镜像构建通过、旧原型引用扫描通过 | 2026-07-31 |
| 分支基线 | `git checkout -b codex/phase-6-...` | 从 `a39414b` 创建；工作区既有文档修改与未跟踪文件全部保留，未执行 reset/checkout 覆盖 | 2026-07-31 |

> `main` 落后当前基线 99 个提交（停在阶段2合并点），阶段3—5 均未合入 `main`；阶段6 分支不得从 `main` 创建。

## 2. 基线已知缺陷（阶段6必须修复）

| 编号 | 事实 | 证据 | 影响任务 | 状态 |
|---|---|---|---|---|
| B-1 | `identity_user_org_employee_no_uniq` 为条件唯一约束，MySQL 上未创建，同组织 `employee_no` 无数据库唯一性 | `scripts\check.cmd` 迁移阶段输出 `identity.User: (models.W036)`；`identity/models/user.py:79-83` | 6.7 前置 | 未实现 |
| B-2 | `notifications_todo_open_dedup_uniq` 同为条件唯一约束，MySQL 上未创建 | 同上输出 `notifications.Todo: (models.W036)`；`notifications/models.py:52-56` | 6.5 | 未实现 |
| B-3 | 配置发布无行锁也无唯一约束，靠应用层"查 PUBLISHED → 置 RETIRED" | `configuration/services/__init__.py:105-125` | 6.1 | 未实现 |
| B-4 | `AdminChangeRequest` 无 HTTP API、无生产调用方、`APPLIED` 从未被写入、`dual_control_enabled()` 无调用方 | `authorization/services/*`；唯一调用方 `backend/tests/authorization/test_dual_control.py` | 6.1 | 未实现 |
| B-5 | `documents` 未注册 `ObjectIdentityProvider`，版本列表只按 `organization_id` 过滤 | `documents/api/documents.py:53-56` | 6.2 | 未实现 |
| B-6 | `PublishLegacyBaseline` 绕过 `ValidateProductPublication`，只校验 `name` | `products/services/publish_legacy_baseline.py:91-93` | 6.4 | 未实现 |
| B-7 | `DeliverNotification` 把 `Notification.status` 写成 `DELIVERED`，投递状态未与通知状态解耦 | `notifications/services/notifications.py:112-113` | 6.5 | 未实现 |
| B-8 | `DingTalkNotificationGateway` 由 `DeliverNotification` 默认实例化，仅因 `DINGTALK_NOTIFIER` 未配置而抛 `RuntimeError`，无显式禁用开关 | `notifications/services/notifications.py:87`；`channels/dingtalk.py:19-20` | 6.5 | 未实现 |

## 3. 权限动作裁决

新增动作清单见计划第21节附录，统一由 `authorization/0013_seed_phase6_actions.py` 一次性登记，写入新建 `PHASE6_ACTIONS` 元组。

| 动作码 | 用途 | 允许证据 | 拒绝证据 | 状态 |
|---|---|---|---|---|
| `configuration.draft.create` | 创建关键配置草稿 | — | — | 未实现 |
| `configuration.publication.request` | 提交配置发布申请 | — | — | 未实现 |
| `configuration.publication.review` | 复核配置发布申请（申请人不可自审） | — | — | 未实现 |
| `configuration.content.read_sensitive` | 查看敏感配置正文 | — | — | 未实现 |
| `legacy_material.submission.create` | 提交历史资料进入待整理区 | — | — | 未实现 |
| `legacy_material.submission.read` | 查看待整理资料与来源证据 | — | — | 未实现 |
| `legacy_material.submission.verify` | 验证来源顺序效力并转正 | — | — | 未实现 |
| `product_material.manage` | 维护材料关联与历史版本链 | — | — | 未实现 |
| `product_material.confirm` | 专业确认或退回具体文件版本 | — | — | 未实现 |
| `product_material.completeness.read` | 读取材料完整性预检结果 | — | — | 未实现 |
| `legacy_baseline.draft.create` | 逐一表单创建老品基线草稿 | — | — | 未实现 |
| `notification.message.read` | 读取本人站内通知 | — | — | 未实现 |
| `notification.message.mark_read` | 标记本人通知已读 | — | — | 未实现 |
| `notification.message.close` | 关闭本人通知 | — | — | 未实现 |
| `identity.pilot_account.provision` | 预置试用临时账号 | — | — | 未实现 |
| `pilot.batch.manage` / `pilot.batch.read` | 试用批次管理与查看 | — | — | 未实现 |
| `pilot.feedback.create` / `.read` / `.assign` / `.handle` / `.retest` / `.close` | 反馈闭环六动作 | — | — | 未实现 |

复用既有动作（不新增）：`configuration.version.read` / `.publish`、`document.version.upload` / `.download`、`product_material.preview` / `.download_original`、`product.publish_baseline`、`identity.user.status_change`、`notification.todo.read`。

## 4. 需求追踪

| 需求 | 说明 | 领域 | 服务 | 权限 | API | 前端/E2E | 失败/并发证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| PIM-003 | 营养标签与营养成分材料 | products / configuration | 材料要求解析 | `product_material.manage` | 材料列表 | 产品详情 | — | 未实现 |
| PIM-004 | 标签稿与包装图片素材 | products / documents | 目录化上传 | `document.version.upload` | 上传会话 | 材料工作台 | — | 未实现 |
| PIM-006 | 材料专业确认绑定文件版本与内容哈希 | products | `SubmitMaterialConfirmation` / `DecideMaterialConfirmation` | `product_material.confirm` | 确认/退回 | 产品详情 | 活动确认竞争 | 未实现 |
| PIM-007 | 原子发布与配置快照 | products | `PublishLegacyBaseline` | `product.publish_baseline` | legacy-baselines publish | E2E | 幂等重试 / 部分失败回滚 | 未实现 |
| PIM-008 | 不可覆盖历史版本链 | products / documents | `CreateLegacyMaterialVersionChain` | `legacy_material.submission.verify` | 排序组链 | 产品详情历史链 | 唯一当前版本约束 | 未实现 |
| PIM-009 | 产品档案与材料完整性视图 | products | `EvaluateProductMaterialCompleteness` | `product_material.completeness.read` | 完整性预检 | 产品详情 | — | 未实现 |
| PIM-010 | 逐一表单录入存量产品 | products | `CreateLegacyBaselineDraft` | `legacy_baseline.draft.create` | 老品基线草稿 | `LegacyProductCreateView` / E2E | 并发与幂等 | 未实现 |
| PIM-011 | 重复候选识别不自动合并 | products | `duplicate_detection` | `legacy_baseline.draft.create` | 草稿创建响应 | 表单提示 | 重复 SHA-256 / 同名同规格 | 未实现 |
| PIM-012 | 老品基线发布门禁 | products | `ValidateProductPublication` 扩展 | `product.publish_baseline` | publish | E2E | 缺必填/缺确认拒绝 | 未实现 |
| PIM-014 | 文件动作分级权限 | documents / products | 票据签发判权 | `product_material.preview` / `.download_original` | download-ticket | E2E 越权拒绝 | 跨用户票据复用拒绝 | 未实现 |
| PLT-003 | 默认拒绝 | authorization | `authorize` | 全部新增动作 | 全部新增端点 | E2E | 每动作允许+拒绝 | 未实现 |
| PLT-005 | 文件与通知权限分离 | documents / notifications | 对象级过滤 | 见第3节 | 列表与详情 | 通知中心 | 接收人隔离 | 未实现 |
| PLT-007 | 管理变更双人复核 | authorization / configuration | `RequestAdminChange` / `ReviewAdminChange` | `configuration.publication.*` | 申请/复核 | 配置页 | 自审拒绝 / 过期 / 重复复核 | 未实现 |
| PLT-009 | 配置快照绑定业务对象 | configuration / products | `CreateSnapshot` | `configuration.version.read` | 快照 | — | 发布后快照不可变 | 未实现 |
| PLT-010 | 受控文件 | documents | 目录化上传链 | `document.version.*` | 上传/下载 | 文件工作台 | 落盘失败不产生 ACTIVE | 未实现 |
| PLT-011 | 权威待办与通知 | notifications | 生命周期服务 | `notification.*` | 通知与待办 | 通知中心 | 处理同步幂等 | 未实现 |
| PLT-013 | 同事务审计 | audit | `append_event` | — | — | — | 回滚不留审计 | 未实现 |
| PLT-016 | 组织边界 | 全域 | 查询过滤 | — | — | — | 跨组织拒绝 | 未实现 |
| 阶段6增量 | 通知分类分级 | notifications | `CreateInAppNotification` | `notification.message.read` | `/notifications/my` | 通知中心 | 六类×三级矩阵 | 未实现 |
| 阶段6增量 | 本地试用认证 | identity | `POST /auth/pilot/login` | `identity.pilot_account.provision` | pilot login | `LoginView` | 停用/错密/生产开关 | 未实现 |
| 阶段6增量 | 待整理资料 | documents / products | `CreateLegacyMaterialSubmission` | `legacy_material.submission.*` | 待整理队列 | 材料工作台 | 不得成为当前有效版本 | 未实现 |
| 阶段6增量 | 试用反馈闭环 | pilot | 反馈六服务 | `pilot.feedback.*` | pilot API | `PilotBatchView` | 并发分派/复测/关闭 | 未实现 |

## 5. 领域 / 服务切片

| 切片 | 计划任务 | 测试位置 | 状态 |
|---|---|---|---|
| 四类配置定义与 schema 校验 | 6.1 | `backend/tests/configuration/test_phase6_definitions.py` | 未实现 |
| 真实双人复核发布 | 6.1 | `backend/tests/configuration/test_dual_control_publish.py` | 未实现 |
| 当前发布唯一性约束 | 6.1 | `backend/tests/configuration/test_published_slot_constraint.py` | 未实现 |
| 目录化上传与失败路径 | 6.2 | `backend/tests/documents/test_catalogued_uploads.py` | 未实现 |
| 文件对象级范围过滤 | 6.2 | `backend/tests/documents/test_document_object_scope.py` | 未实现 |
| 待整理资料入库与幂等 | 6.2 | `backend/tests/products/test_legacy_material_intake.py` | 未实现 |
| 历史版本链 | 6.3 | `backend/tests/products/test_material_chains.py` | 未实现 |
| 材料专业确认 | 6.3 | `backend/tests/products/test_material_confirmations.py` | 未实现 |
| 材料要求三态解析 | 6.3 | `backend/tests/products/test_material_requirements.py` | 未实现 |
| 逐一录入与单一写入口契约 | 6.4 | `backend/tests/products/test_manual_legacy_baseline.py` | 未实现 |
| 老品基线材料门禁 | 6.4 | `backend/tests/products/test_legacy_baseline_material_gate.py` | 未实现 |
| 通知分类与策略 | 6.5 | `backend/tests/notifications/test_classification_policy.py` | 未实现 |
| 通知生命周期 | 6.5 | `backend/tests/notifications/test_notification_lifecycle.py` | 未实现 |
| 通知并发与幂等 | 6.5 | `backend/tests/notifications/test_notification_concurrency.py` | 未实现 |
| 通知 API 与接收人隔离 | 6.6 | `backend/tests/notifications/test_notification_api.py` | 未实现 |
| `employee_no` 唯一性修复 | 6.7 | `backend/tests/identity/test_employee_no_uniqueness.py` | 未实现 |
| 试用密码认证 | 6.7 | `backend/tests/identity/test_pilot_authentication.py` | 未实现 |
| 生产开关阻断 | 6.7 | `backend/tests/identity/test_pilot_auth_settings.py` | 未实现 |
| 试用批次与反馈闭环 | 6.8 | `backend/tests/pilot/` | 未实现 |

## 6. API / OpenAPI

| 场景 | 证据 | 状态 |
|---|---|---|
| 配置草稿、申请、复核、快照端点 | `backend/openapi/schema.yaml` | 未实现 |
| 目录化上传与待整理队列端点 | 同上 | 未实现 |
| 材料列表、组链、确认、完整性预检端点 | 同上 | 未实现 |
| 老品基线草稿与发布端点 | 同上 | 未实现 |
| `GET /api/v1/notifications/my`、`read`、`close` | 同上 | 未实现 |
| `POST /api/v1/auth/pilot/login` | 同上 | 未实现 |
| pilot 批次与反馈端点 | 同上 | 未实现 |
| 生成类型 `schema.d.ts` 无漂移 | `npm run api:generate` + `git diff --exit-code` | 未实现 |
| 新增 `ENABLE_NOTIFICATIONS_API` / `ENABLE_PILOT_API` 开关在四份 settings 显式设置 | `backend/config/settings/*` | 未实现 |

## 7. 前端

| 场景 | 证据 | 状态 |
|---|---|---|
| 配置定义、版本、差异、校验错误、申请与复核闭环 | `frontend/src/modules/admin/ConfigurationListView.spec.ts` | 未实现 |
| 存量产品逐一录入表单 | `frontend/src/modules/products/LegacyProductCreateView.spec.ts` | 未实现 |
| 通知中心空态、筛选、重复点击、403/409、未读更新、安全深链 | `frontend/src/modules/todos/NotificationCenterView.spec.ts` | 未实现 |
| 临时登录仅在非生产标识与后端能力同时存在时展示 | `frontend/src/modules/auth/LoginView.spec.ts` | 未实现 |
| 试用批次与反馈页面 | `frontend/src/modules/pilot/PilotBatchView.spec.ts` | 未实现 |

## 8. E2E

| 场景 | 证据 | 状态 |
|---|---|---|
| 逐一创建存量产品并发布老品基线，重试不重复创建 | `tests/e2e/controlled-files-notifications-pilot-readiness.spec.ts` | 未实现 |
| 当前/历史/待整理材料关联与专业确认 | 同上 | 未实现 |
| 六类通知 × 三级等级、未读/已读、Todo 同步、关闭 | 同上 | 未实现 |
| 深链实时 403 与摘要最小披露 | 同上 | 未实现 |
| 临时账号成功、错误密码、停用用户、独立账号审计、非生产标识 | 同上 | 未实现 |
| 反馈创建—分级—处理—复测—关闭 | 同上 | 未实现 |

## 9. 验收数据基线

| 项 | 目标 | 实际 | 状态 |
|---|---|---|---|
| 存量产品 | 不超过 20 个 | — | 未实现 |
| 正式受控文件版本 | 至少 100 个 | — | 未实现 |
| 可信历史版本 | 至少 20 个 | — | 未实现 |
| 待整理资料 | 至少 10 个 | — | 未实现 |
| 单文件上限 | 配置为 50MB，非代码常量 | — | 未实现 |
| 文件总量 | 不超过 2GB，测试文件不入 Git | — | 未实现 |
| 可重复种子行级快照 | 两次执行稳定 | — | 未实现 |

## 10. 门禁纳入

| 检查 | 结果 | 日期 |
|---|---|---|
| `scripts\preflight.cmd` | 通过 | 2026-07-31 |
| `scripts\check.cmd` 阶段6基线 | **All quality gates passed**（MySQL 488 / Vitest 59 / Playwright 19 / Docker / legacy 均通过） | 2026-07-31 |
| 基线非阻塞告警 | 迁移阶段 2 条 `models.W036`（见第2节 B-1、B-2）；另有阶段5即记录的 npm audit 与前端构建体积告警，本轮未改依赖锁文件 | 2026-07-31 |
| 空库迁移 + 阶段5数据库升级 | 未实现 | — |
| `makemigrations --check` 无漂移 | 未实现 | — |
| 阶段6 Playwright E2E | 未实现 | — |
| `scripts\verify-trd.ps1`（92 需求 / 4 重大阶段门） | 未实现 | — |
| Standards / Spec 双轴代码审阅 | 未实现 | — |
| P0 / P1 / P2 / P3 清单 | 未实现 | — |
