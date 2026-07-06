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
