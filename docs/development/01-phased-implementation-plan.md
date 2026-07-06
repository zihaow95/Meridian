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

## 4. 阶段1：平台内核

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

目标：交付首个可供业务试用的提案—立案—立项闭环。

### Task 2.1：提案、成员和额度

**Files:**

- Create: `backend/apps/opportunities/`
- Create: `backend/tests/opportunities/`
- Create: `frontend/src/modules/opportunities/`

- [ ] 实现机会资产、提案版本、成员邀请和额度账。
- [ ] 实现资格、四项核心内容、公开摘要和撤回校验。
- [ ] 实现提案工作台、我的提案和额度提示。
- [ ] 覆盖OPP-001至OPP-005、OPP-015。
- [ ] 提交：`feat: add proposal submission workflow`

### Task 2.2：重大阶段门和拟立项方案

**Files:**

- Create: `backend/apps/stage_gates/`
- Create: `backend/tests/stage_gates/`
- Create: `frontend/src/modules/stage-gates/`

- [ ] 实现统一阶段门结果和不可变评审提交。
- [ ] 实现经管会整体结论、老板最终决策及差异展示。
- [ ] 实现待补充、暂缓、Pass和复议。
- [ ] 实现拟立项方案、合并、拆分和季度回看。
- [ ] 覆盖OPP-006至OPP-009、OPP-011至OPP-014。
- [ ] 提交：`feat: add opportunity stage gates`

### Task 2.3：原子创建项目和产品草稿

**Files:**

- Create: `backend/apps/projects/`
- Create: `backend/apps/products/`
- Test: `backend/tests/opportunities/test_project_creation.py`

- [ ] 编写重复立项和中途失败回滚测试。
- [ ] 实现项目基础记录、产品/变更草稿和模板运行时初始化。
- [ ] 建立机会—项目—产品来源关系。
- [ ] 实现生命周期看板首个版本。
- [ ] 覆盖OPP-010和GLB-001至GLB-003。
- [ ] 提交：`feat: create project and product draft atomically`

**阶段退出条件：**

- 产品经理和部门负责人可提交真实提案；
- 两个重大阶段门可完成决策；
- 立项通过只创建一个项目和正确产品草稿；
- 权限、文件版本和审计可完整追溯。

## 6. 阶段3：产品档案与存量迁移

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

## 9. 阶段6：正式集成和迁移

### Task 6.1：钉钉

**Files:**

- Modify: `backend/apps/identity/`
- Modify: `backend/apps/notifications/`
- Create: `backend/apps/integrations/dingtalk/`
- Create: `backend/tests/integrations/test_dingtalk.py`
- Modify: `frontend/src/modules/auth/`

- [ ] 接入钉钉企业认证、组织同步、通知和深链接。
- [ ] 移除生产环境本地登录能力。
- [ ] 验证停用用户、无权限深链接和通知脱敏。
- [ ] 提交：`feat: integrate dingtalk identity and notifications`

### Task 6.2：外部数据与迁移演练

**Files:**

- Modify: `backend/apps/integrations/`
- Create: `backend/tests/integrations/`
- Create: `scripts/migrate_legacy_data.py`
- Create: `scripts/reconcile_migration.py`

- [ ] 接入首批已确认数据源和字段映射。
- [ ] 执行存量产品、在途项目和经营数据迁移演练。
- [ ] 输出成功、失败、重复和待处理报告。
- [ ] 验证迁移可重复执行且不重复创建。
- [ ] 提交：`feat: add initial integrations and migration`

## 10. 阶段7：生产化和上线

### Task 7.1：安全、容量和恢复

**Files:**

- Create: `tests/performance/`
- Create: `tests/security/`
- Create: `scripts/backup/`
- Create: `scripts/restore/`
- Create: `docs/operations/recovery-runbook.md`

- [ ] 完成权限矩阵回归、会话、CSRF、文件和凭据检查。
- [ ] 在6 vCPU、8GB限制下执行容量测试。
- [ ] 验证每日数据库与文件备份。
- [ ] 在隔离环境完成数据库和NAS联合恢复。
- [ ] 证明RPO和RTO不超过24小时。
- [ ] 提交：`test: verify security capacity and recovery`

### Task 7.2：离线发布和业务验收

**Files:**

- Modify: `.gitee/pipeline.yml`或Gitee实际流水线配置文件
- Create: `scripts/build-release-package.ps1`
- Create: `scripts/deploy-release.ps1`
- Create: `docs/operations/release-runbook.md`
- Create: `docs/acceptance/first-release.md`

- [ ] CI生成带版本、提交号和SHA-256的离线发布包。
- [ ] 同一发布包先部署测试环境。
- [ ] 完成新品、老品迭代、退市和迁移端到端验收。
- [ ] 人工批准并部署生产。
- [ ] 验证健康检查、回滚和发布日志。
- [ ] 提交：`release: prepare first production baseline`

## 11. 全局完成标准

- 92项PRD/NFR需求均有代码、测试或配置证据；
- 四个重大阶段门均完成端到端验证；
- 新品和老品两条主链可运行；
- 未授权访问、下载、导出和通知被拒绝；
- 历史文件、产品版本、决策和快照不可覆盖；
- 同一关键命令重复执行不产生重复事实；
- 测试、生产、备份、恢复和离线发布均验证通过；
- 正式工程对旧原型零运行时依赖。
