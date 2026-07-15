# 阶段4 开发到首次上市 —— 完成检查点

日期：2026-07-15

状态：退出证据已落地（本轮实测）；全量 `scripts\check.cmd` 与 `verify-trd.ps1` 如未在本机复跑，验收时需补跑

对应计划：`docs/superpowers/plans/2026-07-14-phase-4-development-first-launch.md`

对应测试矩阵：`docs/implementation/phase-4-test-matrix.md`

提交：`2195dd9`（工作台）、`5a24889`（E2E/种子/退出证据）

## 本轮交付摘要

- Task 4.0–4.8：运行时初始化、任务/交付物、例外与计划、阶段门提交与决策、FIRST_LAUNCH + PublishAndHandover、在途迁移、权限过滤 API + OpenAPI
- Task 4.9：`frontend/src/modules/projects/` 看板与执行工作台；路由 `/projects`、`/projects/:publicId`、`/projects/:publicId/launch-gate`；todo 深链回系统页
- Task 4.10：Playwright `development-first-launch.spec.ts`；E2E 种子扩展模板/权限/限定用户/上市与待修复夹具；阶段列表暴露 `stage_gate_public_id`；生命周期看板容忍无 candidate 的迁移项目

## 自动化证据（本机实测）

```text
frontend projects Vitest: 16 passed
Playwright development-first-launch.spec.ts: 6 passed
  - 新品立项→D1–L3 运行时 + 工作台
  - 核心任务未完成阻断阶段门提交（409）
  - FIRST_LAUNCH 发布交接 / 或已 OPERATING 幂等
  - PUBLISH_PENDING_REPAIR 待修复可见
  - D3 CONTINUE 跳过 D1/D2；ARCHIVE_ONLY 无项目
  - 限定用户迁移/先执行拒绝（403/404）
seed_e2e_user: 含 PROJECT_EXECUTION_TEMPLATE + phase4 actions
```

## 尚未在本检查点声明为“本机当次全绿”的项

- 完整 `scripts\check.cmd`（阶段0–4 全部门禁）——请验收复跑确认 `All quality gates passed.`
- `scripts\verify-trd.ps1`——请确认 92 项需求与 4 个重大阶段门仍通过
- 发布失败后的同决定幂等重试 API 表面：由 pytest `test_launch_handover` 覆盖服务层；E2E 覆盖首次进入 `PUBLISH_PENDING_REPAIR`

## 显式不在阶段4范围

阶段5 经营事实/指标/信号；通用 BPM；钉钉内状态迁移。
