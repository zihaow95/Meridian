# 阶段1 平台内核 —— 完成检查点

日期：2026-07-08

状态：已通过 remediation Batch 1–3 重新验收

对应计划：`docs/superpowers/plans/2026-07-06-phase-1-platform-kernel.md`

对应测试矩阵：`docs/implementation/phase-1-test-matrix.md`

修复计划：`docs/implementation/phase-1-code-review-remediation-plan.md`

## 已交付能力概览

- 身份与会话：钉钉 OAuth 抽象、dev login、`django.contrib.auth.login()` 真实会话
- 权限：RBAC + ABAC、默认拒绝、服务层授权、API 权限基类、平台动作目录 seed
- 审计：append-only、事务内审计、带权限和脱敏的审计查询 API
- 双人复核/专项授权/排障：服务层授权 + 审计
- 可靠事件：outbox 本地消费、并发幂等 receipt、失败可重试
- 配置中心：版本服务 + 读取/发布 API
- 受控文件：上传/完成/版本/下载票据 API，事务内 `select_for_update`
- 待办/通知：权威待办投影 + `GET /api/v1/todos/my`
- 前端：真实 API 接入（待办、配置、审计、角色、文件）；生产构建隐藏 dev login

## 自动化证据（本轮实际运行）

```text
backend: ruff / mypy / pytest (MySQL) — 含 acceptance/test_platform_kernel.py
backend: OpenAPI schema 生成与 drift 检查
frontend: eslint / prettier / vue-tsc / vitest / build
frontend: OpenAPI 类型再生成与 drift 检查
E2E: tests/e2e/platform-kernel.spec.ts（Playwright + 后端 dev + Vite proxy）
本地门禁: scripts/check.ps1（含 E2E 步骤）
CI: .github/workflows/ci.yml（backend / frontend / e2e / images / legacy-scan）
```

## 已知限制 / 后置项

- 测试专用端点 `/api/v1/_test/hidden-resource` 仅在 `ENABLE_TEST_API=True` 时注册
- 真实钉钉企业环境登录与通知投递验收：阶段6
- 文件 Nginx `X-Accel-Redirect` 端到端验收：阶段7
