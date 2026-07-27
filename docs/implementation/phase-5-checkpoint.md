# 阶段5 运营、迭代和退市 —— 完成检查点

日期：2026-07-27

状态：**NO-GO（四次复验待定）** — `d2b9a32` 复审仍为 NO-GO（P1：Provision 无授权无审计提权）。本轮将 Provision 迁入 authorization 受控服务，强制组织+执行人、双动作授权、成败审计、`active_slot` 唯一约束与并发锁；并修复看板同渠道多指标下钻与批次行 query service。关闭全部 P1 且验收 GO 前不得推进阶段六。

对应计划：`docs/superpowers/plans/2026-07-20-phase-5-operations-iteration-retirement.md`

## 四次 remediation 要点

- `ProvisionRetirementSystemActor`：同组织 + `system_actor.retirement.provision` + `authorization.role.assign`；失败/成功均审计；`configured_by` 必为执行人
- 管理命令强制 `--organization-id` + `--actor-login-key`，仅委托服务
- `RoleAssignment.active_slot` + MySQL 可用唯一约束；组织行 `select_for_update` 串行化
- 批次行：`list_visible_ingestion_batch_rows`；看板保存点击的完整汇总行

## 本轮本地验证

```text
Reviewed range: d2b9a32...HEAD (fourth remediation)
Backend ruff/format/mypy/django check/migrate drift: OK
MySQL pytest: 467 passed
OpenAPI snapshot: OK (prior slice)
Frontend lint/format/typecheck/build/unit: OK (59 passed, prior slice)
Playwright E2E: 19 passed
Docker images backend+frontend: OK
```

合并或推进阶段六前必须：严格复审 GO。
