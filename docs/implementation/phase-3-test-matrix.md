# 阶段3 产品档案与存量迁移 —— 测试矩阵

状态：已通过（2026-07-10，分支 `codex/phase-3-product-profile-migration`）

对应计划：`docs/superpowers/plans/2026-07-09-phase-3-product-profile-migration.md`

对应 TRD：`docs/trd/02-product-profile-version-migration-trd.md`

> 状态取值：`未实现` / `进行中` / `已通过：<测试位置>` / `后置：<阶段>`。

## PIM 需求追踪

| 需求 | 说明 | 计划证据位置 | 状态 |
|---|---|---|---|
| PIM-001 | 产品资产/版本/SKU/渠道主模型 | `backend/tests/products/test_product_core_models.py` | 已通过 |
| PIM-002 | 研发中草稿演进为 ChangeSet(NEW_PRODUCT) | `backend/tests/products/test_product_core_models.py`, `backend/tests/products/test_product_draft_shell.py` | 已通过 |
| PIM-003 | 属性 Schema 版本化与校验 | `backend/tests/products/test_attribute_schema.py` | 已通过 |
| PIM-004 | 属性组值编辑与内容哈希 | `backend/tests/products/test_attribute_schema.py` | 已通过 |
| PIM-005 | 草稿差异与基线指纹冲突 | `backend/tests/products/test_change_set_diff.py` | 已通过 |
| PIM-006 | 发布预检阻塞项 | `backend/tests/products/test_publication_validation.py` | 已通过 |
| PIM-007 | 原子发布与幂等 | `backend/tests/products/test_publish_change_set.py`, `backend/tests/products/test_product_concurrency.py` | 已通过 |
| PIM-008 | 发布后版本并行有效范围 | `backend/tests/products/test_publish_change_set.py` | 已通过（首期仅版本/SKU 生效） |
| PIM-009 | 产品查询/详情/版本树与字段投影 | `backend/tests/products/test_product_api.py`, `backend/tests/products/test_product_query_permissions.py`, `frontend/src/modules/products/ProductListView.spec.ts` | 已通过 |
| PIM-010 | 导入批次/逐行校验/错误可见 | `backend/tests/products/test_legacy_import.py` | 已通过 |
| PIM-011 | 重复候选识别与人工处理 | `backend/tests/products/test_import_duplicates.py` | 已通过 |
| PIM-012 | 导入确认幂等与基线发布 | `backend/tests/products/test_legacy_baseline_publish.py`, `backend/tests/acceptance/test_product_profile_migration.py` | 已通过 |
| PIM-013 | 外部绑定与编码管理 | `backend/tests/products/test_external_binding.py` | 已通过 |
| PIM-014 | OpenAPI 契约与前端类型漂移门禁 | `backend/openapi/schema.yaml`, `frontend/src/api/generated/schema.d.ts`, `scripts/check.ps1` | 已通过（产品 API 有 `extend_schema`；全局推断警告仍为非阻塞） |

## GLB / NFR 追踪

| 需求 | 说明 | 证据 | 状态 |
|---|---|---|---|
| GLB-004 | 关键写命令事务/幂等/唯一约束 | `backend/tests/products/test_product_concurrency.py`, `backend/tests/products/test_publish_change_set.py`, `backend/tests/products/test_legacy_import.py` | 已通过 |
| GLB-005 | 权限默认拒绝 + 字段级投影 + 审计 | `backend/tests/products/test_product_permissions.py`, `backend/tests/products/test_product_query_permissions.py` | 已通过 |
| GLB-010 | 导入/发布可追溯审计与 outbox | `backend/tests/products/test_legacy_baseline_publish.py`, `backend/tests/acceptance/test_product_profile_migration.py` | 已通过 |
| NFR-006 | 契约可用（OpenAPI + 类型 + 漂移门禁） | `backend/openapi/schema.yaml`, `frontend/src/api/generated/schema.d.ts` | 已通过 |

## E2E

| 场景 | 证据 | 状态 |
|---|---|---|
| 产品列表与导入工作台可达 | `tests/e2e/product-profile-migration.spec.ts` | 已通过（本地） |
| 新品发布 + 存量导入全链路 UI | 同上 | 进行中（首期仅导航冒烟；API 验收见 acceptance 测试） |
