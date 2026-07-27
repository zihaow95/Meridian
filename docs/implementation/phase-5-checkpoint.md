# 阶段5 运营、迭代和退市 —— 完成检查点

日期：2026-07-27

状态：**NO-GO（五次复验待定）** — 四次复验仍为 NO-GO（P1：`active_slot` 在 NULL `scope_id` 下失效；宽泛 `IntegrityError` 假成功；失败审计不完整）。本轮以非空 `scope_key` 重建唯一约束、删除假成功兜底、业务拒绝失败审计、并将系统主体创建下沉到 identity 受控服务。关闭全部 P1 且验收 GO 前不得推进阶段六。

对应计划：`docs/superpowers/plans/2026-07-20-phase-5-operations-iteration-retirement.md`

## 五次 remediation 要点

- `RoleAssignment.scope_id` 非空；新增规范化 `scope_key`；唯一键为 `user+role+scope_type+scope_key+active_slot`；失效时清空 `active_slot`
- `AssignRole` 组织级将 `scope_id=None` 规范为 `target.organization_id`
- `ProvisionRetirementSystemActor`：删除宽泛 `IntegrityError` 假成功；事务外捕获 `ValidationFailedError` 写 FAILURE 审计（含 executor/role/assignment 拒绝）
- 系统主体创建改为 `EnsureRetirementSystemExecutor`（identity 域）；authorization 仅编排权限、角色与审计

## 本轮本地验证

```text
Reviewed range: b52840c...HEAD (fifth remediation)
Backend ruff/format/mypy/django check/migrate drift: OK
MySQL pytest: 474 passed
OpenAPI snapshot: OK
Frontend lint/format/typecheck/build/unit: OK (59 passed)
Playwright E2E: 19 passed
Docker images backend+frontend: OK
Legacy scan: OK
All quality gates passed
```

合并或推进阶段六前必须：严格复审 GO。
