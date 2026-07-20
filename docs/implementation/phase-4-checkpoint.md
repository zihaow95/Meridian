# 阶段4 开发到首次上市 —— 完成检查点

日期：2026-07-20

状态：第八轮 NO-GO（pending_version 注入、恢复窗口、CompleteUpload 并发/重试、流式入口、领域边界、DeliverablePanel 覆盖与资源级下载）已本地修复；待再次全量门禁验收。

对应计划：`docs/superpowers/plans/2026-07-14-phase-4-development-first-launch.md`

对应测试矩阵：`docs/implementation/phase-4-test-matrix.md`

基准：`0a9cec4` → 七次 `a220f18` → 八次修复（本检查点）

## 八次复审修复摘要（相对 `a220f18`）

### Standards
- **P0**：导入拒绝客户端 `pending_version_public_id` 与内联 Base64；仅接受已流式写入的 `staging_relpath`。
- **P0**：恢复走 projects 域 `activate_or_recover_history_file`；正式对象缺失时继续使用暂存文件；`pending_version` 按 `staging_relpath` 一一绑定。
- **P1**：reconcile 通过调用方传入的 protected relpaths 保护任意仍引用 staging 的基线（含 CONFIRMED 窗口）；documents 不再依赖 projects 模型。
- **P1**：CompleteUpload 在锁内绑定 `document_version`；移动失败保留暂存；真实重试不重建文件；并发完成共用同一 PENDING 版本。
- **P1**：迁移文件入口改为 multipart 流式 `project-migration-files/stage`；导入 JSON 不再承载 Base64。
- **P2**：删除 documents→projects 的 recovery 反向依赖。

### Spec
- **P1**：恢复 DeliverablePanel 修订确认 / 409 冲突 Vitest，并保留资源级下载权限与 403 覆盖。
- **P2**：交付物列表返回 per-version `can_download`（不再用组织级布尔统一显隐）。
- **P2**：本检查点记录 `a220f18` 后继提交与精确验证数量；OpenAPI 含 `can_download` 与 stage 接口。

## 本轮实测证据（域内）

```text
Commit target: post-a220f18 eighth-pass remediation
Backend pytest uploads + inflight_migration + reconciliation: 21 passed
Backend ruff check (changed modules): pass
OpenAPI spectacular + schema drift (can_download, project_migration_files_stage): regenerated
Frontend npm run typecheck: pass
Frontend npx vitest run src/modules/projects: 23 passed (5 files)
scripts\check.ps1 full gate / Playwright: not run this slice (pending re-acceptance)
```

全量 `scripts\check.ps1` 与 Playwright 待批准后复跑。
