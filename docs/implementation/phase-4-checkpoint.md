# 阶段4 开发到首次上市 —— 完成检查点

日期：2026-07-20

状态：第七轮 NO-GO（P0 路径穿越、文件补偿链、repair re-arm、下载权限态、Ruff format）已本地修复；待再次全量门禁验收。

对应计划：`docs/superpowers/plans/2026-07-14-phase-4-development-first-launch.md`

对应测试矩阵：`docs/implementation/phase-4-test-matrix.md`

基准：`f44fddb` → 六次 `0a9cec4` → 七次修复（本检查点）

## 七次复审修复摘要（相对 `0a9cec4`）

### Standards
- **P0**：拒绝客户端 `staging_relpath`；服务端路径解析禁止绝对路径与 `..`。
- **P1**：Base64 增量解码；导入执行 MIME/大小策略；激活前持久化 `pending_version_public_id` 以便无暂存文件恢复；空壳交付物可补挂接；reconcile 不清理仍被 IMPORTED 基线引用的 `migration/*.part`；CompleteUpload 仅在激活成功后标记 completed。
- **P1**：`workbench.py` Ruff format 已对齐。
- **P2**：恢复走 `documents.services.recovery` 公开入口，按基线 `pending_version_public_id` 绑定。

### Spec
- **P1**：repair re-arm 使用递增 `submission_number` 与唯一幂等键。
- **P2**：`can_download_documents` + DeliverablePanel 隐藏下载；Vitest 覆盖无权隐藏与 403。
- **P2**：本检查点记录精确验证数量。

## 本轮实测证据（域内）

```text
Commit target: post-0a9cec4 seventh-pass remediation
Backend ruff format --check apps/projects/api/workbench.py: pass
Backend ruff check (changed documents/projects modules): pass
Backend pytest tests/documents/test_uploads.py + tests/projects/test_inflight_migration.py: 15 passed
Frontend npm run typecheck: pass
Frontend npx vitest run src/modules/projects: 20 passed (5 files)
Playwright publish-repair retries=0: not re-run this slice
scripts\check.ps1 full gate: not run this slice (pending re-acceptance)
```

全量 `scripts\check.ps1` 与 Playwright publish-repair 待批准后复跑。
