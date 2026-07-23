# 阶段5 运营、迭代和退市 —— 完成检查点

日期：2026-07-23

状态：**NO-GO（三次复验待定）** — `dc9bd30...6a5864c` 复审仍为 NO-GO。本轮关闭：运行时自我提权、SKU_CHANNEL 跨渠道 ALL 泄露、敏感级回落、TodoItem 跨域写、INACTIVE configured 失败、YEAR 合同外粒度、门禁 format/mypy/有效值读权。关闭全部 P1 且 `scripts\check.cmd` 全绿前不得推进阶段六。

对应计划：`docs/superpowers/plans/2026-07-20-phase-5-operations-iteration-retirement.md`

对应测试矩阵：`docs/implementation/phase-5-test-matrix.md`

基准：`edd50ce` → `5c16ff8` → `dc9bd30` → `696d36a`/`6a5864c` → 本轮 remediation

## 本轮 remediation（相对三次复审）

- 系统主体：仅 `resolve_retirement_system_actor`；`provision_retirement_system_actor` 预配置且拒绝自愈 DISABLED
- SKU_CHANNEL：缺 channel 不再授权；渠道监督人不可见 `channel_id IS NULL` ALL 汇总
- 聚合 contributors 写入 `source_code` / `sensitivity_level`
- Todo 完成：`CompleteOpenTodosForSource`（notifications）；消费者不再导入 TodoItem
- data_source/metric/monitoring：声明 `NO_LOCAL_SUBSCRIBER_EVENT_TYPES`，INACTIVE configured 可 PUBLISHED
- 删除 YEAR；看板渠道下钻展示 contributors
- 有效值成功路径补 `operating_fact.read`；增加拒绝测试

## 复验门禁证据

```text
Reviewed range: 6a5864c...HEAD (third remediation)
scripts\check.ps1: All quality gates passed. (2026-07-23 local)
```

合并或推进阶段六前必须：严格复审 GO（本检查点仍标 NO-GO 直至验收方确认）。
