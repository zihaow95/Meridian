# 阶段4 开发到首次上市 —— 完成检查点

日期：2026-07-20

状态：第十四轮 NO-GO（同键并发审计/outbox 断言、atomic_move TOCTOU 恢复、测试矩阵证据口径）已本地修复；待再次验收。

对应计划：`docs/superpowers/plans/2026-07-14-phase-4-development-first-launch.md`

对应测试矩阵：`docs/implementation/phase-4-test-matrix.md`

基准：`b147eb0` → 十三次 `06424d3` / `db361fc` → 十四次（本检查点提交后回填哈希）

## 十四次复审修复摘要（相对 `db361fc`）

### Standards / Spec
- **P1**：同键并发测试断言 `project_migration.confirm` 审计与 `project_migration.baseline_confirmed` outbox 各仅 1 条。
- **P1**：`activate_staged_content` 在 `atomic_move` 失败且正式对象已存在时转入 PENDING→ACTIVE recovery；`activate_or_recover_history_file` 在暂存缺失时同样重检正式路径。新增 move 窗口 Barrier 并发测试。
- **P2**：测试矩阵 E2E 行改为标注上一轮历史证据（`13d9ee2`/`b147eb0` 门禁），与本切片未重跑 Playwright 的口径一致。

## 本轮实测证据（域内）

```text
Base commits reviewed: 06424d3, db361fc
Remediation commit: <pending local commit>
Backend pytest tests/projects/test_inflight_migration.py: 26 passed
Concurrent confirm + move-race tests: 5/5 consecutive passes
Backend ruff (touched files): pass
scripts\check.ps1 full gate / Docker: not re-run this slice
```
