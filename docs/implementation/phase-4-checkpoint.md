# 阶段4 开发到首次上市 —— 完成检查点

日期：2026-07-20

状态：第十轮 NO-GO（stage 事务原子性、同基线重复 handle、ARCHIVE_ONLY 正式激活、并发 join 断言、reconcile provider 证据）已本地修复；待再次全量门禁验收。

对应计划：`docs/superpowers/plans/2026-07-14-phase-4-development-first-launch.md`

对应测试矩阵：`docs/implementation/phase-4-test-matrix.md`

基准：`d090f01` → 九次 `f069177` / `902550f` → 十次修复（本检查点）

## 十次复审修复摘要（相对 `902550f`）

### Standards
- **P1**：`StageMigrationFile` 在 `transaction.atomic` 内写入 handle/审计/outbox；失败删除 `.part`；审计失败回滚测试。
- **P1**：同一 baseline 内重复 `staging_relpath` 在 normalize/claim 两层拒绝。
- **P1**：`ARCHIVE_ONLY` 激活正式 `DocumentVersion`、写入 `document_version_public_id` 并 consume stage；confirm 响应带回历史文件版本。
- **P1**：并发 CompleteUpload 断言 `join` 后线程结束且 `len(results) == 2`。
- **P2**：reconcile 测试构造 claimed/aged `MigrationFileStage` + CONFIRMED 基线引用，证明 provider 保护。
- **P2**：`staging_relpath` 唯一字段缩至 191，消除 mysql.W003 风险。

### Spec
- **P1**：stage 审计失败无半成品；同基线重复 handle 无半成品。
- **P1**：E2E archive 使用真实 `history_files` 并下载归档版本。
- 检查点记录 `902550f` 后继提交哈希。

## 本轮实测证据（域内）

```text
Base commits reviewed: f069177, 902550f
Backend pytest uploads + reconciliation + inflight_migration: 28 passed
Backend ruff format --check tests/projects/test_inflight_migration.py: pass
OpenAPI spectacular: regenerated (confirm history_files)
scripts\check.ps1 full gate / Playwright: not run this slice (pending re-acceptance)
```

全量 `scripts\check.ps1` 与 Playwright 待批准后复跑。
