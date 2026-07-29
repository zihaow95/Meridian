# 阶段5 运营、迭代和退市 —— 完成检查点

日期：2026-07-29

状态：**NO-GO（六次复验待定）** — 五次复验仍为 NO-GO（P1：0011 存量碰撞、事务外判权、无控停用）。本轮补齐规范化后 ACTIVE 去重；Assign/Deactivate/Provision 统一组织+用户锁并在事务内复核；新增受控 `DeactivateRoleAssignment`；修复 Provision ACTIVE 优先与 E2E seed scope 字段。关闭全部 P1 且验收 GO 前不得推进阶段六。

对应计划：`docs/superpowers/plans/2026-07-20-phase-5-operations-iteration-retirement.md`

## 六次 remediation 要点

- `0011`：规范化后按 `scope_key` 去重 ACTIVE，再加唯一约束；碰撞回填测试覆盖 NULL+显式 org 归一化冲突
- `AssignRole` / `DeactivateRoleAssignment` / `ProvisionRetirementSystemActor`：组织→用户锁顺序，事务内 `subject_for`+`authorize`
- 停用改为受控应用服务（权限复核 + 审计 + 清空 `active_slot`）
- Provision 优先返回当前 ACTIVE/open/`active_slot=1`；仅历史失效行时拒绝自愈
- `seed_e2e_user` 写入规范化 `scope_id`/`scope_key`；空库/双次 seed 测试

## 本轮本地验证

```text
Reviewed range: 5dd25d5...HEAD (sixth remediation)
Focused MySQL pytest (auth+seed+collision): 23 passed
Full scripts/check.ps1: not re-run in this agent turn (avoids stream timeout);
  please run scripts\check.cmd separately for full gate evidence
```

合并或推进阶段六前必须：严格复审 GO。
