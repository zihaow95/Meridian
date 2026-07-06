# 阶段0 工程基础 —— 完成检查点

状态：已完成

日期：2026-07-06

分支：`main`（GitHub 为主，Gitee 为镜像）

对应计划：`docs/superpowers/plans/2026-07-06-phase-0-engineering-foundation.md`

## 1. 目标回顾

在不实现任何业务域功能的前提下，建立可重复初始化、启动、测试、构建和持续集成的正式工程底座。

## 2. 提交记录

阶段0 全部提交（在设计基线 `645cd9c` / `e44096c` 之上）：

| 提交 | 内容 |
|---|---|
| `d4caa2c` | chore: 可复现环境预检（preflight + Python 3.13 固定） |
| `0b1f0db` | chore: Django 应用骨架 + 健康检查 |
| `3310bea` | chore: Vue 应用骨架 |
| `a3e0eed` | docs: 目录级 Cursor 规则（backend/frontend/migrations） |
| `c5e6ec7` | chore: 本地 MySQL 与 Redis 服务 |
| `673a26a` | chore: OpenAPI 契约生成链 |
| `d65f1ac` | ci: 本地统一质量门禁与镜像构建 |
| `d2b157c` | ci: 从 Gitee Go 切换到 GitHub Actions |
| `b70b930` | chore: 通过 .gitattributes 强制 LF 行尾 |

## 3. 工具与运行时版本（本轮实际验证）

| 组件 | 版本 |
|---|---|
| Git | 2.54.0.windows.1 |
| uv | 0.11.26 |
| Python | 3.13.14（由 uv 安装并固定，见 `.python-version`） |
| Node.js | 24.17.0 |
| npm | 11.13.0 |
| Docker | 29.5.3 |
| Docker Compose | v5.1.4 |

关键依赖：Django 5.2.15、djangorestframework 3.16.1、drf-spectacular 0.28.0、mysqlclient 2.2.8、gunicorn 23；Vue 3.5、Vite 8、TypeScript 5.9.3、openapi-typescript 7.13.0、Element Plus、Pinia、vue-router 4、Vitest、Playwright。

## 4. 阶段0 完成定义对照

| # | 完成条件 | 状态 | 证据 |
|---|---|---|---|
| 1 | 新开发者依据 README 即可检查环境、装依赖、启动空业务工程 | 达成 | `README.md` 开发环境/依赖服务章节 |
| 2 | `uv run python --version` 为 3.13.x，`uv.lock` 已提交 | 达成 | `backend/uv.lock`、preflight |
| 3 | `npm ci` 可依据 `package-lock.json` 复现前端依赖 | 达成 | `check.cmd` step 11 |
| 4 | Docker Compose 启动 MySQL 8.0 与 Redis 且健康 | 达成 | `compose.dev.yml`、`docker compose ps` 均 healthy |
| 5 | `GET /api/v1/health` 返回 200 及稳定 JSON | 达成 | `backend/tests/api/test_health.py` |
| 6 | 前端可启动、类型检查、单元测试与生产构建 | 达成 | `check.cmd` step 12-16 |
| 7 | OpenAPI 可生成校验，前端契约类型可重复生成 | 达成 | `check.cmd` step 10、17 |
| 8 | `check.cmd` 一次执行前后端全部门禁，退出码真实 | 达成 | 见第 5 节 |
| 9 | CI 在分支/PR 自动执行同组检查并验证镜像可构建 | 达成 | GitHub Actions（见第 6 节） |
| 10 | 无旧工程引用 | 达成 | `check.cmd` step 20 legacy-scan |

## 5. 本地统一门禁（本轮实际运行并通过）

`scripts\check.cmd` 一次执行 20 个步骤，退出码 0：

环境预检 → Compose 配置校验 → 后端（锁文件、Ruff、格式、mypy、Django check、迁移漂移、pytest(MySQL)、OpenAPI 漂移）→ 前端（npm ci、lint、格式、类型、Vitest、build、契约类型漂移）→ 后端镜像构建 → 前端镜像构建 → 旧工程引用扫描。

门禁有效性已通过多次真实失败→修复→通过验证（Prettier 格式、扫描命令可用性、CRLF 行尾一致性），确认 fail-fast 生效、退出码真实反映结果。

其它本轮通过的校验：`scripts\preflight.cmd`（8 项全 OK）、`scripts\verify-trd.ps1`（6 文档 / 92 需求 / 4 阶段门）。

## 6. 持续集成（GitHub Actions，本轮实际运行并全绿）

工作流：`.github/workflows/ci.yml`，push 与 PR 自动触发，5 个 job 全部通过：

- `backend`：MySQL 8.0 + Redis 服务容器，uv 锁定安装、Ruff、mypy、Django check、迁移漂移、pytest、OpenAPI 漂移；
- `frontend`：Node 24、npm ci、lint、格式、类型、Vitest、build、契约类型漂移；
- `e2e`：Playwright 健康页面烟雾测试；
- `images`：构建前后端镜像（不推送）；
- `legacy-scan`：旧工程引用扫描。

## 7. 平台决策：从 Gitee Go 切换到 GitHub Actions

按 `AGENTS.md` 第 7 条显式处理冲突记录：

- 原因：Gitee Go 云端编译插件内置版本无法满足工程基线——`build@nodejs` 最高仅 Node 15.12.0、`build@python` 最高仅 Python 3.9，而本工程锁定 Node 24 / Python 3.13；且 Gitee Go 原生不支持声明式 MySQL/Redis 服务容器。
- 决策：CI 采用 GitHub Actions（原生支持 setup-node 24、uv 装 Python 3.13、`services:` 声明 MySQL/Redis、runner 自带 Docker），GitHub 为主仓库，Gitee 保留为镜像。
- 影响：删除 `.workflow/` 下 Gitee 流水线文件，新增 `.github/workflows/ci.yml`。

## 8. 明确不在阶段0实现（保持未实现）

钉钉认证/组织同步/RBAC/ABAC/审计；提案—立案—立项—项目—产品档案—阶段门等业务模型；文件受控版本/NAS/下载票据；Celery/事件发件箱/通知；业务菜单/看板/模拟数据；测试环境部署/离线发布/备份恢复。

## 9. 已知限制与后续

- Gitee 镜像同步：GitHub 为 CI 主平台；`gitee` 远端作镜像，按需 `git push gitee main`。
- CI 门禁的"故意失败"验证：门禁有效性已在本地通过多次真实失败充分验证；如需，可在 CI 上追加一次故意失败提交作为额外留痕。
- 阶段0 不含任何业务能力，后续阶段1（平台内核：身份、权限、审计、配置、文件、事件）按主计划推进。
