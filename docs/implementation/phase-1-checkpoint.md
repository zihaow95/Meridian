# 阶段1 平台内核 —— 完成检查点

日期：2026-07-07

状态：已完成（PR1–PR4 已合并）

对应计划：`docs/superpowers/plans/2026-07-06-phase-1-platform-kernel.md`

对应测试矩阵：`docs/implementation/phase-1-test-matrix.md`

## 已交付能力概览

- 身份与会话：组织/用户/绑定、钉钉 OAuth 抽象、开发登录（测试环境启用）
- 权限：RBAC + ABAC、默认拒绝、列表过滤与字段/文件动作策略
- 审计：append-only 审计事件、事务内审计与回滚、审计查询 API
- 双人复核/专项授权/排障：管理变更复核请求、有效期授权、排障访问
- 可靠事件：MySQL outbox、Celery 调度、幂等消费回执
- 配置中心：不可变配置版本、Schema 校验、发布审计与 outbox、引用快照
- 受控文件：上传会话、原子移动、下载票据、巡检补偿
- 待办/通知：权威待办、权限过滤摘要、钉钉投递失败不回滚
- 前端：登录、我的待办、最小管理入口；E2E 冒烟覆盖“未登录跳转登录”

## 自动化证据

- 后端：pytest（MySQL）覆盖 PLT-001 ~ PLT-013（见测试矩阵）
- 静态检查：ruff / mypy
- 契约：OpenAPI schema 与前端生成类型无漂移
- 前端：eslint / prettier / vue-tsc / vitest / build
- E2E：Playwright 冒烟（`tests/e2e/*.spec.ts`）

## 已知限制 / 后置项

- 测试专用端点 `/api/v1/_test/hidden-resource` 仅在 `ENABLE_TEST_API=True` 时注册，不出现在生产 URL 与 OpenAPI
- 真实钉钉企业环境登录与通知投递验收：按计划延后至阶段6
- 文件的 Nginx `X-Accel-Redirect` 端到端验收：随部署（阶段7）补齐

