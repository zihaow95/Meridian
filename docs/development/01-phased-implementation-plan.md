# 产品全生命周期平台分阶段实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在独立正式工程中交付从提案到退市的可运行产品全生命周期平台，并满足已确认PRD、TRD和技术架构。

**Architecture:** 采用Django模块化单体和Vue 3前端，MySQL保存业务事实，NAS保存受控文件，Redis/Celery处理可恢复异步任务。按纵向业务闭环逐步交付，每个阶段都必须形成可运行、可测试、可回滚的软件增量。

**Tech Stack:** Python 3.13、Django 5.2 LTS、Django REST Framework、MySQL 8.0、Redis、Celery、Vue 3、TypeScript、Vite、Element Plus、Docker Compose、pytest、Vitest、Playwright。

**Status:** 已确认基线（2026-07-06）

**Project Code:** Project Meridian（经纬）

---

## 1. 计划使用规则

本文是跨领域主计划。每个实施阶段开始前，应从对应TRD生成一份任务级执行计划；任务级计划必须列出精确文件、测试代码、执行命令和提交点。

禁止一次性完成全部数据库模型后再补业务流程。每个阶段必须同时包含：

- 数据模型和迁移；
- 应用服务和状态规则；
- API和前端最小闭环；
- 权限和审计；
- 自动化测试；
- 文档和可部署结果。

## 2. 正式工程结构

```text
D:\Projects\Meridian\
├─ backend/
│  ├─ config/
│  ├─ apps/
│  │  ├─ identity/
│  │  ├─ authorization/
│  │  ├─ opportunities/
│  │  ├─ products/
│  │  ├─ projects/
│  │  ├─ stage_gates/
│  │  ├─ work_items/
│  │  ├─ documents/
│  │  ├─ operations/
│  │  ├─ integrations/
│  │  ├─ notifications/
│  │  ├─ audit/
│  │  ├─ configuration/
│  │  └─ platform/
│  ├─ tests/
│  ├─ manage.py
│  └─ pyproject.toml
├─ frontend/
│  ├─ src/
│  │  ├─ api/
│  │  ├─ modules/
│  │  ├─ router/
│  │  ├─ stores/
│  │  └─ shared/
│  ├─ tests/
│  └─ package.json
├─ deploy/
│  ├─ compose/
│  └─ nginx/
├─ tests/e2e/
├─ scripts/
└─ README.md
```

除明确标注仓库外部路径外，后续任务中的文件路径均相对于`D:\Projects\Meridian`。

## 3. 阶段0：工程基础

目标：建立可重复启动、测试、构建和部署的空业务工程。

### Task 0.1：初始化独立工程

**Files:**

- Create: `backend/pyproject.toml`
- Create: `backend/manage.py`
- Create: `backend/config/settings/`
- Create: `frontend/package.json`
- Create: `frontend/src/main.ts`
- Create: `deploy/compose/compose.dev.yml`
- Create: `.env.example`
- Create: `README.md`

- [ ] 创建Django、Vue和Docker Compose目录，不复制旧原型代码。
- [ ] 配置开发、测试、生产三套Django设置入口。
- [ ] 配置MySQL、Redis和NAS本地替代目录。
- [ ] 运行后端健康检查。

```powershell
docker compose -f deploy/compose/compose.dev.yml config
```

预期：退出码0，无未解析变量。

- [ ] 运行前端类型检查和生产构建。
- [ ] 提交：`chore: initialize formal lifecycle platform`

### Task 0.2：建立质量工具链

**Files:**

- Create: `backend/pytest.ini`
- Create: `frontend/eslint.config.js`
- Create: `tests/e2e/playwright.config.ts`
- Create: `scripts/check.ps1`
- Create: `.gitee/pipeline.yml`或Gitee实际流水线配置文件

- [ ] 配置Ruff、类型检查、pytest、前端lint、Vitest和Playwright。
- [ ] 让`check.ps1`依次执行所有静态检查和测试。
- [ ] 配置CI只验证和生成离线发布包，不连接生产服务器。
- [ ] 验证空工程质量门禁全部通过。
- [ ] 提交：`ci: add project quality gates`

**阶段退出条件：**

- 新开发者可依据README启动工程；
- MySQL测试数据库可自动创建和清理；
- CI能够验证后端、前端和镜像构建；
- 正式工程不引用`npd-lcm-mvp/`。

**阶段状态：已完成（2026-07-06）。** 完成证据见 [阶段0 完成检查点](../implementation/phase-0-checkpoint.md)。CI 采用 GitHub Actions（原 Gitee Go 因内置 Node/Python 版本过旧无法满足基线，已切换，详见检查点第 7 节）。

## 4. 阶段1：平台内核

**状态：** 已完成并通过 remediation 重新验收（2026-07-08）

**修复计划：** [`docs/implementation/phase-1-code-review-remediation-plan.md`](../implementation/phase-1-code-review-remediation-plan.md)

**任务级计划：** [`docs/superpowers/plans/2026-07-06-phase-1-platform-kernel.md`](../superpowers/plans/2026-07-06-phase-1-platform-kernel.md)

**测试矩阵：** [`docs/implementation/phase-1-test-matrix.md`](../implementation/phase-1-test-matrix.md)

**PR 拆分：** PR1（1.0–1.4 契约/身份/认证/授权）→ PR2（1.5–1.7 审计/发件箱）→ PR3（1.8–1.10 配置/文件/待办）→ PR4（1.11–1.12 前端/E2E/退出）

**检查点：** `docs/implementation/phase-1-checkpoint.md`

目标：先建立所有业务域共同依赖的身份、权限、审计、配置、文件和可靠事件能力。

### Task 1.1：身份、组织和开发登录

**Files:**

- Create: `backend/apps/identity/`
- Create: `backend/tests/identity/`
- Create: `frontend/src/modules/auth/`

- [ ] 先编写用户状态、组织边界和停用登录测试。
- [ ] 实现组织、部门、用户和身份绑定模型。
- [ ] 实现仅限开发/测试环境的本地登录适配器。
- [ ] 确保生产设置不能启用开发登录。
- [ ] 提交：`feat: add identity and organization foundation`

### Task 1.2：权限、审计和事件发件箱

**Files:**

- Create: `backend/apps/authorization/`
- Create: `backend/apps/audit/`
- Create: `backend/apps/platform/outbox/`
- Create: `backend/tests/authorization/`
- Create: `backend/tests/audit/`

- [ ] 编写默认拒绝、平台管理权隔离和事务内重新判权测试。
- [ ] 实现RBAC动作目录、ABAC策略接口和对象身份适配器。
- [ ] 实现只追加审计记录。
- [ ] 实现MySQL事件发件箱、Celery分发和消费者幂等。
- [ ] 验证Redis不可用时业务事实和待发送事件仍保留。
- [ ] 提交：`feat: add authorization audit and outbox`

### Task 1.3：配置、文件和待办

**Files:**

- Create: `backend/apps/configuration/`
- Create: `backend/apps/documents/`
- Create: `backend/apps/notifications/`
- Create: `backend/tests/documents/`
- Create: `frontend/src/modules/todos/`

- [ ] 实现不可变配置版本及项目快照接口。
- [ ] 实现文件PENDING—ACTIVE补偿流程和SHA-256。
- [ ] 实现文档版本、业务关联和短时下载票据。
- [ ] 实现权威待办、站内通知和权限过滤摘要。
- [ ] 验证文件失败、审计失败和重复事件场景。
- [ ] 提交：`feat: add configuration documents and todos`

**阶段退出条件：**

- PLT-001至PLT-013的基础能力可被业务模块调用；
- 权限、审计、文件和事件具备MySQL集成测试；
- 管理员不能因平台角色读取高敏业务测试对象。

## 5. 阶段2：提案到项目纵向切片

**状态：** 已完成（2026-07-09）

**任务级计划：** [`docs/superpowers/plans/2026-07-08-phase-2-opportunity-to-project.md`](../superpowers/plans/2026-07-08-phase-2-opportunity-to-project.md)

**测试矩阵：** [`docs/implementation/phase-2-test-matrix.md`](../implementation/phase-2-test-matrix.md)

**完成检查点：** [`docs/implementation/phase-2-checkpoint.md`](../implementation/phase-2-checkpoint.md)

**PR 拆分：** PR1（Task 2.1–2.3 提案提交）→ PR2（Task 2.4–2.6 阶段门/评估/暂缓复议）→ PR3（Task 2.7 原子立项）→ PR4（Task 2.8–2.10 前端/E2E/退出）

目标：交付首个可供业务试用的提案—立案—立项闭环。**已达成。**

### Task 2.1：提案、成员和额度

**Files:**

- Create: `backend/apps/opportunities/`
- Create: `backend/tests/opportunities/`
- Create: `frontend/src/modules/opportunities/`

- [x] 实现机会资产、提案版本、成员邀请和额度账。
- [x] 实现资格、四项核心内容、公开摘要和撤回校验。
- [x] 实现提案工作台、我的提案和额度提示。
- [x] 覆盖OPP-001至OPP-005、OPP-015。
- [x] 提交：`feat: add proposal submission workflow`

### Task 2.2：重大阶段门和拟立项方案

**Files:**

- Create: `backend/apps/stage_gates/`
- Create: `backend/tests/stage_gates/`
- Create: `frontend/src/modules/stage-gates/`

- [x] 实现统一阶段门结果和不可变评审提交。
- [x] 实现经管会整体结论、老板最终决策及差异展示。
- [x] 实现待补充、暂缓、Pass和复议。
- [x] 实现拟立项方案、合并、拆分和季度回看。
- [x] 覆盖OPP-006至OPP-009、OPP-011至OPP-014。
- [x] 提交：`feat: add opportunity stage gates`（拆分为多个 feat 提交，见检查点）

### Task 2.3：原子创建项目和产品草稿

**Files:**

- Create: `backend/apps/projects/`
- Create: `backend/apps/products/`
- Test: `backend/tests/opportunities/test_project_creation.py`

- [x] 编写重复立项和中途失败回滚测试。
- [x] 实现项目基础记录、产品/变更草稿和模板运行时初始化。
- [x] 建立机会—项目—产品来源关系。
- [x] 实现生命周期看板首个版本。
- [x] 覆盖OPP-010和GLB-001至GLB-003。
- [x] 提交：`feat: create project and product draft atomically`（看板与 E2E 在 Task 2.9 交付）

**阶段退出条件：**

- [x] 产品经理和部门负责人可提交真实提案；
- [x] 两个重大阶段门可完成决策；
- [x] 立项通过只创建一个项目和正确产品草稿；
- [x] 权限、文件版本和审计可完整追溯。

## 6. 阶段3：产品档案与存量迁移

**状态：** 已完成（2026-07-10，见 [`phase-3-checkpoint.md`](../implementation/phase-3-checkpoint.md)）

**任务级计划：** [`docs/superpowers/plans/2026-07-09-phase-3-product-profile-migration.md`](../superpowers/plans/2026-07-09-phase-3-product-profile-migration.md)

**测试矩阵：** [`docs/implementation/phase-3-test-matrix.md`](../implementation/phase-3-test-matrix.md)

### Task 3.1：产品—版本—SKU—渠道

**Files:**

- Modify: `backend/apps/products/`
- Create: `backend/tests/products/`
- Create: `frontend/src/modules/products/`

- [ ] 实现固定核心字段、属性Schema、营养、素材和外部绑定。
- [ ] 实现草稿差异、内容哈希确认和基线冲突。
- [ ] 实现原子发布和并行有效范围。
- [ ] 实现产品档案查询、搜索和权限字段投影。
- [ ] 覆盖PIM-001至PIM-009、PIM-013至PIM-014。
- [ ] 提交：`feat: add governed product dossier`

### Task 3.2：存量产品导入

**Files:**

- Modify: `backend/apps/products/`
- Create: `backend/apps/products/imports/`
- Create: `backend/tests/products/test_legacy_import.py`
- Create: `frontend/src/modules/products/pages/ProductImportPage.vue`

- [ ] 实现Excel模板、导入批次、逐行错误和重复候选。
- [ ] 实现产品总监确认基线和录入纠正。
- [ ] 验证重复导入幂等及部分完整基线。
- [ ] 覆盖PIM-010至PIM-012。
- [ ] 提交：`feat: add legacy product baseline import`

## 7. 阶段4：开发到首次上市

**状态：** 已完成（GO，2026-07-20）；见 [`phase-4-checkpoint.md`](../implementation/phase-4-checkpoint.md)。阶段5分支自 tip `edd50ce`。

**任务级计划：** [`docs/superpowers/plans/2026-07-14-phase-4-development-first-launch.md`](../superpowers/plans/2026-07-14-phase-4-development-first-launch.md)

**测试矩阵：** [`docs/implementation/phase-4-test-matrix.md`](../implementation/phase-4-test-matrix.md)

### Task 4.1：项目模板、任务和交付物

**Files:**

- Modify: `backend/apps/projects/`
- Create: `backend/apps/work_items/`
- Create: `backend/tests/work_items/`
- Create: `frontend/src/modules/projects/`

- [ ] 实现D1—L3默认模板和项目快照。
- [ ] 实现部门责任到唯一个人R。
- [ ] 实现任务依赖、计划、逾期和调整。
- [ ] 实现三层交付物和专业确认。
- [ ] 覆盖EXE-001至EXE-006、EXE-011至EXE-013。
- [ ] 提交：`feat: add project execution workbench`

### Task 4.2：阶段策略、首次上市和运营交接

**Files:**

- Modify: `backend/apps/stage_gates/`
- Modify: `backend/apps/products/`
- Create: `backend/tests/projects/test_launch_handover.py`
- Create: `frontend/src/modules/projects/pages/LaunchGatePage.vue`

- [ ] 实现复用、简化、豁免、不适用和并行。
- [ ] 实现普通阶段门和`FIRST_LAUNCH`重大阶段门。
- [ ] 实现产品发布失败补偿和运营交接。
- [ ] 实现在途项目当前阶段迁移。
- [ ] 覆盖EXE-007至EXE-010、EXE-014。
- [ ] 提交：`feat: complete launch and handover workflow`

## 8. 阶段5：运营、迭代和退市

**状态：** 已完成（GO，2026-07-29）；见 [`phase-5-checkpoint.md`](../implementation/phase-5-checkpoint.md)。全量门禁与 Standards / Spec 双轴终审均通过；阶段6尚未开始。

**任务级计划：** [`docs/superpowers/plans/2026-07-20-phase-5-operations-iteration-retirement.md`](../superpowers/plans/2026-07-20-phase-5-operations-iteration-retirement.md)

**测试矩阵：** [`docs/implementation/phase-5-test-matrix.md`](../implementation/phase-5-test-matrix.md)

任务切片以任务级计划 Task 5.0—5.10 与 PR1—PR7 为准（监控配置 → 接入事实 → 汇总风险 → 议题迭代 → 退市 → API → 前端/E2E）。下方保留主计划摘要，便于跨阶段导航。

### Task 5.1：经营事实、指标和风险信号

**Files:**

- Create: `backend/apps/operations/`
- Create: `backend/tests/operations/`
- Create: `frontend/src/modules/operations/`

- [ ] 实现接口/文件/手工批次和标准经营事实。
- [ ] 实现人工有效值、汇总下钻和受控指标规则。
- [ ] 实现风险信号、数据不足和迟到数据重算。
- [ ] 覆盖OPS-001至OPS-007、OPS-013至OPS-014。
- [ ] 提交：`feat: add operating facts and risk signals`

### Task 5.2：经营议题、迭代和退市

**Files:**

- Modify: `backend/apps/operations/`
- Modify: `backend/apps/opportunities/`
- Create: `backend/tests/operations/test_issue_conversion.py`
- Create: `backend/tests/operations/test_retirement.py`
- Create: `frontend/src/modules/operations/pages/OperatingIssuePage.vue`

- [ ] 实现经营议题和轻量研判。
- [ ] 实现议题转迭代提案但不自动提交。
- [ ] 实现普通迭代结果回写。
- [ ] 实现`PRODUCT_RETIREMENT`重大阶段门和计划执行。
- [ ] 覆盖OPS-008至OPS-012。
- [ ] 提交：`feat: close iteration and retirement loop`

## 9. 阶段6：存量产品、受控文件和试用准备

**状态：** 已完成并GO（2026-08-06）；见 [`phase-6-checkpoint.md`](../implementation/phase-6-checkpoint.md)和[`phase-6-final-code-review.md`](../implementation/phase-6-final-code-review.md)。HEAD `62ffea3`全量门禁与TRD校验通过，Standards / Spec双轴P0/P1/P2均为0；允许启动阶段7实施。

**范围说明：** [`2026-07-30-phase-6-internal-pilot-scope.md`](../superpowers/specs/2026-07-30-phase-6-internal-pilot-scope.md)

**任务级计划：** [`2026-07-30-phase-6-controlled-files-notifications-pilot-readiness.md`](../superpowers/plans/2026-07-30-phase-6-controlled-files-notifications-pilot-readiness.md)

**测试矩阵：** [`phase-6-test-matrix.md`](../implementation/phase-6-test-matrix.md)

**完成检查点：** [`phase-6-checkpoint.md`](../implementation/phase-6-checkpoint.md)

**试用访问边界：** 阶段6仅通过公司局域网访问非生产环境；每位试用人员使用管理员预置的独立临时账号和密码，不允许共享账号。钉钉登录完成后是否保留本地账号能力另行评估，未经正式批准不得在生产环境启用。

**首批文件验收基线：** 不超过20个产品、至少100个正式受控文件版本，其中至少20个可信历史版本；另含至少10个待整理资料。单文件试用默认上限通过版本化配置设为50MB，首批文件总量不超过2GB；这些数字不替代阶段7正式容量验证。

**首轮真实用户试用默认配置：** 阶段7 GO 后启动，约8人、持续2周，由产品总监担任验收负责人，一名产品经理统一收集反馈，研发、质量/合规、包装/设计、销售/渠道和系统管理共同参与。部门、人员、周期和反馈责任人按试用批次配置，不硬编码且不改写历史批次记录。

较早的“钉钉正式集成和外部系统 API 接入”范围已被本节取代。当前不存在统一外部业务系统，历史资料分散在项目成员设备中；阶段六不得虚构 API 数据源，也不得建设个人设备扫描、桌面采集代理或通用集成平台。

### Task 6.1：存量产品和受控文件

- [x] 首批不超过20个现有产品，全部复用既有产品创建流程逐一录入；不建设产品主数据 Excel 批量导入或第二条创建入口。
- [x] 将逐一录入作为既有产品档案、版本、SKU和渠道模块的业务回归，问题进入阶段六试用反馈闭环。
- [x] 复用配置版本能力实现双层文件治理：系统管理员发布技术文件目录，产品总监发布产品材料要求模板。
- [x] 首批已上市产品默认要求产品规格、内外包装图片、标签稿、营养标签/营养成分文件和检测报告；其他已批准材料类型可按配置上传。
- [x] 支持将业务提交的历史文件纳入受控文件版本、权限、审计和业务对象关联。
- [x] 当前有效材料必须上传；可靠历史材料按版本时间顺序追加，无法确认版本顺序或有效状态的文件进入待整理区，不得直接成为正式有效版本。
- [x] 建立受控资料包的来源、提交人、校验值、映射结果、重复/冲突和待处理记录。
- [x] 通过可重复演练证明重试不会重复创建产品、文件版本或业务关联。

### Task 6.2：站内通知闭环

- [x] 复用现有待办和站内通知模型，补齐通知分类、等级、模板、策略版本和历史绑定。
- [x] 完成站内通知列表、未读/已读、待办深链接、处理结果同步、关闭和审计闭环。
- [x] 采用已确认的初始渠道矩阵；阶段六所有类别均只投递站内，不调用钉钉。
- [x] 通知摘要遵循最小披露和对象级实时判权。

### Task 6.3：试用能力和内部验收

- [x] 由管理员预置独立临时账号和密码，通过公司局域网访问非生产环境；禁止共享账号并记录登录审计。
- [x] 准备可重复初始化的试用产品、受控文件、待办和站内通知数据。
- [x] 在非生产环境完成试用能力、主流程和问题反馈闭环的内部验收，不在阶段6启动真实业务用户试用。
- [ ] 运行全量质量门禁、完成代码审阅并形成阶段检查点；阶段6 GO 后进入阶段7。

### 延期范围

- 钉钉登录、组织同步、钉钉通知和钉钉深链接全部延期；研究结论保留在 `docs/research/2026-07-30-dingtalk-app-provisioning-requirements.md`。
- 真实外部系统 API 接入延期到存在明确源系统、数据负责人和字段契约之后。
- 安全容量、备份恢复、离线发布和受控试用环境部署属于阶段7；正式生产切换在真实用户试用结论之后另行批准。

## 10. 阶段7：生产化准备与受控试用发布

**状态：** 范围、退出标准与任务级计划已确认（2026-07-30）；阶段6已GO，阶段7可以启动实施但尚未开始。

**任务级计划：** [`2026-07-30-phase-7-production-readiness-pilot-release.md`](../superpowers/plans/2026-07-30-phase-7-production-readiness-pilot-release.md)

**阶段终点：** 完成内网HTTPS受控试用环境、安全、容量、备份恢复、运行健康、离线发布、部署回滚与全链路回归，并批准约8名真实用户启动两周试用。阶段7 GO不等于试用完成或正式生产上线。

**访问与延期边界：** 无需公网IP，仅允许公司内网可信HTTPS入口；临时账号继续独立预置并禁止共享。钉钉登录/组织/通知/深链接及真实外部系统API仍延期，不得成为阶段7依赖或完成声明。

### Task 7.1：运行与恢复准备

- [ ] 建立6 vCPU/8GB受控试用拓扑、内网HTTPS、密钥引用和可重复部署。
- [ ] 实现最小披露运行看板、备份运行和恢复验证事实及授权API。
- [ ] 完成每日MySQL/文件备份、失败站内告警和隔离联合恢复。
- [ ] 证明RPO、RTO均不超过24小时，抽查业务记录与文件SHA-256一致。
- [ ] 完成会话、CSRF、权限、文件、凭据、依赖和日志脱敏安全专项。
- [ ] 在首期规模数据下通过既定p95、通知时效和错误率容量门槛。

### Task 7.2：离线发布、回滚和试用启动验收

- [ ] CI一次生成带版本、提交号、镜像摘要、迁移清单和SHA-256的离线发布包。
- [ ] 同一发布包先部署干净验证环境，再部署受控试用环境；禁止现场重新构建。
- [ ] 完成部署前备份、迁移、健康检查、核心冒烟、发布日志和应用包回滚演练。
- [ ] 回归阶段1—6、两条主链、四个重大阶段门、存量文件、站内通知和反馈闭环。
- [ ] 运行全量质量门禁并完成Spec/Standards双轴严格代码审核，P0/P1为零。
- [ ] 产品总监批准参与人、周期、数据范围、反馈R/A、停止条件和回滚方案后，阶段7才可GO并启动真实用户试用。
- [ ] 真实用户试用完成、反馈整改和正式生产上线另行验收与批准。

## 11. 全局完成标准

- 92项PRD/NFR需求均有代码、测试或配置证据；
- 四个重大阶段门均完成端到端验证；
- 新品和老品两条主链可运行；
- 未授权访问、下载、导出和通知被拒绝；
- 历史文件、产品版本、决策和快照不可覆盖；
- 同一关键命令重复执行不产生重复事实；
- 测试/受控试用环境、备份、恢复和离线发布均验证通过；
- 正式工程对旧原型零运行时依赖。
