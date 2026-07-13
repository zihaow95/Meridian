# 阶段3 产品档案与存量迁移 —— 完成检查点

日期：2026-07-13

状态：修复已落地，等待全量门禁复验通过后退出

对应计划：`docs/superpowers/plans/2026-07-09-phase-3-product-profile-migration.md`

对应测试矩阵：`docs/implementation/phase-3-test-matrix.md`

## 本轮 Spec/Standards P1 修复

- 产品列表/详情强制 `product.read_basic`（无权同组织用户不可见）
- 属性确认不再把变更集推进到 `IN_CONFIRMATION`；提交仍为 DRAFT→IN_CONFIRMATION
- `product_change_set` 对象身份提供器 + `assigned_confirmer` 重分配落库/审计/outbox
- 导入 CREATE/LINK/SKIP 决策事务内写审计与 outbox；前端决策与确认串行化
- 创建变更集 OpenAPI 响应 201；导入模板下载、Excel/CSV 上传、结果报告
- 产品筛选：品牌/品类/状态/负责人/SKU/外部编码/渠道

## 自动化证据（提交前定向）

```text
uv run pytest ... 相关产品用例 → 199 passed（全量 MySQL，check 中断前）
uv run mypy / ruff → 通过
frontend unit 4 passed；typecheck 通过
scripts\check.cmd → 提交后复跑（OpenAPI drift 需提交同步后才能绿）
```
