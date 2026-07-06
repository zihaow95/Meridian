# Project Meridian（经纬）

产品/项目全生命周期管理平台正式工程。

正式项目路径：

```text
D:\Projects\Meridian
```

## 当前状态

- 总体架构和技术架构已确认；
- 6份PRD已确认基线；
- 6份TRD已确认基线；
- TRD校验覆盖92项需求和4个重大阶段门；
- 四份开发前文档已完成；
- 正式Django/Vue工程尚未初始化。

## 文档入口

### 架构

- [产品全生命周期架构](docs/superpowers/specs/2026-06-26-product-lifecycle-architecture-design.md)
- [技术架构](docs/superpowers/specs/2026-06-30-technical-architecture-design.md)

### 产品需求

- [总体PRD](docs/prd/00-product-lifecycle-master-prd.md)
- `docs/prd/01`至`05`子PRD

### 技术设计

- [TRD索引](docs/trd/README.md)
- [TRD完整性审计](docs/trd/2026-06-30-trd-completeness-audit.md)

### 开发准备

- [开发就绪基线](docs/development/00-development-readiness-baseline.md)
- [分阶段实施计划](docs/development/01-phased-implementation-plan.md)
- [工程规范](docs/development/02-engineering-standards.md)
- [测试策略与质量门禁](docs/development/03-test-strategy-and-quality-gates.md)

## 开发环境

支持版本（由预检脚本校验）：

| 组件 | 版本要求 |
|---|---|
| Git | 2.x |
| uv | 0.11+ |
| Python | 3.13（由 uv 安装并固定，见 `.python-version`） |
| Node.js | 24 LTS |
| npm | 随 Node 24 |
| Docker Desktop | 提供 MySQL 8.0 与 Redis，运行前必须启动 daemon |
| Docker Compose | v2+ |

前置条件：Docker Desktop 必须处于运行状态，否则依赖 MySQL/Redis 的任务会失败。

首次准备 Python 运行时：

```powershell
uv python install 3.13
uv python pin 3.13
```

### 环境预检

```powershell
scripts\preflight.cmd
```

环境齐备时退出码为 0；缺失任一组件或 Docker daemon 未运行时，脚本会明确报出原因并以非零码退出。该失败是环境证据，不应绕过。

## 本地依赖服务（MySQL 与 Redis）

开发与测试依赖由 Docker Compose 提供，应用代码在宿主机运行。首次使用先复制环境模板：

```powershell
Copy-Item .env.example .env
```

启动依赖服务：

```powershell
docker compose -f deploy/compose/compose.dev.yml --env-file .env up -d
```

查看状态（等待 MySQL 与 Redis 均为 `healthy`）：

```powershell
docker compose -f deploy/compose/compose.dev.yml --env-file .env ps
```

停止服务（保留数据卷）：

```powershell
docker compose -f deploy/compose/compose.dev.yml --env-file .env down
```

首次启动会自动创建开发库 `meridian`、测试库 `meridian_test` 和开发账号。后端迁移与测试均在 MySQL 上执行，无 SQLite 回退：

```powershell
# 在 backend/ 目录，且 .env 变量已加载到当前会话
uv run python manage.py migrate --settings=config.settings.development
uv run pytest -q
```

> **破坏性操作**：以下命令会删除数据卷并清空开发数据库，仅在需要彻底重置时手动执行，不要放入日常启动流程。
>
> ```powershell
> docker compose -f deploy/compose/compose.dev.yml --env-file .env down -v
> ```

## 校验

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-trd.ps1
```

预期：

```text
TRD verification passed.
Documents: 6
Requirements traced: 92
Major stage gates: 4
```

## 工程边界

正式工程采用Python/Django + Vue 3 + MySQL 8.0模块化单体。

旧Node.js/SQLite/localStorage原型、旧MVP计划、Smoke截图和运行日志不属于本仓库正式基线，也不得成为构建、测试或部署依赖。

## 下一步

1. 确认并提交设计基线；
2. 编写Phase 0任务级实施计划；
3. 初始化`backend/`、`frontend/`、`deploy/`和`tests/`；
4. 建立CI、MySQL测试环境和质量门禁；
5. 开始平台内核和首个纵向业务切片。
