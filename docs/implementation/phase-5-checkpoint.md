# 阶段5 运营、迭代和退市 —— 完成检查点

日期：2026-07-29

状态：**NO-GO（七次复验待定）** — 六次复验仍为 NO-GO（P1：锁后仍用陈旧 actor；撤销复用 assign 权限/审计）。本轮锁函数返回重读 User；Assign/Deactivate/Provision 统一使用 locked_actor；注册 `authorization.role.revoke`；补独立连接停用竞态、revoke 允许/拒绝/审计回滚与 MigrationExecutor 0010→0011 证据；`.env` 加载后强制可写 npm cache。关闭全部 P1 且验收 GO 前不得推进阶段六。

对应计划：`docs/superpowers/plans/2026-07-20-phase-5-operations-iteration-retirement.md`

## 七次 remediation 要点

- `lock_organization_and_users` 返回 `dict[id, User]`；三服务用 locked_actor 判权/写入/审计
- 新增 `authorization.role.revoke`（迁移 0012）；Deactivate 仅检查 revoke，审计含 ACTIVE→INACTIVE
- MigrationExecutor 真实执行 0010→0011 碰撞去重并校验非空字段与唯一约束
- `check.ps1` 在加载 `.env` 之后再次清理并强制 LocalAppData npm cache

## 本轮本地验证

```text
Reviewed range: a5139ca...HEAD (seventh remediation)
Focused MySQL pytest: pending in this turn
Full scripts/check.cmd: run by human after local commit
```

合并或推进阶段六前必须：严格复审 GO。
