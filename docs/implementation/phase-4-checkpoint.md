# 阶段4 开发到首次上市 —— 完成检查点

日期：2026-07-20

状态：第十三轮 NO-GO（ARCHIVE_ONLY 锁内重读历史列表 + 同键并发唯一事实）已本地修复；待再次验收。

对应计划：`docs/superpowers/plans/2026-07-14-phase-4-development-first-launch.md`

对应测试矩阵：`docs/implementation/phase-4-test-matrix.md`

基准：`816336e` → 十二次 `13d9ee2` / `b147eb0` → 十三次 `06424d3`（本检查点）

## 十三次复审修复摘要（相对 `b147eb0`）

### Standards / Spec
- **P1**：`_activate_archived_history_files` 在 `select_for_update` 锁定 baseline 后，从锁定对象重新构造 `history_files` / `history_deliverables`，再 `_ensure_pending_ids`。
- **P1**：同键 ARCHIVE_ONLY 并发（独立连接 + Barrier）断言唯一 Document / DocumentVersion / FileObject，baseline 引用唯一，stage 已 consume。

## 本轮实测证据（域内）

```text
Base commits reviewed: 13d9ee2, b147eb0
Remediation commit: 06424d3
Backend pytest tests/projects/test_inflight_migration.py: 26 passed
Backend ruff (touched files): pass
scripts\check.ps1 full gate: not re-run this slice (code-only P1)
Docker image builds: still environment-dependent (Docker Hub); not re-attempted
```
