# Project Meridian 阶段7生产化准备与受控试用发布实施计划

> **For agentic workers:** 本计划由规划/审核代理维护；当前代理不执行开发。每个任务由独立实现任务调用 `/implement` 并严格测试先行，每个PR完成后提交当前代理调用 `/code-review`。验收发现由实现方整改，审核方复验；未经 Task 7.8 全量门禁、恢复演练、双轴审阅和阶段检查点，不得宣布阶段7完成。

**Goal:** 在阶段6 GO基线上，完成内网受控试用环境、安全加固、运行健康、数据库与文件联合备份恢复、6 vCPU/8GB容量验证、可追溯离线发布包、部署回滚和全链路回归，形成允许约8名真实用户启动两周试用的GO/NO-GO证据。

**Architecture:** 保持Django模块化单体和现有Vue SPA。受控试用环境通过内网HTTPS反向代理统一暴露前后端；MySQL、受控文件和审计是唯一业务事实，Redis/Celery可重建。`platform`域保存备份运行与恢复验证事实并提供最小披露运行看板；脚本执行可重复的备份、隔离恢复、发布和回滚，CI只构建一次带摘要的离线包，同一包进入受控试用环境。

**Tech Stack:** Python 3.13、Django 5.2、DRF 3.16、MySQL 8.0、Redis、Celery 5.6、Vue 3、TypeScript、Vitest、Playwright、OpenAPI 3、Docker Compose、Nginx、PowerShell。

**Status:** 阶段6已在`e26c553`记录当时GO（功能整改截至`62ffea3`）；本计划已于2026-08-06按实际代码重审，Task 7.0—7.8尚未开始。后续提交不自动继承该GO，阶段7开工提交由Task 7.0 fresh gate后另行固定。

**Date:** 2026-07-30；最近重审：2026-08-06

**Authoritative sources:** `README.md`; `docs/development/00-development-readiness-baseline.md`; 六份PRD/TRD，重点为PRD/TRD 05；`docs/development/02-engineering-standards.md`; `docs/development/03-test-strategy-and-quality-gates.md`; `docs/implementation/phase-6-checkpoint.md`; 阶段6任务级计划；当前Meridian代码。

## 1. 职责边界与执行基线

- 正式仓库固定为 `D:\Projects\Meridian`；`e26c553`只作为阶段6历史GO证据。Task 7.0必须在拟开工的单一精确提交上重跑基线门禁，通过后记录该提交并从它创建`codex/phase-7-production-readiness-pilot-release`。
- 当前规划/审核代理只维护计划、审阅实现、复验门禁并给出GO/NO-GO，不承担Task 7.0—7.8开发，不在验收任务中直接修复代码。
- 每个实现PR必须提供基线提交、变更范围、测试命令和结果；审核按Spec与Standards双轴给出P0—P3 findings，实现方整改后重新送审。
- 阶段7终点是“受控试用环境可用且批准启动真实用户试用”，不是“真实用户试用完成”，也不是“正式生产上线”。
- 无需公网IP；受控试用只允许公司内网入口。真实用户凭据不得经明文HTTP传输，内网HTTPS证书或等效可信终止是GO前置条件。
- 阶段6已有`scripts/start-pilot.ps1`提供开发设置下的临时HTTP局域网入口，可用于非敏感内部演示和技术联调；它不满足Task 7.1的HTTPS、安全设置、资源约束和可重复部署门禁，不得作为阶段7环境验收证据。
- 阶段6临时账号继续仅用于受控试用，独立账号、禁止共享、可停用、全量登录审计；`production`设置仍必须拒绝该登录能力。
- 钉钉登录、组织同步、通知、深链接和真实外部系统API全部延期，不进入本阶段依赖、健康门禁或完成声明。
- 不建设Kubernetes、Harbor、微服务、通用监控平台或第二套业务数据写入口。
- 开工前保留既有工作区修改；不得使用reset、checkout或覆盖式清理用户文件。

## 2. 当前代码基线与冲突裁决

- 已有`production.py`强制密钥、允许主机、MySQL凭据、HTTPS、安全Cookie、HSTS和开发登录关闭；阶段7补受控试用设置和部署验证，不复制安全配置。
- 阶段6已经交付独立试用账号、登录审计、试用批次/反馈闭环、局域网启动脚本和操作手册；阶段7复用这些业务能力，不再新建第二套账号、反馈或临时启动机制。
- `/api/v1/health`是公开、无敏感信息的存活探针；TRD要求的授权运行看板、备份记录和恢复验证API尚未实现，两者保持分离。
- `platform`目前只有抽象模型和基础API，没有迁移；阶段7由该域拥有`BackupRun`与`RestoreVerification`，首个迁移为`platform/0001_runtime_operations.py`。
- `authorization`当前最新迁移为0013；阶段7动作种子使用0014。`products`已到0018，但不改变`platform`和`authorization`的计划编号。
- 开发Compose只有MySQL/Redis，Nginx只服务SPA；阶段7新增独立受控试用Compose与代理配置，不改变开发环境行为。
- 当前CI可执行后端、前端、OpenAPI、E2E和镜像构建，但不生成可验证离线包，也没有发布、备份、恢复和回滚脚本。
- 当前`scripts\check.cmd`是本地全量权威门禁；阶段7扩展其覆盖，但发布验收不得只引用历史CI或阶段6结果。
- 原主计划中的“阶段7部署生产”与“阶段7 GO后才启动真实用户试用”冲突；以最新确认边界为准：先发布受控试用环境，真实试用完成后另行作正式生产决策。

## 3. 完成定义

1. 同一受控试用拓扑可在内网HTTPS入口重复部署，服务、资源限制、数据卷、密钥引用和防火墙边界明确。
2. 公开健康探针不泄密；授权运行看板显示MySQL、Redis、Celery、文件存储、通知、备份和恢复摘要。
3. MySQL和受控文件每日备份到独立位置，带不可变清单、SHA-256、保留期、失败记录和站内告警。
4. 在隔离环境完成数据库与文件联合恢复，抽查产品、项目、决策、文件记录和文件哈希，证明RPO/RTO均不超过24小时。
5. 会话、CSRF、安全响应头、临时认证、默认拒绝、文件权限、日志脱敏、密钥和依赖检查通过。
6. 在总上限6 vCPU/8GB、接近首期规模的数据下达到API、看板、通知、文件和错误率目标。
7. CI一次构建离线发布包，包内包含版本、提交、镜像摘要、迁移清单和SHA-256且不含密钥、业务数据或备份。
8. 同一发布包完成受控试用环境部署、健康检查、迁移和回滚演练，发布日志可追溯。
9. 阶段1—6两条主链、四个重大阶段门、存量产品/文件、站内通知和反馈闭环回归通过。
10. 约8人、两周的真实用户试用启动包获产品总监批准；P0/P1为零，P2按门禁书面接受。

## 4. 需求与任务映射

| 范围 | 任务 |
|---|---|
| 阶段6交接、证据矩阵和受控试用输入 | Task 7.0 |
| 内网HTTPS、资源约束、密钥和可重复部署 | Task 7.1 |
| 运行健康、备份/恢复事实、权限和管理API | Task 7.2 |
| 数据库/文件备份、清单、失败告警 | Task 7.3 |
| 隔离联合恢复、完整性抽查、RPO/RTO | Task 7.4 |
| 安全专项与依赖/凭据检查 | Task 7.5 |
| 6 vCPU/8GB容量与性能 | Task 7.6 |
| 离线包、同包部署、健康与回滚 | Task 7.7 |
| 全链路回归、严格代码审阅、GO与试用启动包 | Task 7.8 |

基线需求映射：

| PRD/TRD需求 | 阶段7覆盖 |
|---|---|
| PLT-003、PLT-005、PLT-007、PLT-013 | 默认拒绝、敏感动作、双人复核和审计失败可见 |
| PLT-010、PLT-011、PLT-015、PLT-016 | 文件/通知运行保障、联合备份恢复和单组织边界 |
| NFR容量与性能 | 200用户、10个并行项目、首年规模数据和既定p95/错误率 |
| 工程标准与质量门禁 | 可重复构建、迁移、OpenAPI、E2E、覆盖率、发布与回滚证据 |

## 5. 数据迁移和部署顺序

1. 阶段6全部迁移及检查点GO。
2. `platform/0001_runtime_operations.py`。
3. `authorization/0014_seed_runtime_operations_actions.py`。
4. 在空库和阶段6数据库副本分别验证迁移。
5. 构建一次离线发布包并记录摘要。
6. 备份受控试用目标后部署同一包、执行迁移和健康检查。
7. 失败时按已演练步骤回滚应用包；涉及不可逆数据迁移则停止，不得伪装自动回滚。

迁移不得把备份文件、密钥或完整错误堆栈写入数据库；只保存位置引用、摘要、校验值和脱敏错误。恢复验证只引用已完成备份，不修改备份运行事实。

## 6. PR拆分

| PR | 范围 | 独立验收结果 |
|---|---|---|
| PR1 | Task 7.0—7.1 | 阶段6交接、内网受控试用拓扑和安全配置 |
| PR2 | Task 7.2 | 运行事实、权限、API和管理看板 |
| PR3 | Task 7.3 | 数据库/文件备份、清单和失败告警 |
| PR4 | Task 7.4 | 隔离联合恢复与RPO/RTO证据 |
| PR5 | Task 7.5 + Task 7.6测试工具 | 安全专项、可重复容量种子与压测工具；此时的试跑不构成正式容量验收 |
| PR6 | Task 7.7 + Task 7.6正式运行 | 可追溯离线包、同包部署、在该候选包上完成正式容量判定和回滚 |
| PR7 | Task 7.8 | 全链路回归、终审、阶段7检查点和试用启动批准 |

## 7. Task 7.0：建立阶段7执行与验收基线

**Files:** Create `docs/implementation/phase-7-test-matrix.md`; Modify `README.md`, `docs/development/01-phased-implementation-plan.md`.

**Interfaces and direct callers:** Consumes `phase-6-checkpoint.md`、`phase-6-test-matrix.md`和阶段6最终提交；produces阶段7需求—实现—测试—运行证据矩阵，供所有PR和Task 7.8使用。

- [ ] 只有阶段6检查点明确GO、P0/P1为零且未决P2已书面接受时建立阶段7分支。
- [ ] 在实际阶段7检出运行`scripts\check.cmd`和`scripts\verify-trd.ps1`，不复用历史结果冒充本轮基线。
- [ ] 固定目标主机、6 vCPU/8GB资源边界、内网地址、证书负责人、备份独立位置和恢复隔离位置；缺少项明确标记阻塞。
- [ ] 测试矩阵覆盖安全、容量、备份、恢复、运行健康、离线包、部署、回滚、全链路E2E和代码审阅。
- [ ] 提交：`docs: establish phase 7 readiness baseline`。

## 8. Task 7.1：内网受控试用拓扑与安全配置

**Files:** Create `backend/config/settings/pilot.py`, `deploy/compose/compose.pilot.yml`, `deploy/nginx/pilot.conf`, `deploy/env/pilot.env.example`, `docs/operations/pilot-deployment-runbook.md`; Modify `backend/config/settings/production.py`, `backend/tests/identity/test_production_auth_settings.py`, `backend/tests/identity/test_pilot_auth_settings.py`, `backend/Dockerfile`, `frontend/Dockerfile`.

**Interfaces and direct callers:** `compose.pilot.yml`启动Nginx、backend、Celery worker/beat、MySQL、Redis和受控文件卷；Nginx调用公开`/api/v1/health`，浏览器统一通过内网HTTPS访问SPA和`/api/v1`。

- [ ] 资源限制总和不超过6 vCPU/8GB；MySQL、Redis和应用端口不直接暴露公司网络。
- [ ] `pilot.py`复用安全基线并对密钥、主机、数据库、文件根目录和认证开关fail closed；`production.py`继续拒绝临时登录。
- [ ] 环境样例只包含变量名和安全说明；真实密钥、证书、凭据、备份位置和业务数据不得进入Git或发布包。
- [ ] 代理设置可信转发头、请求体上限、安全头和API路由；公开健康响应保持最小披露。
- [ ] 执行Compose配置校验、镜像非root检查、服务启动、重启和数据卷持久性测试。
- [ ] 提交：`ops: add controlled pilot topology`。

## 9. Task 7.2：运行健康、备份与恢复事实

**Files:** Create `backend/apps/platform/models/runtime.py`, `backend/apps/platform/migrations/0001_runtime_operations.py`, `backend/apps/platform/services/backup_runs.py`, `backend/apps/platform/services/restore_verifications.py`, `backend/apps/platform/queries/runtime_health.py`, `backend/apps/platform/api/runtime.py`, `backend/apps/platform/api/urls.py`, `backend/apps/authorization/migrations/0014_seed_runtime_operations_actions.py`, `backend/tests/platform/test_runtime_operations.py`, `backend/tests/platform/test_runtime_health_api.py`, `frontend/src/modules/admin/RuntimeHealthView.vue`, `frontend/src/modules/admin/RuntimeHealthView.spec.ts`; Modify `backend/apps/platform/models/__init__.py`, `backend/apps/authorization/actions.py`, `backend/config/urls.py`, `frontend/src/router/index.ts`.

**Interfaces and direct callers:** `BackupRun`由备份命令写入；`RestoreVerification`只引用已完成备份；`GET /api/v1/admin/runtime-health`、`GET /api/v1/admin/backups`、`POST /api/v1/admin/restore-verifications`由授权管理页调用。

- [ ] 保存类型、范围、开始/结束、状态、大小、SHA-256、位置引用、保留期和脱敏错误；记录不可原位覆盖。
- [ ] 恢复记录保存数据库/文件备份、隔离环境、抽查计数、一致性、耗时、RPO/RTO、执行人和整改状态。
- [ ] 动作码至少包含`platform.runtime_health.read`、`platform.backup.read`和`platform.restore_verification.record`，默认拒绝且写操作事务内复核。
- [ ] 运行看板汇总MySQL、Redis、Celery积压/失败、文件挂载/容量/巡检、站内通知失败、最近备份和最近恢复；不纳入已延期钉钉/外部API。
- [ ] 普通用户、平台管理员和具备专项业务角色者分别验证；详情不得泄露路径、凭据、文件名、SQL或堆栈。
- [ ] 提交：`feat: record and expose runtime readiness`。

## 10. Task 7.3：数据库与受控文件备份

**Files:** Create `backend/apps/platform/management/commands/run_backup.py`, `backend/tests/platform/test_backup_command.py`, `scripts/backup/backup-database.ps1`, `scripts/backup/backup-files.ps1`, `scripts/backup/run-backup.ps1`, `scripts/backup/verify-backup-manifest.ps1`, `docs/operations/backup-runbook.md`; Modify `backend/apps/notifications/services/notifications.py`, `backend/config/settings/base.py`.

**Interfaces and direct callers:** 操作系统计划任务调用`run-backup.ps1`；脚本调用数据库/文件备份工具并生成清单，管理命令记录`BackupRun`；失败通过阶段6站内通知服务告警系统管理员。

- [ ] 每日数据库与文件备份写入独立位置；同一运行使用唯一运行号，重试不覆盖既有成功备份。
- [ ] 清单列出类型、时间、范围、大小、SHA-256、工具版本和文件相对引用；禁止记录密钥或明文凭据。
- [ ] 数据库备份使用一致性选项；文件备份与数据库切点关系写入清单，偏差用于计算RPO。
- [ ] 成功前验证文件存在、非零、摘要匹配和可读取；部分成功不得标记整体成功。
- [ ] 失败记录脱敏错误并创建站内告警，告警失败不吞掉备份失败；退出码非零。
- [ ] 保留与清理仅删除已过期且不被恢复验证/保留策略引用的备份，先提供dry-run。
- [ ] 提交：`ops: automate governed backups`。

## 11. Task 7.4：隔离联合恢复与RPO/RTO证明

**Files:** Create `backend/apps/platform/management/commands/verify_restored_state.py`, `backend/tests/platform/test_restore_verification.py`, `scripts/restore/restore-isolated.ps1`, `scripts/restore/verify-restored-state.ps1`, `deploy/compose/compose.restore.yml`, `docs/operations/recovery-runbook.md`.

**Interfaces and direct callers:** `restore-isolated.ps1`只接受显式备份清单和隔离目标，调用MySQL/文件恢复；`verify_restored_state`只读抽查恢复库和文件并记录`RestoreVerification`。

- [ ] 恢复脚本拒绝生产/受控试用活动路径、空路径、根目录和未通过摘要校验的备份。
- [ ] 在隔离MySQL实例和独立文件根目录联合恢复，不覆盖源备份或活动环境。
- [ ] 抽查产品、版本、SKU、渠道、项目、重大决策、审计、文件记录和实际文件；文件SHA-256一致。
- [ ] 记录备份切点、故障假设、开始/完成、RPO、RTO、缺失/孤立对象和整改。
- [ ] 至少演练一次成功恢复和一次损坏/缺失备份的安全失败；过程不依赖个人记忆。
- [ ] 只有RPO/RTO均≤24小时且无不可解释不一致时通过。
- [ ] 提交：`test: prove joint restore objectives`。

## 12. Task 7.5：安全专项与凭据边界

**Files:** Create `backend/tests/security/test_session_csrf_headers.py`, `backend/tests/security/test_runtime_admin_permissions.py`, `backend/tests/security/test_file_access_boundaries.py`, `backend/tests/security/test_pilot_auth_boundaries.py`, `scripts/security/check-repository-secrets.ps1`, `docs/implementation/phase-7-security-report.md`; Modify `.github/workflows/ci.yml`, `scripts/check.ps1`.

**Interfaces and direct callers:** CI和`scripts\check.cmd`调用安全测试与密钥扫描；安全报告引用实际提交、工具版本、命令和发现处置。

- [ ] 验证会话固定攻击防护、CSRF、Cookie、安全响应头、HTTPS转发和未授权信息最小披露。
- [ ] 对管理API、运行详情、文件预览/下载、通知深链和反馈证据执行允许/拒绝/越界/撤权即时生效矩阵。
- [ ] 证明临时认证只能在受控试用设置开启，停用用户立即拒绝，production和默认配置fail closed。
- [ ] 扫描Git跟踪文件、环境样例和离线包中的高风险密钥模式；命中必须人工判定并留证。
- [ ] 对Python和npm锁文件执行可复现依赖漏洞检查；高严重度未处置问题阻止GO。
- [ ] 日志、错误和审计断言不得包含密码、Cookie、Secret、数据库凭据、绝对文件路径或敏感正文。
- [ ] 提交：`test: enforce phase 7 security gates`。

## 13. Task 7.6：6 vCPU/8GB容量与性能验证

**Files:** Create `tests/performance/run_capacity.py`, `tests/performance/scenarios.py`, `tests/performance/README.md`, `backend/apps/identity/management/commands/seed_phase7_capacity.py`, `backend/tests/identity/verify_phase7_capacity_seed.py`, `docs/implementation/phase-7-capacity-report.md`; Modify `deploy/compose/compose.pilot.yml`, `.github/workflows/ci.yml`.

**Interfaces and direct callers:** 可重复容量种子生成接近首期规模数据；`run_capacity.py`通过公开API施加确定性并发场景并输出机器可读结果，报告引用原始结果和环境资源快照。

- [ ] 数据包含200用户、10个并行项目、产品/版本/SKU/渠道/文件元数据和首年经营事实估算；不提交真实业务文件。
- [ ] 种子重复执行保持行级稳定，不污染受控试用正式验收数据。
- [ ] 覆盖普通列表/详情、业务写入、生命周期/产品看板、通知可见和配置上限内文件流式传输。
- [ ] 门槛：列表/详情p95≤1秒，写入p95≤2秒，看板p95≤2秒，通知≤60秒，稳态服务端错误率<0.5%。
- [ ] 在Compose总限制6 vCPU/8GB下记录并发、持续时间、吞吐、p50/p95/p99、错误率、CPU、内存和数据库连接。
- [ ] 正式容量证据必须在Task 7.7生成并部署的同一候选发布包上执行；源码环境或更早镜像的结果只能作为调试证据。
- [ ] 预热与正式样本分离；失败阈值不得通过删样本、降低并发或重跑挑选最好结果掩盖。
- [ ] 提交：`test: verify first release capacity`。

## 14. Task 7.7：离线发布包、同包部署与回滚

**Files:** Create `scripts/release/build-release-package.ps1`, `scripts/release/verify-release-package.ps1`, `scripts/release/deploy-release.ps1`, `scripts/release/rollback-release.ps1`, `deploy/release/manifest.schema.json`, `docs/operations/release-runbook.md`; Modify `.github/workflows/ci.yml`, `scripts/check.ps1`, `docs/implementation/phase-7-capacity-report.md`.

**Interfaces and direct callers:** CI调用构建脚本一次生成包和SHA-256；部署脚本只接受验证通过的包；回滚脚本使用上一已知良好包和部署前备份。

- [ ] 包含后端/前端镜像、受控试用Compose/代理配置、迁移与运维脚本、版本、提交号、镜像摘要、文件清单和总包SHA-256。
- [ ] 排除`.env`、密钥、证书私钥、上传文件、数据库、备份、测试真实数据、缓存和开发依赖。
- [ ] 未提交工作树、摘要不匹配、清单不完整、镜像架构不符或来源提交未知时拒绝构建/部署。
- [ ] 同一包先在干净验证环境部署，再部署受控试用环境；禁止现场重新构建或替换包内文件。
- [ ] 干净环境部署成功后，以该包作为Task 7.6正式容量运行的唯一应用来源；容量失败后不得替换镜像继续沿用原包摘要。
- [ ] 先冻结候选代码提交和发布包SHA，再保存不可变的容量原始结果；容量报告以单独证据提交引用候选提交、包SHA、镜像摘要、环境快照和原始结果位置，不重新构建候选包。
- [ ] 部署前备份，执行迁移、健康检查、核心冒烟和发布日志；任一步失败停止并给出可见状态。
- [ ] 回滚至少演练应用包回退；数据库迁移若不可逆，发布前必须提供兼容策略或阻止发布。
- [ ] 提交：`release: build reproducible pilot package`。

## 15. Task 7.8：全链路回归、严格验收与阶段7 GO

**Files:** Create `tests/e2e/phase-7-release-readiness.spec.ts`, `docs/implementation/phase-7-checkpoint.md`, `docs/acceptance/real-user-pilot-start.md`; Modify `docs/implementation/phase-7-test-matrix.md`, `README.md`, `docs/development/01-phased-implementation-plan.md`, `docs/development/03-test-strategy-and-quality-gates.md`.

**Interfaces and direct callers:** `scripts\check.cmd`是代码全量门禁；备份/恢复、容量、安全、发布和回滚脚本提供运行证据；检查点汇总所有PR审阅与真实命令。

- [ ] 从空库和阶段6数据库副本迁移，执行阶段1—6全量回归及四个重大阶段门、两条主链。
- [ ] E2E覆盖新品、存量老品、文件历史/待整理、专业确认、站内通知、反馈闭环、运行看板和权限撤销。
- [ ] 执行格式、静态、类型、MySQL、OpenAPI、前端、E2E、Docker、覆盖率、安全、容量、备份、恢复、同包部署和回滚门禁。
- [ ] 当前审核代理逐PR及最终差异执行Spec/Standards双轴审阅；不在审核中直接修代码，所有finding由实现方整改后复验。
- [ ] 测试矩阵区分本轮实跑、历史记录、未执行和环境阻塞；禁止用文档记录替代本轮证据。
- [ ] 检查点列出提交、发布包SHA、目标环境、备份/恢复记录、RPO/RTO、容量结果、审阅发现、缺陷和已知限制。
- [ ] 检查点分别记录候选代码提交和后续证据提交；容量、部署、回滚证据必须回指同一候选包SHA，不能用证据提交的HEAD冒充候选来源。
- [ ] P0/P1必须为零；P2只有明确规避、负责人和期限且经项目负责人书面接受才可GO。
- [ ] 产品总监批准约8人、两周、人员范围、数据边界、反馈R/A、停止条件和回滚方案后，才允许启动真实用户试用。
- [ ] 明确阶段7 GO不代表真实试用完成或正式生产上线；试用结论另行形成验收决策。
- [ ] 提交：`docs: record phase 7 readiness acceptance`。

## 16. 阶段7必须覆盖的权限与审计

- 运行健康查看、备份记录查看、恢复验证记录；
- 受控试用用户预置、停用和登录；
- 高敏文件预览、原件下载、通知深链和反馈证据；
- 发布、部署、回滚和恢复执行人的操作留痕；
- 每项至少包含允许、拒绝、跨组织、对象范围变化后立即拒绝和审计断言。

平台管理员可维护环境和查看脱敏运行状态，但除非另有业务角色或专项授权，不得读取高敏产品材料、通知正文或反馈证据。操作系统脚本身份只拥有所需最小数据库/文件权限，不等同平台超级管理员。

## 17. 阶段7停止条件

- 阶段6不是明确GO或存在未关闭P0/P1；
- 需要把临时认证开放公网、以HTTP传输真实用户凭据或在production启用；
- 备份与活动数据位于同一故障域，或恢复只能覆盖活动环境；
- 数据库与文件切点无法关联、摘要不匹配或存在不可解释缺失；
- 容量环境超过6 vCPU/8GB，或通过降低既定负载规避阈值失败；
- 发布包包含密钥、真实业务数据、备份或来源不明文件；
- 部署使用的包与验证包摘要不同，或失败后继续宣称成功；
- 高严重度安全问题、P0/P1、失败/跳过门禁未闭环；
- 钉钉、公网或真实外部API被当作阶段7前置依赖；
- 要求在阶段7 GO前启动真实用户试用，或把GO写成正式生产上线。

## 18. 严格代码审核与复验协议

1. 审核范围固定为阶段6 GO提交到待验收提交的差异，并核对未提交文件、迁移和生成契约。
2. 先按计划与PRD/TRD审Spec，再按工程标准审权限、事务、并发、幂等、审计、迁移、错误、测试和运维安全。
3. findings必须含等级、文件/行、触发场景、业务风险和修复要求；无证据不得判通过。
4. 审核代理不直接修改实现；实现方在独立开发任务整改并提供新提交和测试证据。
5. 复验先跑受影响测试，再跑全量门禁；旧结果、局部通过或“理论上可行”不能关闭finding。
6. 只有P0/P1为零、P2已按规则处置、所有必需门禁本轮通过，才可签署GO。

## 19. 明确延期到阶段7以后

- 钉钉身份认证、组织同步、通知、深链接，以及是否删除临时本地登录；
- 真实ERP、MES、WMS、销售/BI、财务等外部系统API；
- 公网入口、多组织、移动端、Kubernetes、Harbor和通用监控平台；
- 真实用户两周试用的执行、反馈整改和最终业务验收；
- 正式生产切换、生产数据迁移和面向全员推广。

## 20. 阶段7退出证据

- `docs/implementation/phase-7-test-matrix.md`与`phase-7-checkpoint.md`；
- 阶段6 GO基线、阶段7分支和最终提交范围；
- 空库及阶段6副本迁移、全量`scripts\check.cmd`和`scripts\verify-trd.ps1`；
- 安全报告、容量报告及原始机器可读结果；
- 数据库/文件备份清单、摘要、失败告警和隔离恢复记录；
- RPO/RTO、业务对象抽查和文件SHA-256一致性；
- 离线发布包清单、总包SHA、同包部署、健康检查、发布日志和回滚证据；
- Spec/Standards双轴代码审阅、整改和复验记录；
- `docs/acceptance/real-user-pilot-start.md`及产品总监批准；
- 明确结论：阶段7 GO或NO-GO；GO仅允许启动真实用户试用，不等于试用完成或正式生产上线。
