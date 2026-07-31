# Project Meridian 阶段6受控文件、站内通知与试用准备实施计划

> **For agentic workers:** 本计划由规划/审核代理维护；当前代理不执行开发。每个任务由独立实现任务调用 `/implement` 并严格测试先行，每个PR完成后提交当前代理调用 `/code-review`。验收发现由实现方整改，审核方复验；未经 Task 6.9 全量门禁、双轴审阅和阶段检查点，不得宣布阶段6完成。

**Goal:** 在不依赖钉钉、公网回调或外部业务系统的前提下，完成存量产品逐一录入、双层材料配置、受控文件历史链、待整理资料、专业确认、老品基线发布、站内通知和试用反馈闭环，为阶段7生产化收尾准备可验证的软件基线。

**Architecture:** 保持 Django 模块化单体。`configuration`拥有不可变技术文件目录、产品材料要求、通知模板和通知策略；`documents`拥有文件对象和不可变版本链；`products`拥有产品材料、专业确认、完整性检查和老品基线发布；`notifications`拥有站内通知事实与接收人状态；新增轻量`pilot`域保存试用批次和反馈事实。跨域写入只调用公开应用服务，MySQL保存唯一业务事实，Redis/Celery只做可重放分发。

**Tech Stack:** Python 3.13、Django 5.2、DRF 3.16、MySQL 8.0、Redis、Celery 5.6、Vue 3、TypeScript、Pinia、Element Plus、Vitest、Playwright、OpenAPI 3、Docker Compose。

**Status:** 已确认范围并完成任务级规划，尚未开始实现。

**Date:** 2026-07-30（2026-07-31 依据 `a39414b` 检出复核代码基线，更正第2节裁决，新增第5.1节MySQL唯一性约定与第21节动作清单附录）

**Authoritative sources:** `README.md`; `docs/development/00-development-readiness-baseline.md`; `docs/superpowers/specs/2026-07-30-phase-6-internal-pilot-scope.md`; PRD/TRD 02与05；`docs/development/02-engineering-standards.md`; `docs/development/03-test-strategy-and-quality-gates.md`; `docs/implementation/phase-5-checkpoint.md`; 当前Meridian代码。

**Ownership boundary:** 当前规划/审核代理只维护计划、审阅实现、复验门禁并给出GO/NO-GO，不承担Task 6.0—6.9开发，也不在验收任务中直接修复代码。每个finding由独立实现任务整改并重新送审。

## 1. 执行基线与不可变约束

- 正式仓库固定为 `D:\Projects\Meridian`；阶段6从阶段5已验收提交 `41717b2` 或其后续明确合并点创建 `codex/phase-6-controlled-files-notifications-pilot-readiness`。
- 开工前识别并保留当前工作区既有修改；不得使用reset、checkout或覆盖式清理用户文件。
- 首批不超过20个存量产品，使用同一老品基线应用服务逐一创建；不建设产品主数据Excel批量导入，也不保留第二条产品写入口。
- 技术文件目录由系统管理员治理；产品材料要求由产品总监治理。平台配置权不隐含产品敏感资料读取权。
- 材料类型、必填规则、单文件大小和通知策略均来自已发布版本，不硬编码业务配置。
- 当前有效材料必须存在；可信历史材料形成不可覆盖版本链；无法确认顺序、效力或来源的文件停留在待整理资料，不伪造历史事实。
- 具体关键材料由部门负责人或专业确认人确认；产品总监确认并发布老品基线，不代替专业判断。
- 站内通知是权威记录；阶段6不调用钉钉，不因通知失败回滚业务事实。
- 临时本地账号仅限非生产局域网环境且禁止共享；未经正式批准不得在生产启用。
- 阶段6完成内部验收和试用准备，不启动真实业务用户试用；真实用户试用只在阶段7 GO后开始。
- 每个写命令必须在事务内重新判权、锁定或校验并发版本，并写审计和必要的outbox；查询必须对象级过滤。
- 文件、配置、确认、产品版本、通知处理和试用反馈历史不得原位覆盖。
- API统一使用`/api/v1`、UUID `public_id`、稳定错误结构和OpenAPI生成类型。
- MySQL关键行为、权限允许/拒绝、幂等重试、并发竞争、审计回滚和失败恢复不得用SQLite或纯mock替代。

## 2. 当前代码基线与冲突裁决

> 本节结论已于 2026-07-31 对 `a39414b` 检出逐条复核，附代码位置。与复核前描述不一致处已就地更正。

- `configuration`已有不可变版本（`models.py:15-21`状态枚举、`replace_content`/`save`拒绝改已发布内容）、JSON Schema 校验（`schema_registry.py:126`）、`ConfigurationSnapshot`模型与`CreateSnapshot`服务；但**快照和草稿都没有HTTP端点**，`api/urls.py:13-28`只有定义列表、版本列表和发布三个路由。阶段6需新增草稿与快照相关API，不只是"补草稿"。
- `PublishVersion.business_confirmed`默认`True`且API层从不传值（`api/configurations.py:134`），全仓库无其他引用；它不构成任何复核证据。
- `AdminChangeRequest`模型、`RequestAdminChange`、`ReviewAdminChange`（含`ReviewerMustDiffer`，`review_admin_change.py:51-53`）均已存在，但**没有HTTP API、没有任何生产调用方（唯一调用方是`backend/tests/authorization/test_dual_control.py`）、`APPLIED`状态从未被写入、`dual_control_enabled()`无调用方**。阶段6复用该状态机，但必须补齐API、`APPLIED`推进和开关接线；这是Task 6.1的实际工作量，不是"接线即可"。
- 配置发布当前**既无`select_for_update`也无唯一约束**，靠应用层"查PUBLISHED→置RETIRED→发布"（`services/__init__.py:105-125`）；`configuration_version_def_num_uniq`只约束`(definition, version_number)`。阶段6必须补结构性约束，见第5.1节。
- `platform.file_upload`不在`platform`应用内，而是`configuration`的定义码`platform.file_upload`，由`documents/policy.py:24-50`解析，schema只有`allowed_mime_types`与`max_bytes`两字段，未发布配置时回退到settings（测试环境10MB）。阶段6新增版本化技术文件目录，并保留代码级安全兜底。50MB是试用默认配置，不是代码常量。
- `documents`已有流式上传与SHA-256（`api/uploads.py:85-95`）、`FileObject.storage_status` PENDING→ACTIVE、`DocumentVersion.supersedes_version`版本链、`DownloadTicket`和`ReconcileStorage`补偿。注意`UploadSession`本身没有状态字段，用`completed_at`表达；PENDING→ACTIVE属于`FileObject`。阶段6扩展分类与来源元数据，不复制存储链。
- `documents`**未注册`ObjectIdentityProvider`**，`DocumentVersionListView`只按`organization_id`过滤（`api/documents.py:53-56`），全域只有`document.version.upload`/`download`两个动作，`DocumentDownloadView`是`authentication_classes = []`的票据下载入口。阶段6的"敏感文件越权拒绝"和"查询必须对象级过滤"要求必须在Task 6.2补齐对象级判权，不能假定已存在。
- `ProductMaterial.material_type`仍是固定枚举（`models.py:720-745`，6个取值：内外包装、标签、设计源文件、渠道图、批准印样），无法表达配置化规格、营养和检测报告；迁移为受控`material_type_code`并保留现有值。
- `ProductMaterial.confirmation`错误复用必须绑定属性组值的`AttributeConfirmation`（`models.py:760-766`指向`models.py:783-812`）；阶段6新增独立`MaterialConfirmation`。
- `PublishLegacyBaseline`已有权限、事务、审计、outbox和幂等入口，但只校验`payload.get("name")`（`publish_legacy_baseline.py:91-93`），且**完全绕过`ValidateProductPublication`**——后者已有11组校验并已包含检查文档受控状态的`_material_blocks`（`validate_publication.py:440-457`）。阶段6在`PublishLegacyBaseline`增加材料完整性与专业确认门禁时，必须接入`ValidateProductPublication`，不得另写第二套发布校验。
- 存量导入批次的`ConfirmProductImportBatch._confirm_item`只创建`ProductAsset`+`ProductChangeSet`（`import_batch.py:304-330`），`ProductVersion`/`SKU`/`ChannelConfiguration`由`PublishLegacyBaseline`创建。逐一表单要抽取并复用的单条服务`CreateLegacyBaselineDraft`，抽取点是`_confirm_item`，不是整条发布链路。
- `Notification`当前把投递状态混入通知状态（`NotificationStatus`只有PENDING/DELIVERED/FAILED，`models.py:18-21`），缺少类别、等级、已读、关闭和处理同步；`Delivery`已独立表达渠道投递并含`IN_APP`/`DINGTALK`枚举。但`DeliverNotification`仍会把`Notification.status`写成`DELIVERED`（`services/notifications.py:112-113`），`notifications/0002`必须一并解除该耦合。
- `DingTalkNotificationGateway`存在于`channels/dingtalk.py`且被`DeliverNotification`默认实例化（`services/notifications.py:87`），`DINGTALK_NOTIFIER`在`config/`下未定义——当前是"未配置时抛`RuntimeError`"，不是被开关阻断。阶段6须补显式禁用开关，使拒绝路径可测且语义明确。
- `Todo`继续表达行动项，`Notification`表达消息记录；两者当前只有`Notification.todo`外键，`Todo.source_type`/`source_id`指向领域来源而非通知。阶段6按来源键同步，不合并模型。
- 前端配置页只能查看定义，`DocumentWorkbenchView`需要手输`documentId`，`TodoListView`只有列表和跳转；阶段6在现有模块增量形成工作台。前端类型由`npm run api:generate`从`backend/openapi/schema.yaml`生成到`src/api/generated/schema.d.ts`。
- 登录入口不止开发登录：钉钉OAuth的`DingTalkStartView`/`DingTalkCallbackView`已接线存在（`identity/api/auth.py:39-85`），`DevLoginView`按`login_key`查用户且仅在`ENABLE_DEV_LOGIN`下注册。`User`已继承`AbstractBaseUser`、迁移含`password`字段、`UserManager`支持`set_password`。阶段6新增受控临时账号密码入口时必须与既有钉钉登录路径并存不冲突，保留现有E2E开发登录但不暴露给试用人员。
- 所有领域API都挂在`config/urls.py`的`ENABLE_*_API`开关后面（如`ENABLE_CONFIGURATION_API`、`ENABLE_DOCUMENTS_API`、`ENABLE_PRODUCTS_API`）。阶段6新增的通知API与试用API必须同步新增开关并改`base.py`/`development.py`/`test.py`/`production.py`。
- 软件反馈不是经营议题，不复用`operations.OperatingIssue`；新增最小`pilot`域。

## 3. 完成定义

1. 四类关键配置可起草、校验、申请和由不同人员复核发布；已发布版本不可修改，业务对象保存所用快照。
2. 上传按技术目录项校验MIME、大小、敏感等级和预览能力；失败不产生可引用正式版本。
3. 可信历史资料形成不可覆盖链；待整理资料保留来源证据但不能成为当前有效材料。
4. 材料确认绑定具体文件版本和内容哈希，新版本不继承旧确认。
5. 存量产品通过逐一表单进入统一老品基线服务；重试和并发不重复创建产品、版本、SKU或渠道。
6. 材料要求按产品分类和生命周期状态计算三态结果；缺少必填、确认或可信当前版本时禁止发布。
7. 通知拥有六类类别、三级等级、模板与策略版本；阶段6只产生`IN_APP`投递。
8. 接收人可查询、筛选、标为已读和关闭通知；业务完成后与Todo幂等同步，深链接实时判权。
9. 临时账号密码只在非生产局域网启用；停用用户立即拒绝，登录审计不含凭据。
10. 试用批次与反馈可配置、分级、附受控证据、分派、复测和关闭，历史批次不被新配置改写。
11. 内部验收覆盖不超过20个产品、至少100个正式文件版本、20个可信历史版本、10个待整理资料、单文件配置上限50MB、总量不超过2GB。
12. 全量门禁、阶段6 E2E、测试矩阵、代码审阅和检查点均有本轮证据；P0/P1为零。

## 4. 需求与任务映射

| 范围 | 任务 |
|---|---|
| 配置草稿、双人复核、技术目录、材料要求 | Task 6.1 |
| 文件上传、目录校验、来源证据、待整理资料 | Task 6.2 |
| 历史版本链、材料确认、完整性检查 | Task 6.3 |
| 存量产品逐一录入和老品基线发布 | Task 6.4 |
| 通知分类、等级、模板、策略和生命周期 | Task 6.5 |
| 站内通知API、前端、Todo同步和实时判权 | Task 6.6 |
| 临时账号密码、局域网运行边界 | Task 6.7 |
| 试用批次、反馈闭环和启动准备 | Task 6.8 |
| E2E、全量门禁、代码审阅和退出证据 | Task 6.9 |

基线需求映射：

| PRD/TRD需求 | 阶段6覆盖 |
|---|---|
| PIM-003、PIM-004、PIM-006—PIM-008 | 营养/标签、文件素材、确认、原子发布和历史版本 |
| PIM-009—PIM-012、PIM-014 | 产品档案、逐一表单、重复识别、老品基线和文件动作权限 |
| PLT-003、PLT-005、PLT-007、PLT-009 | 默认拒绝、文件/通知权限、管理变更复核和配置快照 |
| PLT-010、PLT-011、PLT-013、PLT-016 | 受控文件、权威待办/通知、同事务审计和组织边界 |
| 2026-07-30阶段6范围增量 | 通知分类分级、本地试用认证、待整理资料和试用反馈闭环 |

## 5. 迁移顺序

1. `configuration/0004_current_published_slot.py`（结构：当前发布唯一性哨兵列与约束）
2. `configuration/0005_seed_phase6_definitions.py`（数据：四类定义与初始 schema）
3. `authorization/0013_seed_phase6_actions.py`
4. `documents/0003_catalogued_upload_metadata.py`
5. `products/0012_legacy_material_intake.py`
6. `products/0013_governed_product_materials.py`
7. `notifications/0002_in_app_notification_lifecycle.py`
8. `identity/0003_employee_no_unique_slot.py`
9. `pilot/0001_initial.py`

迁移不得形成`configuration ↔ products`、`documents ↔ products`或`notifications ↔ pilot`循环。配置快照只从业务域指向`configuration`；通知和试用域只保存稳定业务引用。结构迁移与数据迁移分开提交，符合`.cursor/rules/migrations.mdc`。

### 5.1 MySQL 唯一性实现约定（强制）

Django 的`UniqueConstraint(condition=...)`在 MySQL 后端只触发`models.W036`并被跳过，不会生成任何索引。2026-07-31 在`a39414b`上运行`scripts\check.cmd`，迁移阶段实际输出两条 W036：

```text
identity.User: (models.W036) MySQL does not support unique constraints with conditions.
notifications.Todo: (models.W036) MySQL does not support unique constraints with conditions.
```

即`identity_user_org_employee_no_uniq`（`identity/models/user.py:79-83`）与`notifications_todo_open_dedup_uniq`（`notifications/models.py:52-56`）在 MySQL 上**都不存在**。前者意味着同一组织内非空`employee_no`当前没有数据库唯一性，而 Task 6.7 的试用登录正是以`employee_no`作为账号标识，必须先修复再实现密码登录，否则同号多账号会让登录目标不确定。

因此阶段6凡是"某范围内只允许一条当前记录"的规则，一律采用仓库已验证的空值哨兵列模式，即`operations.IssueSignalLink.active_primary_slot`（`operations/models.py:987-990`）的写法：新增可空标记列，当前记录写入固定值、非当前记录置`NULL`，再对`(范围字段..., 哨兵列)`建普通`UniqueConstraint`。适用范围至少包括：

- 同一`ConfigurationDefinition`只有一个`PUBLISHED`版本；
- 同一业务对象 × `material_type_code`只有一个当前`ProductMaterial`；
- 同一`ProductMaterial`只有一个生效`MaterialConfirmation`；
- 同一`Document`只有一个当前版本指针；
- 同一组织内非空`employee_no`唯一（修复既有未生效约束，Task 6.7 前置）；
- 同一`assignee` × `dedup_key`只有一个`OPEN`待办（修复既有未生效约束）。

禁止用条件唯一约束或纯应用层检查冒充"MySQL约束保证"。每条约束必须有直接插入冲突行并断言数据库拒绝的 MySQL 测试。两条既有失效约束的修复要连同重复数据体检一起做：迁移前先探测是否已存在重复行，存在则停线报告，不得静默丢弃或合并既有账号与待办。

## 6. PR拆分

| PR | 范围 | 独立验收结果 |
|---|---|---|
| PR1 | Task 6.0—6.1 | 阶段基线、配置定义、草稿和真实双人发布 |
| PR2 | Task 6.2 | 目录化上传、来源证据和待整理队列 |
| PR3 | Task 6.3—6.4 | 材料链、专业确认、逐一录入和老品基线 |
| PR4 | Task 6.5—6.6 | 站内通知领域、API和前端闭环 |
| PR5 | Task 6.7—6.8 | 临时认证、局域网边界、试用批次和反馈 |
| PR6 | Task 6.9 | 阶段6纵向E2E、全量门禁、双轴审阅和GO证据 |

## 7. Task 6.0：建立阶段6执行基线

**Files:** Create `docs/implementation/phase-6-test-matrix.md`; Modify `README.md`, `docs/development/01-phased-implementation-plan.md`.

**Interfaces:** Consumes `phase-5-checkpoint.md`、`phase-5-test-matrix.md`、阶段6范围说明和`scripts\check.cmd`; produces阶段6需求—测试证据矩阵。

- [ ] 从阶段5 GO tip创建阶段6分支，记录基线提交和工作树状态，不覆盖未归属修改。
- [ ] 在实际阶段6检出运行`scripts\check.cmd`；失败即记录阻塞，不复用阶段5旧结果冒充本轮基线。
- [ ] 建立测试矩阵，逐项列出配置、文件、产品、通知、认证、反馈、权限、审计、并发、API、前端和E2E证据。
- [ ] 主计划和README链接本计划与测试矩阵，不提前勾选实现项。
- [ ] 提交：`docs: establish phase 6 execution baseline`。

## 8. Task 6.1：配置定义、草稿和双人发布

**Files:** Modify `backend/apps/configuration/models.py`, `backend/apps/configuration/schema_registry.py`, `backend/apps/configuration/services/__init__.py`, `backend/apps/configuration/api/configurations.py`, `backend/apps/configuration/api/urls.py`, `backend/apps/authorization/actions.py`, `backend/apps/authorization/services/request_admin_change.py`, `backend/apps/authorization/services/review_admin_change.py`, `backend/config/urls.py`, `frontend/src/modules/admin/ConfigurationListView.vue`; Create `backend/apps/configuration/migrations/0004_current_published_slot.py`, `backend/apps/configuration/migrations/0005_seed_phase6_definitions.py`, `backend/apps/authorization/migrations/0013_seed_phase6_actions.py`, `backend/apps/authorization/api/admin_changes.py`, `backend/apps/authorization/api/urls.py`（若尚未存在则新建并挂载）, `backend/tests/configuration/test_phase6_definitions.py`, `backend/tests/configuration/test_dual_control_publish.py`, `backend/tests/configuration/test_published_slot_constraint.py`, `frontend/src/modules/admin/ConfigurationListView.spec.ts`.

**Interfaces:** `CreateConfigurationDraft(context, definition_code, content, scope)`, `RequestConfigurationPublication(context, version_public_id)`, `ReviewConfigurationPublication(context, request_public_id, decision)`, existing`CreateSnapshot(...)`。

- [x] 先写MySQL测试：`TECHNICAL_FILE_CATALOG`、`PRODUCT_MATERIAL_REQUIREMENTS`、`NOTIFICATION_TEMPLATE_CATALOG`、`NOTIFICATION_DELIVERY_POLICY`可创建草稿、校验和发布（`tests/configuration/test_phase6_definitions.py`）。
- [x] 技术目录schema定义目录项代码、名称、MIME、单文件上限、预览能力、默认敏感等级和保留约束；材料要求按产品分类/生命周期状态定义三态要求。
- [x] 通知模板定义模板代码、类别、默认等级、最小摘要和允许变量；策略定义类别×等级的站内规则，阶段6拒绝启用钉钉（`NOTIFICATION_CHANNELS`只含`IN_APP`，schema层面无法表达钉钉）。
- [x] `authorization/0013`一次性登记第21节附录列出的全部新增动作；后续PR不得回改该迁移。动作写入**新建的`PHASE6_ACTIONS`元组**，不得追加进`PLATFORM_ACTIONS`/`PRODUCT_ACTIONS`——既有种子迁移`0003`/`0005`在运行时导入这些元组，追加会改变历史迁移在空库上的行为，且其反向操作会误删阶段6动作。`tests/authorization/test_phase6_actions.py`把附录清单固化为断言，防止后续PR回改。
- [x] 现有`configuration.version.publish`直发入口改为只接受已批准变更请求，不允许绕过申请人与复核人分离。
- [x] 测试创建人不能复核自己的发布请求；复核人必须有动作权限；拒绝、过期和重复复核不发布（`tests/configuration/test_dual_control_publish.py`）。
- [x] 复用`AdminChangeRequest`及审计，不复制审批状态机；`business_confirmed`布尔值不再充当关键配置发布证据（`PublishVersion`改收`approved_request`）。
- [x] 补齐`AdminChangeRequest`缺失的接线：新增申请/复核HTTP API、实现`APPROVED → APPLIED`推进、让`dual_control_enabled()`真正生效（`services/__init__.py:89`）。申请与复核走领域动作码`configuration.publication.request`/`review`，不复用平台通用复核权，避免通用复核权外溢到配置发布。
- [x] 同定义只有一个当前PUBLISHED版本按第5.1节的哨兵列模式实现（`configuration/0004_current_published_slot.py`），禁止条件唯一约束；已用直接插入冲突行的MySQL测试断言数据库拒绝，并覆盖升级回填与重复数据停线。重复守卫必须在任何DDL之前执行，因为MySQL无法回滚已应用的DDL。
- [ ] 并发直发的落败方语义（拒绝还是串行覆盖）暂缓裁决：双人复核落地后不存在绕过复核的并发直发路径，唯一约束继续作为兜底。复核环节实现时一并确定并补测。
- [x] 增加草稿详情、创建、发布申请和复核API；敏感正文按权限过滤（无`configuration.content.read_sensitive`者只拿到摘要与状态，`content_json`为`null`）。
- [x] 前端完成定义、版本、差异、校验错误、申请和复核最小闭环（`ConfigurationListView.spec.ts`，12例）。
- [x] 运行配置/授权目标测试、mypy、OpenAPI与前端Vitest：`ruff check`/`ruff format --check`、`mypy config apps`（318文件0错）、`makemigrations --check`（无漂移）、`pytest -q`（550通过）、`spectacular --validate`、前端`lint`/`typecheck`/`vitest`（23文件71例）。本轮未运行：Playwright E2E、Docker镜像构建（属完整`scripts/check.ps1`范围）。
- [x] 提交：`feat: govern phase 6 configuration`（`7c11cff`）。

## 9. Task 6.2：目录化文件上传与待整理资料

**Files:** Modify `backend/apps/documents/models.py`, `backend/apps/documents/policy.py`, `backend/apps/documents/services/uploads.py`, `backend/apps/documents/api/uploads.py`, `backend/apps/documents/api/documents.py`, `backend/apps/documents/apps.py`, `backend/apps/products/models.py`; Create `backend/apps/documents/migrations/0003_catalogued_upload_metadata.py`, `backend/apps/documents/services/catalog.py`, `backend/apps/documents/policies/identity_provider.py`, `backend/apps/products/migrations/0012_legacy_material_intake.py`, `backend/apps/products/services/legacy_material_intake.py`, `backend/tests/documents/test_catalogued_uploads.py`, `backend/tests/documents/test_document_object_scope.py`, `backend/tests/products/test_legacy_material_intake.py`.

> 注意：`documents/policy.py`是上传策略解析器，不是RBAC判权；本任务不要把两者混在一个模块里。

**Interfaces:** `CreateCataloguedUploadSession(context, catalog_item_code, filename, declared_mime)`, `CompleteCataloguedUpload(...)`, `CreateLegacyMaterialSubmission(context, document_version_public_id, owner, claimed_metadata, idempotency_key)`。

- [x] 先写测试：目录项必须来自当前已发布技术目录；MIME、大小、敏感等级和预览能力由该版本解析，缺失或停用项拒绝上传（`documents/services/catalog.py`，`tests/documents/test_catalogued_uploads.py`）。目录项schema新增可选`enabled`布尔值：缺省即可用，停用必须显式声明。
- [x] 保留代码级安全上限作为故障兜底，业务默认50MB只来自配置；新配置无需发版即可改变新上传限制（`DOCUMENT_UPLOAD_HARD_MAX_BYTES`按`min()`封顶，配置写多大都不越过）。
- [x] 上传会话锁定目录版本和摘要，完成时再次校验；上传期间换版不改变已开始会话的规则（会话存`catalog_version_public_id`+`catalog_content_digest`，完成时按该版本读规则）。
- [x] 测试空文件、超限、声明/检测MIME不一致、移动失败、重复完成和并发完成；失败不得产生可引用ACTIVE版本。MIME核验按magic number签名表执行：声明类型可验证时字节必须匹配。
- [x] 保存来源说明、原始文件日期、提交人、SHA-256、声称版本、声称效力和处理状态，不修改二进制（`LegacyMaterialSubmission`，字段名一律带`claimed_`前缀以标明未经核实）。
- [x] 同一幂等键重试只产生一个待整理记录；相同SHA-256关联不同对象时提示重复候选。唯一约束落在`(organization, idempotency_key)`，已用直接插入冲突行的MySQL测试断言数据库拒绝。
- [x] 待整理资料默认不能成为`Document.current_version`、`material_status=APPROVED`的`ProductMaterial`或发布材料：录入完全不写`ProductMaterial`，状态停在`PENDING_TRIAGE`。发布门禁的对应断言在6.3随`validate_publication`一并补。
- [x] 上传、重复判断、状态变化和失败写审计，审计不保存文件正文（审计摘要只含标识、SHA-256和声称值）。
- [ ] 为`documents`注册`ObjectIdentityProvider`：**本轮判定为不可按原文执行**。唯一能由documents自身确立的对象身份是"上传者"，而授予上传者下载权会放宽访问，与既有已测规则冲突（`tests/projects/test_inflight_migration.py:248`断言迁移人未获授权时`can_download`为假）。原始需求是让查询按对象范围**收窄**，已改为版本列表逐条`authorize()`（含真实敏感等级）实现，比只按`organization_id`过滤更严。是否仍需provider待与对象关联模型（`DocumentLink`当前无任何写入方）一并裁决。
- [x] 敏感等级判权必须落在票据签发环节：`DocumentVersionDownloadTicketView`签发前按版本真实`sensitivity_level`重新`authorize()`，DRF权限类只能按资源类型判定、会把所有文件当作INTERNAL。已补测越权用户拿不到票据、票据消费后不可重放。
- [ ] 运行documents/products目标测试、文件移动失败恢复和MySQL并发测试。
- [ ] 提交：`feat: stage catalogued legacy materials`。

## 10. Task 6.3：产品材料版本链、专业确认与完整性

**Files:** Modify `backend/apps/products/models.py`, `backend/apps/products/services/materials.py`, `backend/apps/products/services/validate_publication.py`; Create `backend/apps/products/migrations/0013_governed_product_materials.py`, `backend/apps/products/services/material_chains.py`, `backend/apps/products/services/material_confirmations.py`, `backend/apps/products/services/material_requirements.py`, `backend/apps/products/api/materials.py`, `backend/tests/products/test_material_chains.py`, `backend/tests/products/test_material_confirmations.py`, `backend/tests/products/test_material_requirements.py`.

**Interfaces:** `VerifyLegacyMaterialSubmission(...)`, `CreateLegacyMaterialVersionChain(context, ordered_submission_ids, current_submission_id, owner, material_type_code)`, `SubmitMaterialConfirmation(...)`, `DecideMaterialConfirmation(...)`, `EvaluateProductMaterialCompleteness(...)`。

- [ ] 将固定`MaterialType`迁移为配置驱动`material_type_code`；数据迁移保留现有包装/标签代码，未知旧值停线报告。
- [ ] 新建`MaterialConfirmation`绑定产品材料、具体`DocumentVersion`、内容哈希、确认人、决定、意见和时间。
- [ ] 审计既有`ProductMaterial.confirmation`：可证明的映射迁入新表，无法证明的保持未确认，不补造批准。
- [ ] 可信历史资料先完成来源、顺序和效力验证，再按指定顺序生成`supersedes_version`链；当前有效版本只能有一个。
- [ ] 待整理资料转正必须走验证服务，拒绝直接改状态或跳过专业确认。
- [ ] 新文件版本使旧确认失效但保留历史；确认人只能确认获授权材料类型/对象。
- [ ] 完整性解析锁定材料要求版本，返回缺失、待确认、待整理和不适用清单；`OPTIONAL`缺失不阻塞。
- [ ] MySQL约束覆盖同对象/材料类型唯一当前材料、版本号递增和活动确认竞争；唯一性一律按第5.1节哨兵列模式实现，并用直接插入冲突行的测试证明数据库拒绝。
- [ ] 增加材料列表、待整理队列、排序组链、提交确认、确认/退回和完整性预检API。
- [ ] 提交：`feat: govern product material history`。

## 11. Task 6.4：存量产品逐一录入与老品基线发布

**Files:** Modify `backend/apps/products/services/import_batch.py`, `backend/apps/products/services/publish_legacy_baseline.py`, `backend/apps/products/api/products.py`, `backend/apps/products/api/urls.py`, `frontend/src/modules/products/ProductListView.vue`, `frontend/src/modules/products/ProductDetailView.vue`, `frontend/src/modules/products/store.ts`, `frontend/src/router/index.ts`; Create `backend/apps/products/services/create_legacy_baseline.py`, `backend/apps/products/api/legacy_baselines.py`, `backend/tests/products/test_manual_legacy_baseline.py`, `backend/tests/products/test_legacy_baseline_material_gate.py`, `frontend/src/modules/products/LegacyProductCreateView.vue`, `frontend/src/modules/products/LegacyProductCreateView.spec.ts`.

**Interfaces:** `CreateLegacyBaselineDraft(context, payload, idempotency_key)`；existing`ConfirmProductImportBatch`改为调用同一单条服务；existing`PublishLegacyBaseline`保持唯一发布入口。

- [ ] 先写契约测试证明表单和既有批次最终调用同一老品基线创建服务，不存在两套产品、版本、SKU或渠道写逻辑。抽取点是`ConfirmProductImportBatch._confirm_item`（产品+变更集），版本/SKU/渠道仍由`PublishLegacyBaseline`创建。
- [ ] 材料完整性与专业确认门禁接入既有`ValidateProductPublication`：`PublishLegacyBaseline`目前完全绕过它且只校验`name`，必须改为复用同一校验器扩展`_material_blocks`，不得另写第二套发布校验。
- [ ] 表单覆盖上市产品必填核心字段、至少一个SKU和渠道；材料通过材料工作台关联，不把文件塞进JSON。
- [ ] 重复候选按名称/规格、条码、外部编码提示；用户只能明确创建、关联或取消，系统不得自动合并。
- [ ] 发布前锁定change set，运行字段、SKU/渠道、材料完整性和专业确认预检；失败时不创建部分版本。
- [ ] 发布原子创建产品版本、SKU、渠道和配置快照；相同幂等键重试返回同一结果，不同键不得二次发布。
- [ ] 产品详情显示材料完整性、当前材料、历史链、待整理资料和确认状态；无权限时不泄露文件名或存在性。
- [ ] “不超过20个”只作为阶段6验收数据，不写成永久产品数量上限。
- [ ] 覆盖允许/拒绝、并发、审计回滚、发布失败重试和阶段3产品查询回归。
- [ ] 提交：`feat: publish governed legacy baselines`。

## 12. Task 6.5：站内通知分类、等级和权威生命周期

**Files:** Modify `backend/apps/notifications/models.py`, `backend/apps/notifications/services/notifications.py`, `backend/apps/notifications/consumers.py`; Create `backend/apps/notifications/migrations/0002_in_app_notification_lifecycle.py`, `backend/apps/notifications/services/policies.py`, `backend/apps/notifications/services/lifecycle.py`, `backend/tests/notifications/test_classification_policy.py`, `backend/tests/notifications/test_notification_lifecycle.py`, `backend/tests/notifications/test_notification_concurrency.py`.

**Interfaces:** `CreateInAppNotification(...)`, `MarkNotificationRead(context, notification_public_id)`, `CloseNotification(...)`, `SynchronizeNotificationForSource(...)`。

- [ ] 新增六类`ACTION_REQUIRED`、`DEADLINE`、`BUSINESS_ALERT`、`PROCESS_RESULT`、`SYSTEM_FAILURE`、`INFORMATION`和三级`URGENT`、`IMPORTANT`、`NORMAL`。
- [ ] 通知保存模板版本和策略快照；创建时渲染最小摘要，禁止复制对象正文、敏感字段或凭据。
- [ ] 通知生命周期改为UNREAD/READ/CLOSED并记录read_at/closed_at/close_reason；渠道状态继续只由`Delivery`表达。同时解除`DeliverNotification`把`Notification.status`写成`DELIVERED`的耦合（`services/notifications.py:112-113`），否则"投递状态只由Delivery表达"不成立。
- [ ] 数据迁移根据现有IN_APP delivery映射生命周期；无法判断的记录保持UNREAD并输出迁移说明。
- [ ] 把`notifications_todo_open_dedup_uniq`从条件唯一约束改为第5.1节哨兵列模式，并测试证明其在MySQL上真实生效；当前该约束因W036未被创建。
- [ ] 阶段6策略只创建IN_APP delivery；新增显式禁用开关阻断`DingTalkNotificationGateway`。当前它由`DeliverNotification`默认实例化，只因`DINGTALK_NOTIFIER`未配置而抛`RuntimeError`，这不是可测的拒绝语义。
- [ ] 创建时判权决定是否通知；查询只返回接收人记录；深链接访问仍由目标API重新判权。
- [ ] 已读和关闭使用条件更新实现幂等；并发请求不得丢失首次时间和审计事实。
- [ ] Todo完成、取消或过期后按来源键同步相关通知；重复事件不得重开已关闭事实。
- [ ] 六类×三级矩阵各有测试证据，并覆盖缺失模板、非法变量和未发布策略。
- [ ] 提交：`feat: establish authoritative in-app notifications`。

## 13. Task 6.6：站内通知API、前端和深链接闭环

**Files:** Modify `backend/apps/notifications/api/urls.py`, `backend/apps/notifications/api/todos.py`, `backend/apps/notifications/queries/todos.py`, `backend/config/urls.py`, `backend/config/settings/base.py`, `backend/config/settings/development.py`, `backend/config/settings/test.py`, `backend/config/settings/production.py`, `frontend/src/modules/todos/store.ts`, `frontend/src/modules/todos/TodoListView.vue`, `frontend/src/router/index.ts`; Create `backend/apps/notifications/api/notifications.py`, `backend/apps/notifications/queries/notifications.py`, `backend/tests/notifications/test_notification_api.py`, `frontend/src/modules/todos/NotificationCenterView.vue`, `frontend/src/modules/todos/NotificationCenterView.spec.ts`.

> 通知API须按仓库既有约定挂在新增的`ENABLE_NOTIFICATIONS_API`开关后面，并在四份settings中显式设置。

**Interfaces:** `GET /api/v1/notifications/my`, `POST /api/v1/notifications/{id}/read`, `POST /api/v1/notifications/{id}/close`, existing`GET /api/v1/todos/my`。

- [ ] 列表按状态、类别、等级和时间筛选，默认稳定倒序分页；只返回最小摘要、时间、状态和安全深链。
- [ ] 未读计数使用权限过滤后的数据库查询，不依赖前端缓存；已读/关闭只允许接收人本人。
- [ ] Todo列表显示类别、等级、到期和处理状态；通知中心与待办保持清晰区分并可相互定位。
- [ ] 内部深链使用路由白名单；未知、外部或危险scheme拒绝，不使用任意`window.location.assign`。
- [ ] 深链目标403/404统一显示“无权访问或内容不存在”，不泄露对象存在性。
- [ ] OpenAPI描述分页、过滤、动作和统一错误；重新生成前端类型并移除手写重复类型。
- [ ] Vitest覆盖空态、筛选、重复点击、403/409、未读更新和安全深链；后端覆盖接收人隔离与审计。
- [ ] 提交：`feat: close the in-app notification experience`。

## 14. Task 6.7：临时账号密码与局域网运行边界

**Files:** Modify `backend/apps/identity/models/user.py`, `backend/apps/identity/api/auth.py`, `backend/apps/identity/api/urls.py`, `backend/config/settings/development.py`, `backend/config/settings/test.py`, `backend/config/settings/production.py`, `frontend/src/modules/auth/LoginView.vue`, `frontend/src/modules/auth/store.ts`, `.env.example`; Create `backend/apps/identity/migrations/0003_employee_no_unique_slot.py`, `backend/apps/identity/management/commands/provision_pilot_user.py`, `backend/tests/identity/test_employee_no_uniqueness.py`, `backend/tests/identity/test_pilot_authentication.py`, `backend/tests/identity/test_pilot_auth_settings.py`, `frontend/src/modules/auth/LoginView.spec.ts`, `scripts/start-pilot.cmd`, `scripts/start-pilot.ps1`, `docs/operations/pilot-environment-runbook.md`.

**Interfaces:** `POST /api/v1/auth/pilot/login`使用`employee_no + password`；`provision_pilot_user --employee-no ... --roles ...`；现有session/logout/me保持不变。

- [ ] 使用Django密码哈希和服务端session，不自建令牌；`login_key`继续只服务开发/E2E。`User`已继承`AbstractBaseUser`且`UserManager`支持`set_password`，无需新增密码存储。
- [ ] 与既有钉钉OAuth入口（`DingTalkStartView`/`DingTalkCallbackView`）并存不冲突：三条登录路径的会话建立必须走同一`establish_session()`，不得各自实现登录。
- [ ] 前置：先按第5.1节修复`identity_user_org_employee_no_uniq`，让"同组织非空`employee_no`唯一"在MySQL上真实生效，并测试重复`employee_no`被数据库拒绝。未修复前不得上线以`employee_no`为标识的密码登录。
- [ ] `ENABLE_PILOT_PASSWORD_LOGIN`只允许非生产设置显式开启；production检测到开启必须启动失败。
- [ ] 登录校验组织、ACTIVE状态和密码；停用、离职、错误密码和无角色用户拒绝。
- [ ] 成功和失败登录写脱敏审计；密码、哈希、Cookie和完整凭据不得进入日志或审计。
- [ ] 管理命令只创建或更新明确账号，不批量赋予关键角色；关键角色继续走既有批准流程。
- [ ] 前端仅在非生产标识和后端能力同时存在时展示临时登录，并醒目标注非生产环境。
- [ ] 启动脚本显式绑定批准的局域网地址，配置ALLOWED_HOSTS/CSRF来源并打印访问地址；不自动开放防火墙或公网端口。
- [ ] 每位参与人必须使用独立账号，禁止公共演示账号或共享凭据。
- [ ] 钉钉完成后是否保留只记录为后续评估项，阶段6不自动删除本地认证代码。
- [ ] 提交：`feat: enable controlled non-production pilot access`。

## 15. Task 6.8：试用批次、反馈闭环与启动准备

**Files:** Create `backend/apps/pilot/`, `backend/apps/pilot/migrations/0001_initial.py`, `backend/apps/pilot/models.py`, `backend/apps/pilot/services/batches.py`, `backend/apps/pilot/services/feedback.py`, `backend/apps/pilot/queries.py`, `backend/apps/pilot/api/`, `backend/tests/pilot/`, `frontend/src/modules/pilot/PilotBatchView.vue`, `frontend/src/modules/pilot/PilotBatchView.spec.ts`, `frontend/src/modules/pilot/store.ts`; Modify `backend/config/settings/base.py`（`INSTALLED_APPS`与`ENABLE_PILOT_API`）, `backend/config/settings/development.py`, `backend/config/settings/test.py`, `backend/config/settings/production.py`, `backend/config/urls.py`, `frontend/src/router/index.ts`.

**Interfaces:** `CreatePilotBatch(...)`, `AddPilotParticipant(...)`, `OpenPilotFeedback(...)`, `AssignPilotFeedback(...)`, `SubmitFeedbackRetest(...)`, `ClosePilotFeedback(...)`。

- [ ] 模型只保存试用批次、参与人快照、反馈、严重程度、复现摘要、受控证据引用、责任人、状态、目标版本和验收结果。
- [ ] 默认约8人/2周作为可编辑配置，不写死；开始后的批次保存快照，后续模板调整不改写历史。
- [ ] 反馈状态最小为OPEN/TRIAGED/IN_PROGRESS/READY_FOR_RETEST/CLOSED/REJECTED，且只通过应用服务迁移。
- [ ] P0/P1关闭前不得完成批次；P2遗留必须填写规避、责任人、目标版本和书面接受人；P3可转后续清单。
- [ ] 证据附件必须是获授权受控文件版本；反馈摘要不复制敏感产品正文。
- [ ] 同一批次/外部反馈键和重复提交幂等；并发分派、复测和关闭使用version_no或条件更新。
- [ ] 权限区分批次管理、反馈创建、分派、处理、复测和关闭；系统管理员不因环境支持权获得敏感反馈读取权。
- [ ] 阶段6只用内部验收数据走通完整反馈链，不把批次标记为真实业务试用完成。
- [ ] 生成阶段7后试用启动清单：账号、人员、周期、数据范围、反馈R/A、已知限制和停止条件。
- [ ] 提交：`feat: prepare governed pilot feedback`。

## 16. Task 6.9：纵向E2E、全量门禁、代码审阅与阶段GO

**Files:** Create `tests/e2e/controlled-files-notifications-pilot-readiness.spec.ts`, `backend/apps/identity/management/commands/seed_phase6_acceptance.py`, `backend/tests/identity/verify_phase6_seed_cold_start.py`, `docs/implementation/phase-6-checkpoint.md`; Modify `docs/implementation/phase-6-test-matrix.md`, `README.md`, `docs/development/01-phased-implementation-plan.md`.

**Interfaces:** `seed_phase6_acceptance`必须可重复执行；`scripts\check.cmd`是全量权威门禁；`scripts\verify-trd.ps1`继续校验92项需求和4个重大阶段门。

- [ ] 冷启动迁移后执行两次阶段6种子，比较产品、版本、SKU、渠道、配置快照、文件链、材料确认、通知、Todo、试用批次和反馈的行级稳定快照。
- [ ] E2E逐一创建存量产品，关联当前/历史/待整理材料，专业确认并发布老品基线；验证重试不重复创建。
- [ ] E2E覆盖六类通知、三级等级、未读/已读、Todo处理同步、关闭、深链实时403和摘要最小披露。
- [ ] E2E覆盖临时账号成功、错误密码、停用用户、独立账号审计和非生产标识。
- [ ] E2E用内部验收数据完成反馈创建、分级、处理、复测和关闭。
- [ ] 验收数据达到不超过20个产品、至少100个正式版本、20个可信历史版本、10个待整理资料、单文件配置上限50MB和总量不超过2GB；测试文件不得提交Git。
- [ ] 执行空库迁移、阶段5数据库升级、`makemigrations --check`、目标MySQL测试、完整`scripts\check.cmd`、`scripts\verify-trd.ps1`和必要Docker构建。
- [ ] 对阶段6提交范围执行Spec与Standards双轴`/code-review`；修复所有P0/P1，并按规则处理P2/P3后重跑受影响门禁。
- [ ] 测试矩阵记录本轮真实命令、提交号和结果；未执行、环境阻塞和文档历史结果分栏披露。
- [ ] 检查点给出明确GO/NO-GO；只有全量门禁通过、代码审阅闭环和P0/P1为零才可进入阶段7。
- [ ] 明确阶段6 GO不代表真实用户试用开始，下一步只能是阶段7生产化收尾。
- [ ] 提交：`docs: record phase 6 acceptance`。

## 17. 阶段6必须覆盖的权限与审计

- 配置草稿创建、发布申请、复核发布、查看正文；
- 技术目录上传、产品材料关联、待整理资料查看和验证；
- 材料专业确认、老品基线发布；
- 通知读取、标记已读和关闭；
- 临时账号预置、停用和登录；
- 试用批次管理、反馈创建、分派、处理、复测和关闭；
- 敏感文件预览与原件下载继续使用独立动作；
- 每项至少包含允许、拒绝、跨组织、对象范围变化后立即拒绝和审计断言。

平台管理员只允许管理账号、技术配置和运行环境；除非另有业务角色或专项授权，不得查看高敏产品材料、通知对象正文或反馈证据。

## 18. 阶段6停止条件

出现以下任一情况立即停止当前切片并记录：

- 实际样本需要目录之外的新材料类型且业务未确认分类；
- 无法确定历史文件来源、顺序或效力，却被要求直接标记正式有效；
- 关键配置仍可由创建人自行发布；
- 材料确认无法绑定具体文件版本和内容哈希；
- 临时认证需要暴露公网或绕过production安全开关；
- 通知策略触发真实钉钉调用；
- 迁移需要覆盖历史文件、配置、确认或通知记录；
- MySQL唯一约束、权限拒绝、审计回滚或并发测试无法在当前环境执行；
- 全量门禁失败但有人要求以局部测试代替阶段GO；
- 真实业务用户被要求在阶段7 GO前开始正式试用。

## 19. 明确延期到阶段7或以后

- 钉钉登录、组织同步、钉钉通知和钉钉深链接；
- 真实外部系统API及通用集成平台；
- 公网入口、生产认证决策和生产凭据；
- 6 vCPU/8GB正式容量、安全专项、备份恢复和RPO/RTO证明；
- 离线发布包、受控试用环境部署、回滚和启动批准；
- 正式生产切换、生产数据迁移和全员推广延后到真实用户试用结论之后；
- 真实用户首轮试用的实际运行与业务反馈结论。

## 20. 阶段6退出证据

- `docs/implementation/phase-6-test-matrix.md`；
- `docs/implementation/phase-6-checkpoint.md`；
- 阶段6分支、基线提交和最终提交范围；
- 空库和阶段5升级迁移结果；
- MySQL后端测试、前端lint/format/type/Vitest/build、OpenAPI与生成类型；
- 阶段6Playwright E2E与可重复种子行级快照；
- 全量`scripts\check.cmd`与`scripts\verify-trd.ps1`结果；
- Spec/Standards双轴代码审阅结论及整改记录；
- P0/P1/P2/P3清单、已知限制和阶段7输入；
- 明确结论：阶段6 GO或NO-GO，且不把未开始的真实用户试用写成已完成。

## 21. 附录：`authorization/0013` 新增动作清单

`PHASE6_ACTIONS`元组内容如下，`authorization/0013_seed_phase6_actions.py`一次性登记，后续PR只允许使用不允许回改。`ActionCategory`取值域为`READ`/`WRITE`/`DECIDE`/`ADMIN`/`EXPORT`（`authorization/models/role.py:20-25`）。

| action_code | resource_type | ActionCategory | 用途 | 任务 |
|---|---|---|---|---|
| `configuration.draft.create` | `configuration.version` | WRITE | 创建关键配置草稿 | 6.1 |
| `configuration.publication.request` | `configuration.version` | ADMIN | 提交配置发布申请 | 6.1 |
| `configuration.publication.review` | `configuration.version` | ADMIN | 复核配置发布申请 | 6.1 |
| `configuration.content.read_sensitive` | `configuration.version` | READ | 查看敏感配置正文 | 6.1 |
| `legacy_material.submission.create` | `legacy_material_submission` | WRITE | 提交历史资料进入待整理区 | 6.2 |
| `legacy_material.submission.read` | `legacy_material_submission` | READ | 查看待整理资料及来源证据 | 6.2 |
| `legacy_material.submission.verify` | `legacy_material_submission` | DECIDE | 验证来源、顺序与效力并转正 | 6.3 |
| `product_material.manage` | `product_material` | WRITE | 维护产品材料关联与历史版本链 | 6.3 |
| `product_material.confirm` | `product_material` | DECIDE | 专业确认或退回具体文件版本 | 6.3 |
| `product_material.completeness.read` | `product_material` | READ | 读取材料完整性预检结果 | 6.3 |
| `legacy_baseline.draft.create` | `product_change_set` | WRITE | 逐一表单创建老品基线草稿 | 6.4 |
| `notification.message.read` | `notification.message` | READ | 读取本人站内通知 | 6.6 |
| `notification.message.mark_read` | `notification.message` | WRITE | 标记本人通知已读 | 6.6 |
| `notification.message.close` | `notification.message` | WRITE | 关闭本人通知 | 6.6 |
| `identity.pilot_account.provision` | `identity.user` | ADMIN | 预置试用临时账号 | 6.7 |
| `pilot.batch.manage` | `pilot.batch` | ADMIN | 创建与配置试用批次、参与人 | 6.8 |
| `pilot.batch.read` | `pilot.batch` | READ | 查看试用批次与参与人快照 | 6.8 |
| `pilot.feedback.create` | `pilot.feedback` | WRITE | 创建试用反馈 | 6.8 |
| `pilot.feedback.read` | `pilot.feedback` | READ | 查看反馈及受控证据引用 | 6.8 |
| `pilot.feedback.assign` | `pilot.feedback` | ADMIN | 分级与分派责任人 | 6.8 |
| `pilot.feedback.handle` | `pilot.feedback` | WRITE | 处理并提交待复测 | 6.8 |
| `pilot.feedback.retest` | `pilot.feedback` | DECIDE | 复测判定 | 6.8 |
| `pilot.feedback.close` | `pilot.feedback` | DECIDE | 关闭或驳回反馈 | 6.8 |

复用而不新增的既有动作：

| 既有 action_code | 阶段6用途 | 说明 |
|---|---|---|
| `configuration.version.read` | 读取定义与版本列表 | 语义不变 |
| `configuration.version.publish` | 执行已批准的发布 | 语义收紧为"只接受已批准变更请求" |
| `authorization.admin_change.request` / `.review` | 通用管理变更申请与复核 | 配置发布走上表的领域专用动作，避免通用复核权外溢 |
| `document.version.upload` / `.download` | 受控文件上传与下载 | 目录项校验在服务层，不新增动作 |
| `product_material.preview` / `.download_original` | 敏感材料预览与原件下载 | 按范围要求继续保持独立动作 |
| `product.publish_baseline` | 发布老品基线 | 增加材料门禁但不改动作 |
| `identity.user.status_change` | 停用试用账号 | 不新增停用动作 |
| `notification.todo.read` | 读取本人待办 | 与新增通知动作并存 |

试用登录本身不设动作码：登录发生在会话建立之前，由`ENABLE_PILOT_PASSWORD_LOGIN`开关、组织与`ACTIVE`状态校验控制，成功与失败都写脱敏审计。
