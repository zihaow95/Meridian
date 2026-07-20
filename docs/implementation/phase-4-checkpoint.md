# 阶段4 开发到首次上市 —— 完成检查点

日期：2026-07-20

状态：第六轮 NO-GO（文件补偿链、Base64 入库、前端下载、repair 真实失败链、repair-message 竞态）已本地修复；待再次全量门禁验收。

对应计划：`docs/superpowers/plans/2026-07-14-phase-4-development-first-launch.md`

对应测试矩阵：`docs/implementation/phase-4-test-matrix.md`

基准：`631b004` → 五次修复 `f44fddb` → 六次修复（本检查点）

## 六次复审修复摘要（相对 `f44fddb`）

### Standards
- **P1**：导入时将历史文件写入存储临时目录，MySQL 只保留 `staging_relpath`/SHA/大小等元数据，不再持久化 Base64。
- **P1**：`activate_staged_content` 移动后以单事务完成 ACTIVE/CONTROLLED；`ReconcileStorage` 对「PENDING 且正式文件已存在」补激活；确认幂等重试会继续激活并挂接交付物；`CompleteUpload` 在事务提交后激活；交付物仅在 ACTIVE 后引用。
- **P2**：移除未使用的 `StagedContent.document_id` / `version_public_id`。

### Spec
- **P1**：`DeliverablePanel` 基于 `document_version_public_id` 申请下载票据并触发下载。
- **P1**：E2E repair 种子每次 re-arm 都重新走双人决策 + 真实发布失败；响应断言 MySQL 计数 `product_version_count` / `monitoring_scope_count` == 1。
- **P2**：`repair-message` 移出 `PUBLISH_PENDING_REPAIR` 条件块，状态刷新后仍可见。
- **P2**：测试矩阵与本检查点已更新。

## 本轮实测证据（域内，非整轮 check.ps1）

```text
Backend: ruff + mypy config apps + related pytest (documents/projects migration/workbench/handover)
Frontend: typecheck + projects vitest
Playwright: publish-repair E2E with retries=0 (prior round passed; re-verify after this fix)
```

全量 `scripts\check.ps1`（含 Docker / 旧依赖扫描）待批准后复跑。

## 显式不在阶段4范围

运营监测深度能力、退市流程、多组织迁移工具 UI。
