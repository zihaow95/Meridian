# Project Meridian 阶段0工程基础实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不实现任何业务域功能的前提下，建立可重复初始化、启动、测试、构建和持续集成的正式工程底座。

**Architecture:** 使用Django模块化单体和Vue 3单页应用；开发与测试依赖由Docker Compose提供MySQL和Redis，应用代码在宿主机运行；后端以OpenAPI作为前后端契约来源。阶段0只建立工程骨架、健康检查和质量门禁，不创建机会、产品、项目等业务模型。

**Tech Stack:** Python 3.13、uv、Django 5.2 LTS、Django REST Framework 3.16、MySQL 8.0、Redis、Vue 3、TypeScript、Vite、Element Plus、Node.js 24 LTS、npm、Docker Compose、pytest、Ruff、mypy、Vitest、Playwright、Gitee Go。

**Status:** 待执行

**Date:** 2026-07-06

---

## 1. 执行约束

- 工程根目录固定为`D:\Projects\Meridian`。
- 不复制、引用或兼容旧原型代码。
- 不创建业务表、业务状态机、正式身份认证或权限模型。
- Windows命令统一使用`npm.cmd`，避免PowerShell执行策略拦截`npm.ps1`。
- 当前系统Python 3.14不符合基线；必须由uv安装并固定Python 3.13。
- Docker daemon未运行时立即停止基础设施任务，不静默跳过。
- Gitee远端和Gitee Go尚未配置时，先完成本地质量门禁；CI任务必须明确记录为阻塞，不能宣称阶段0完成。
- 每个任务结束时执行对应验证并提交；任何失败都先修复再进入下一任务。

## 2. 阶段0完成定义

以下条件必须同时成立：

1. 新开发者只依据根目录`README.md`即可完成环境检查、安装依赖和启动空业务工程。
2. `uv run python --version`输出Python 3.13.x，`uv.lock`已提交。
3. `npm.cmd ci`可依据`package-lock.json`复现前端依赖。
4. Docker Compose可启动MySQL 8.0和Redis，并通过健康检查。
5. 后端`GET /api/v1/health`返回200及稳定JSON结构。
6. 前端可启动、类型检查、单元测试和生产构建。
7. OpenAPI文件可生成并通过校验，前端契约类型可重复生成。
8. `scripts\check.cmd`一次执行后端和前端全部门禁，退出码真实反映结果。
9. Gitee Go在分支或PR上自动执行同一组检查，并验证应用镜像可以构建。
10. `rg "npd-lcm-mvp|PLM-DMS|新品开发上市全生命周期管理系统" backend frontend deploy tests scripts`无旧工程引用。

## 3. Task 0.0：冻结正式基线并建立执行分支

**Files:**

- Verify: `.gitignore`
- Verify: `AGENTS.md`
- Verify: `README.md`
- Verify: `docs/`
- Verify: `references/`
- Verify: `scripts/`

- [ ] 确认当前仓库没有提交历史，且上述基线文件均为待跟踪文件。

```powershell
git status --short
git log --oneline -1
```

预期：第一条命令只显示已复制的正式文档包；第二条命令提示当前分支尚无提交。

- [ ] 检查仓库中不存在旧原型目录和旧工程引用。

```powershell
Get-ChildItem -Force
rg -n "npd-lcm-mvp|PLM-DMS" . --glob "!docs/superpowers/plans/2026-05-15-plm-dms-mvp.md"
```

预期：根目录无旧原型；搜索无结果。若旧计划文件存在，不纳入正式基线。

- [ ] 提交正式设计基线。

```powershell
git add .gitignore AGENTS.md README.md docs references scripts
git diff --cached --check
git commit -m "docs: establish Meridian design baseline"
git switch -c codex/phase-0-engineering-foundation
```

预期：形成首个基线提交并切换到阶段0分支。

## 4. Task 0.1：建立可失败的环境预检

**Files:**

- Create: `.python-version`
- Create: `scripts/preflight.ps1`
- Create: `scripts/preflight.cmd`
- Modify: `.gitignore`
- Modify: `README.md`

- [ ] 先执行人工预检并记录当前缺口。

```powershell
git --version
node --version
npm.cmd --version
uv --version
docker version
docker compose version
```

预期：Git和Node 24可用；首次执行时uv缺失、Docker daemon可能不可用。该失败是环境证据，不应绕过。

- [ ] 安装uv并固定Python 3.13。

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv python install 3.13
uv python pin 3.13
uv run python --version
```

预期：最后一条输出`Python 3.13.x`，并生成只包含`3.13`的`.python-version`。

- [ ] 编写`scripts/preflight.ps1`，逐项校验Git、uv、Python 3.13、Node 24、npm、Docker CLI、Compose和Docker daemon；任一项失败时输出明确原因并以非零码退出。
- [ ] 编写`scripts/preflight.cmd`，只负责用`powershell -NoProfile -ExecutionPolicy Bypass -File`调用同名PowerShell脚本并透传退出码。
- [ ] 在`.gitignore`中加入`.env`、`.venv/`、`node_modules/`、`dist/`、`htmlcov/`、`.pytest_cache/`、`.mypy_cache/`和本地上传目录。
- [ ] 在README记录支持版本、预检命令和Docker Desktop必须启动的前置条件。

```powershell
scripts\preflight.cmd
```

预期：环境齐备时退出码0；关闭Docker daemon后应明确失败且退出码非0。

- [ ] 提交。

```powershell
git add .python-version .gitignore README.md scripts/preflight.ps1 scripts/preflight.cmd
git commit -m "chore: add reproducible environment preflight"
```

## 5. Task 0.2：初始化后端并建立第一个测试闭环

**Files:**

- Create: `backend/pyproject.toml`
- Create: `backend/uv.lock`
- Create: `backend/manage.py`
- Create: `backend/config/settings/base.py`
- Create: `backend/config/settings/development.py`
- Create: `backend/config/settings/test.py`
- Create: `backend/config/settings/production.py`
- Create: `backend/config/urls.py`
- Create: `backend/config/wsgi.py`
- Create: `backend/config/asgi.py`
- Create: `backend/apps/platform/api/health.py`
- Create: `backend/tests/api/test_health.py`
- Create: `backend/pytest.ini`

- [ ] 初始化Python项目并锁定基线依赖。

```powershell
Set-Location backend
uv init --bare --python 3.13
uv add "Django>=5.2,<5.3" "djangorestframework>=3.16,<3.17" "drf-spectacular>=0.28,<0.29" "mysqlclient>=2.2,<2.3" "gunicorn>=23,<24"
uv add --dev "pytest>=8,<9" "pytest-django>=4.11,<5" "pytest-cov>=6,<7" "ruff>=0.12,<0.13" "mypy>=1.16,<2" "django-stubs>=5.2,<5.3" "djangorestframework-stubs>=3.16,<3.17"
uv lock --check
```

预期：生成`pyproject.toml`和`uv.lock`，且解释器约束为`>=3.13,<3.14`。

- [ ] 创建最小Django配置；开发、测试、生产设置均继承`base.py`。生产设置缺少`DJANGO_SECRET_KEY`、数据库或允许主机时必须启动失败。
- [ ] 先编写健康检查失败测试：

```python
@pytest.mark.django_db
def test_health_endpoint_exposes_no_sensitive_runtime_details(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "meridian-api"}
```

- [ ] 运行测试，确认因路由不存在而失败。

```powershell
uv run pytest tests/api/test_health.py -q
```

预期：失败，状态码为404；不得因测试未收集而“通过”。

- [ ] 实现只返回固定结构的健康检查并注册`/api/v1/health`，不返回版本、数据库地址、路径或密钥。
- [ ] 配置Ruff、mypy、pytest和覆盖率；测试设置默认读取MySQL测试库，不回退SQLite。

```powershell
uv run pytest tests/api/test_health.py -q
uv run ruff check .
uv run ruff format --check .
uv run mypy config apps
uv run python manage.py check --settings=config.settings.production --deploy
```

预期：前三项通过；生产部署检查只允许出现已明确记录、必须由反向代理或部署环境解决的警告，不能忽略错误。

- [ ] 提交。

```powershell
git add backend
git commit -m "chore: initialize Django application foundation"
```

## 6. Task 0.3：初始化前端并建立第一个组件测试

**Files:**

- Create: `frontend/`
- Modify: `frontend/package.json`
- Create: `frontend/src/app/App.vue`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/router/index.ts`
- Create: `frontend/src/stores/index.ts`
- Create: `frontend/src/app/App.spec.ts`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/eslint.config.js`

- [ ] 使用Vue TypeScript模板初始化，不接受React或JavaScript模板。

```powershell
npm.cmd create vite@latest frontend -- --template vue-ts
Set-Location frontend
npm.cmd install
npm.cmd install vue-router@4 pinia element-plus
npm.cmd install -D vitest @vue/test-utils jsdom eslint prettier vue-tsc
```

- [ ] 在`package.json`中建立`lint`、`format:check`、`typecheck`、`test:unit`和`build`脚本。
- [ ] 先编写组件测试，证明应用壳层必须显示正式项目名称：

```typescript
it('identifies the formal Meridian application', () => {
  const wrapper = mount(App)
  expect(wrapper.get('h1').text()).toBe('Project Meridian')
})
```

- [ ] 运行测试并确认默认Vite页面导致失败。

```powershell
npm.cmd run test:unit -- --run
```

- [ ] 删除Vite演示内容，实现最小应用壳层、路由入口和Pinia入口；不实现登录、菜单和业务页面。

```powershell
npm.cmd run lint
npm.cmd run format:check
npm.cmd run typecheck
npm.cmd run test:unit -- --run
npm.cmd run build
```

预期：全部退出码0，`dist/`不进入Git。

- [ ] 提交。

```powershell
git add frontend
git commit -m "chore: initialize Vue application foundation"
```

## 7. Task 0.4：建立MySQL和Redis本地基础设施

**Files:**

- Create: `.env.example`
- Create: `deploy/compose/compose.dev.yml`
- Create: `deploy/mysql/init/001-test-database.sql`
- Create: `storage/.gitkeep`
- Modify: `backend/config/settings/development.py`
- Modify: `backend/config/settings/test.py`
- Modify: `README.md`

- [ ] `.env.example`只包含开发占位值和变量说明，不包含真实凭据；开发者本地复制为`.env`。
- [ ] Compose仅启动`mysql`和`redis`两个依赖服务，设置健康检查、资源上限和命名卷，不在阶段0引入MinIO、Celery或Nginx。
- [ ] MySQL固定8.0主版本，启用`utf8mb4`、严格SQL模式和`READ-COMMITTED`；初始化脚本创建独立测试库并仅授予开发账号所需权限。
- [ ] Redis只绑定Compose网络和本机开发端口，不暴露到公司公网。

```powershell
Copy-Item .env.example .env
docker compose -f deploy/compose/compose.dev.yml --env-file .env config
docker compose -f deploy/compose/compose.dev.yml --env-file .env up -d
docker compose -f deploy/compose/compose.dev.yml --env-file .env ps
```

预期：配置无未解析变量；MySQL和Redis最终均为`healthy`。

- [ ] 验证后端迁移和测试确实使用MySQL。

```powershell
Set-Location backend
uv run python manage.py migrate --settings=config.settings.development
uv run pytest tests/api/test_health.py -q
```

预期：迁移成功；测试创建并清理独立MySQL测试库；日志中无SQLite连接。

- [ ] 在README记录启动、停止、清理和重新初始化开发依赖的命令；清理数据卷必须标记为破坏性操作，不放入日常启动脚本。
- [ ] 提交。

```powershell
git add .env.example deploy storage backend/config/settings README.md
git commit -m "chore: add local MySQL and Redis services"
```

## 8. Task 0.5：建立OpenAPI契约生成链

**Files:**

- Modify: `backend/config/settings/base.py`
- Modify: `backend/config/urls.py`
- Create: `backend/openapi/schema.yaml`
- Create: `backend/tests/api/test_openapi.py`
- Create: `frontend/src/api/generated/schema.d.ts`
- Modify: `frontend/package.json`

- [ ] 先编写契约测试，要求Schema包含健康检查且版本为`v1`。
- [ ] 配置drf-spectacular的Schema端点；文档页面仅在开发设置启用，生产默认关闭。
- [ ] 生成并校验Schema。

```powershell
Set-Location backend
uv run python manage.py spectacular --file openapi/schema.yaml --validate --settings=config.settings.test
uv run pytest tests/api/test_openapi.py -q
```

- [ ] 前端安装`openapi-typescript`并新增`api:generate`脚本，从已提交的`backend/openapi/schema.yaml`生成类型。

```powershell
Set-Location frontend
npm.cmd install -D openapi-typescript
npm.cmd run api:generate
git diff --exit-code -- src/api/generated/schema.d.ts
```

预期：重复生成不产生差异。

- [ ] 提交。

```powershell
git add backend frontend
git commit -m "chore: establish OpenAPI contract generation"
```

## 9. Task 0.6：建立统一质量门禁和镜像构建

**Files:**

- Create: `backend/Dockerfile`
- Create: `frontend/Dockerfile`
- Create: `deploy/nginx/default.conf`
- Create: `scripts/check.ps1`
- Create: `scripts/check.cmd`
- Create: `tests/e2e/package.json`
- Create: `tests/e2e/playwright.config.ts`
- Create: `tests/e2e/smoke.spec.ts`
- Modify: `README.md`

- [ ] 后端镜像使用Python 3.13基础镜像和`uv sync --locked --no-dev`，非root用户运行Gunicorn。
- [ ] 前端镜像分为Node构建阶段和Nginx运行阶段；运行镜像不包含源码和Node开发依赖。
- [ ] Playwright只建立健康页面烟雾测试，不实现业务E2E。
- [ ] `scripts/check.ps1`按顺序执行：

  1. 环境预检；
  2. Compose配置校验；
  3. 后端锁文件、Ruff、mypy、Django check、迁移漂移检查、pytest和OpenAPI漂移检查；
  4. 前端`npm ci`、lint、格式、类型、Vitest和build；
  5. 两个Docker镜像构建；
  6. 旧工程引用扫描。

- [ ] `scripts/check.cmd`透传PowerShell脚本退出码，任何子步骤失败时立即停止并显示失败步骤。

```powershell
scripts\check.cmd
```

预期：完整执行且退出码0；临时破坏任一测试后必须返回非零码，恢复后再次通过。

- [ ] 提交。

```powershell
git add backend frontend deploy tests scripts README.md
git commit -m "ci: add local quality gates and image builds"
```

## 10. Task 0.7：接入Gitee Go持续集成

**Files:**

- Create by Gitee Go: `.workflow/BranchPipeline.yml`
- Create by Gitee Go: `.workflow/PRPipeline.yml`
- Optional create by Gitee Go: `.workflow/MasterPipeline.yml`
- Modify after generation: corresponding `.workflow/*.yml`

- [ ] 先验证远端；若没有`origin`，停止并向仓库管理员取得正式Gitee仓库地址，不猜测地址。

```powershell
git remote -v
```

- [ ] 推送当前分支后，由仓库管理员在Gitee仓库中开通Gitee Go。流水线文件必须由Gitee Go生成到`.workflow/`，再基于实际插件格式修改，不预造未经平台验证的`.gitee/pipeline.yml`。
- [ ] 分支和PR流水线执行与`scripts\check.cmd`等价的Linux命令；使用Python 3.13和Node 24，依据`uv.lock`与`package-lock.json`安装。
- [ ] CI启动MySQL 8.0和Redis服务，运行后端MySQL测试，不使用SQLite替代。
- [ ] CI构建后端和前端镜像，但不推送公共镜像仓库、不部署服务器、不注入生产凭据。
- [ ] 在Gitee页面手工触发一次分支流水线，并通过一次故意失败验证门禁真实生效；修复后重新运行成功。
- [ ] 提交平台生成和已验证的流水线文件。

```powershell
git add .workflow
git commit -m "ci: add Gitee Go validation pipeline"
```

预期：Gitee Go分支流水线和PR流水线均有成功记录。若Gitee Go未开通，本任务及阶段0均保持未完成。

## 11. Task 0.8：形成阶段退出证据

**Files:**

- Create: `docs/implementation/phase-0-checkpoint.md`
- Modify: `docs/development/01-phased-implementation-plan.md`

- [ ] 在检查点文档记录提交哈希、工具版本、验证日期、完整命令、结果、Gitee构建链接和已知限制。
- [ ] 执行最终门禁。

```powershell
scripts\preflight.cmd
scripts\check.cmd
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-trd.ps1
git status --short
git log --oneline --decorate -10
```

预期：

- 三组检查全部退出码0；
- Git只显示本任务预期修改；
- 无跳过、`xfail`、静默重试或SQLite替代；
- 阶段检查点可追溯到具体提交和Gitee构建。

- [ ] 将主计划阶段0标记为已完成，并链接检查点文档。
- [ ] 提交。

```powershell
git add docs
git commit -m "docs: record phase 0 completion evidence"
```

## 12. 明确不在阶段0实现

- 钉钉认证、组织同步、RBAC、ABAC和审计；
- 提案、立案、立项、项目、产品档案和阶段门；
- 文件受控版本、NAS正式存储和下载票据；
- Celery任务、事件发件箱和通知；
- 业务菜单、生命周期看板和任何模拟业务数据；
- 测试环境部署、离线发布包、备份和恢复演练。

这些能力分别属于后续阶段。阶段0不得以“先搭通”为理由创建临时业务模型或不可复用的假实现。

## 13. 当前已知阻塞项

| 项目 | 当前状态 | 解除条件 | 是否阻塞阶段0完成 |
|---|---|---|---|
| uv | 未安装 | 按Task 0.1安装并验证 | 是 |
| Python 3.13 | 当前仅确认3.14 | 由uv安装并固定3.13 | 是 |
| Docker daemon | 最近检查未运行 | 启动Docker服务并通过预检 | 是 |
| Gitee远端 | 尚未确认 | 配置正式`origin` | 是 |
| Gitee Go | 尚未开通 | 管理员开通并生成`.workflow` | 是 |
| 私有镜像仓库 | 不提供 | 阶段0只验证构建，不推送镜像 | 否 |

