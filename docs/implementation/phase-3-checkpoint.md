# 阶段3 产品档案与存量迁移 —— 完成检查点

日期：2026-07-13

状态：已通过（2026-07-13 审查阻断项修复后）

对应计划：`docs/superpowers/plans/2026-07-09-phase-3-product-profile-migration.md`

对应测试矩阵：`docs/implementation/phase-3-test-matrix.md`

## 已交付能力概览

- **产品主模型**：`ProductAsset`、`ProductVersion`、`SKU`、`ChannelConfiguration`、`ProductChangeSet`；`ProductDraft` 兼容代理
- **属性 Schema**：版本化定义、变更集编辑、差异、确认、营养/素材校验
- **发布**：`ValidateProductPublication`（含生效时间、渠道 SKU、范围冲突）+ `PublishProductChangeSet`（渠道无效数据显式失败）
- **权限边界**：变更集详情/差异要求 `product.read_basic`；提交用 `product_draft.submit`，批准用 `product_change_set.approve`（禁止自批）
- **写命令规范**：范围更新与外部绑定均含授权、审计、outbox
- **查询 API**：产品搜索/详情（含外部绑定）、变更集详情/差异/编辑/范围/提交/批准/预检/发布
- **存量导入**：CSV 解析、重复候选人工决策、确认导入、基线发布
- **PIM-013**：外部绑定 upsert API + 产品详情展示 + 前端入口
- **前端**：列表、详情（外部绑定）、变更集（范围/提交/批准/发布）、导入（决策/确认/发布）
- **验收**：后端验收测试 + Playwright 导航与导入发布可搜索闭环

## 数据库迁移（阶段3）

| 应用 | 迁移 |
|---|---|
| `products` | `0003_product_profile_core` … `0009_mysql_candidate_uniqueness` |
| `projects` | `0003_product_profile_core` |
| `authorization` | `0005_seed_product_actions`、`0006_seed_change_set_approve_action` |
| `integrations` | `0001_external_binding` |

## 自动化证据（本轮实际运行）

```text
uv run pytest tests/products tests/acceptance/test_product_profile_migration.py -q --create-db
  → 47 passed
uv run mypy config apps                                         → Success
frontend product unit tests                                     → 4 passed
frontend typecheck / format:check                               → 通过
tests/e2e/product-profile-migration.spec.ts                     → 2 passed（导航 + 导入发布可搜索）
scripts/check.cmd                                               → All quality gates passed（含 MySQL 全量 pytest、阶段0/2/3 E2E）
```

## 已知限制

- 导入首期仅 CSV（stdlib），无 Excel 异步 Celery 流水线
- OpenAPI `spectacular` 对阶段2遗留 APIView 仍有推断警告；阶段3新增产品端点已补齐 request/response 契约
- 版本范围历史区间重叠的完整拓扑校验仍可继续加深；当前对开放生效范围冲突已阻塞

## 阶段4 边界

阶段3 **不实现**：D1-L3 项目执行模板、阶段4交付物工作台、`FIRST_LAUNCH` 重大阶段门、经营事实汇总、外部系统正式同步、复杂搜索引擎。

## 阶段退出条件核对

- [x] PIM-001–PIM-012、GLB-004/005/010、NFR-006 有测试或文档证据
- [x] 新品变更集可 API 发布为 `ACTIVE` 产品档案
- [x] 存量导入可确认并发布基线后可搜索
- [x] 前端产品模块可构建且单元测试通过
- [x] PIM-013 外部绑定（模型 + 授权写命令 + API + 详情展示 + 前端）
- [x] 草稿读取与批准权限边界
- [x] 范围/生效时间预检与渠道失败显式化
- [x] 完整 `scripts/check.cmd` 门禁
- [x] Playwright 阶段三闭环 E2E（导航 + 导入发布可搜索）
