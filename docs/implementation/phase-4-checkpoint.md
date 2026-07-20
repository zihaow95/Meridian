# 阶段4 开发到首次上市 —— 完成检查点

日期：2026-07-20

状态：第九轮 NO-GO（stage 授权/单次领取句柄、reconcile 生产保护、并发 CompleteUpload、E2E stage 主链、Prettier）已本地修复；待再次全量门禁验收。

对应计划：`docs/superpowers/plans/2026-07-14-phase-4-development-first-launch.md`

对应测试矩阵：`docs/implementation/phase-4-test-matrix.md`

基准：`a220f18` → 八次 `d090f01` → 九次修复（本检查点）

## 九次复审修复摘要（相对 `d090f01`）

### Standards
- **P1**：`project-migration-files/stage` 强制 `project_migration.confirm`；命令层授权 + 审计 + outbox。
- **P1**：`MigrationFileStage` 持久化组织/上传者/过期/单次领取；导入 claim，确认后 consume；禁止跨基线复用同一 `staging_relpath`。
- **P1**：projects `ready()` 注册 reconcile protected-relpath provider；默认巡检保护未消费暂存。
- **P1**：CompleteUpload 并发屏障测试（独立连接 + Barrier）验证最终仅一条 CONTROLLED 版本。
- **P2**：`activate_staged_content` 文档与“移动失败保留暂存”实现对齐。

### Spec
- **P1**：stage API 允许/拒绝测试；E2E 覆盖 stage → batch → confirm → download；limited 用户拒绝 stage。
- **P2**：交付物列表 `can_download` 授权前 false、授权后 true。
- **P2**：检查点记录精确哈希 `d090f01` 及本轮后续提交；`DeliverablePanel.spec.ts` Prettier 已对齐。

## 本轮实测证据（域内）

```text
Base commit reviewed: d090f01
Commit target: ninth-pass remediation after d090f01
Backend pytest uploads + inflight_migration + reconciliation: 24 passed
Backend ruff check (changed modules): pass
OpenAPI spectacular: regenerated (MigrationFileStageResponse expires_at/public_id)
Frontend prettier DeliverablePanel.spec.ts: written
Frontend typecheck + vitest src/modules/projects: 23 passed
scripts\check.ps1 full gate / Playwright: not run this slice (pending re-acceptance; E2E seed adds document.version.download)
```

全量 `scripts\check.ps1` 与 Playwright 待批准后复跑（需刷新 E2E seed 以获得下载授权）。
