# 阶段3 产品档案与存量迁移 —— 完成检查点

日期：2026-07-10

状态：已通过（分支 `codex/phase-3-product-profile-migration`，待合入 main）

对应计划：`docs/superpowers/plans/2026-07-09-phase-3-product-profile-migration.md`

对应测试矩阵：`docs/implementation/phase-3-test-matrix.md`

HEAD：`22c3026`（前端 UI）；后端完整历史见下方提交记录

## 已交付能力概览

- **产品主模型**：`ProductAsset`、`ProductVersion`、`SKU`、`ChannelConfiguration`、`ProductChangeSet`；`ProductDraft` 兼容代理
- **属性 Schema**：版本化定义、变更集编辑、差异、确认、营养/素材校验
- **发布**：`ValidateProductPublication` + `PublishProductChangeSet`（幂等、乐观锁、基线指纹）
- **查询 API**：产品搜索/详情、变更集详情/差异/编辑/预检/发布；字段级权限投影
- **存量导入**：CSV 解析、`ImportBatch`/`ImportItem`、重复识别、确认导入、`PublishLegacyBaseline`
- **前端**：产品列表、详情、变更集工作台、发布预检面板、导入页；Pinia store + 单元测试
- **验收**：`test_product_profile_migration.py`（新品发布 + 存量导入可搜索）；Playwright 产品导航冒烟

## 提交记录（阶段3）

```text
22c3026 feat: add product dossier UI
e303ca9 feat: add legacy product baseline import (OpenAPI types)
6298be1 feat: add legacy product baseline import
143587c feat: add product dossier APIs
afe2df8 feat: publish product change sets atomically
502ab97 feat: add product materials and attribute confirmations
9188fb0 feat: add product attribute schema and diff
9b718b8 feat: add product profile core model
f36888b feat: add phase 3 product authorization actions
654d0e7 feat: establish phase 3 baseline and test matrix
```

## 数据库迁移（阶段3 新增）

| 应用 | 迁移 |
|---|---|
| `products` | `0003_product_profile_core` … `0008_import_batches` |
| `projects` | `0003_product_profile_core` |
| `authorization` | `0005_seed_product_actions` |

## 自动化证据（本轮实际运行）

```text
uv run pytest tests/products -q --create-db                    — 34 passed
uv run pytest tests/acceptance/test_product_profile_migration.py -q --create-db — 2 passed
npm run test:unit -- --run ProductListView.spec.ts …          — 4 passed
npm run typecheck                                              — 通过
uv run python manage.py spectacular --file openapi/schema.yaml — 通过（全局推断警告非阻塞）
tests/e2e/product-profile-migration.spec.ts                    — 未在本轮重跑（需 dev 栈）
scripts/check.ps1                                              — 未完整执行
scripts/preflight.cmd / verify-trd.ps1                         — 未在本轮执行
```

## 已知限制

- `integrations_external_binding` 模型与 `PIM-013` 独立测试未实现；重复识别使用业务编号/SKU/条码
- 导入首期仅 CSV（stdlib），无 Excel 异步 Celery 流水线
- 渠道配置发布钩子 `create_channel_configurations` 仍为空实现
- E2E 仅覆盖产品列表/导入页导航；完整导入+发布 UI 链路依赖后续补强
- OpenAPI `spectacular` 对部分 APIView 仍有推断警告（与阶段2相同策略：非阻塞）

## 阶段4 边界

阶段3 **不实现**：D1-L3 项目执行模板、阶段4交付物工作台、`FIRST_LAUNCH` 重大阶段门、经营事实汇总、外部系统正式同步、复杂搜索引擎。

## 阶段退出条件核对

- [x] PIM-001–PIM-012、GLB-004/005/010、NFR-006 有测试或文档证据
- [x] 新品变更集可 API 发布为 `ACTIVE` 产品档案
- [x] 存量导入可确认并发布基线后可搜索
- [x] 前端产品模块可构建且单元测试通过
- [ ] PIM-013 外部绑定（明确后置）
- [ ] 完整 `scripts/check.ps1` 门禁（待合入前执行）
- [ ] Playwright 全链路 E2E（待 dev 环境重跑）
