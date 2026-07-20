# 阶段4 开发到首次上市 —— 完成检查点

日期：2026-07-20

状态：第十一轮 NO-GO（stage 事务内重判权、ARCHIVE_ONLY 激活失败同键恢复、跨列表重复 handle + savepoint、confirm history_files OpenAPI 类型）已本地修复；待再次全量门禁验收。

对应计划：`docs/superpowers/plans/2026-07-14-phase-4-development-first-launch.md`

对应测试矩阵：`docs/implementation/phase-4-test-matrix.md`

基准：`902550f` → 十次 `d558308` / `9417a54` → 十一次（本检查点提交后回填哈希）

## 十一次复审修复摘要（相对 `9417a54`）

### Standards
- **P1**：`StageMigrationFile` 在写入 handle/审计/outbox 的 `transaction.atomic` 内重新 `authorize`；流式写入后权限被撤销则回滚并清理 `.part`。
- **P1**：`ARCHIVE_ONLY` 在 CONFIRMED 同幂等键重试时继续调用 `_activate_archived_history_files`（不再直接返回）。
- **P1**：导入批次每行嵌套 `transaction.atomic`（savepoint）；跨 `history_files`/`history_deliverables` 重复 `staging_relpath` 在 create/claim 前拒绝。

### Spec
- **P1**：激活失败后同键重试测试；跨列表重复 + 同批成功行回归（错误行无半成品 baseline/claim）。
- **P2**：confirm 响应 `history_files` 使用带 child 的序列化器（含 `document_version_public_id`）。
- **P2**：检查点与测试矩阵证据口径对齐：本切片跑域内 pytest；全量门禁（含 Playwright）以再次验收为准。上次干净克隆 `9417a54` 全量门禁曾全绿，但不替代本轮修复后的复跑。

## 本轮实测证据（域内）

```text
Base commits reviewed: d558308, 9417a54
Remediation commit: <pending local commit>
Backend pytest tests/projects/test_inflight_migration.py + uploads + reconciliation: 31 passed
Backend ruff check (touched files): pass
OpenAPI spectacular + frontend api:generate: regenerated (typed MigrationBaselineConfirmHistoryFile)
scripts\check.ps1 full gate / Playwright: not run this slice (pending re-acceptance)
```

全量 `scripts\check.ps1` 与 Playwright 待批准后复跑。
