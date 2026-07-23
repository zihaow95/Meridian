# 阶段5 运营、迭代和退市 —— 完成检查点

日期：2026-07-22

状态：**NO-GO（二次复验待定）** — `5c16ff8...dc9bd30` 复审仍为 NO-GO；本轮继续关闭 P1（批次无界响应、人工值泄露、系统执行主体、提交前范围校验、汇总 ABAC、data_source.configured 消费者）并处理 P2。关闭全部 P1 且 `scripts\check.cmd` 全绿前不得推进阶段六。

对应计划：`docs/superpowers/plans/2026-07-20-phase-5-operations-iteration-retirement.md`

对应测试矩阵：`docs/implementation/phase-5-test-matrix.md`

基准：`edd50ce` → 初验 tip `5c16ff8` → 本轮 remediation（未合入 tip 前以工作区为准）

## 初验结论（相对 `edd50ce...5c16ff8`）

Standards / Spec 多处 P1：跨域直接写模型、列表无分页、退市完成缺审计/outbox、到期退市空任务、汇总权限过粗、退市范围静默过滤、outbox 未注册消费者、看板错误下钻、批次详情缺权限、TRD 错误码缺失等。当时全量门禁通过但不能作为阶段完成证据。

## 本轮 remediation 关闭项

- 跨域：`CreateRetirementGate` + `ApplyRetirementSubmission` / `ApplyRetirementDecision`；完成态审计 + `retirement.completed` 幂等 outbox
- 列表/批次行：统一 `items/page/page_size/count`；批次行独立分页端点
- 到期执行：真实 Celery 扫描 + Beat；双 worker / 幂等测试
- 汇总 ABAC：对象级 ResourceDescriptor + MonitoringAssignment 裁剪；产品汇总 `sku_breakdown`
- 退市范围：去重后数量必须完全命中，否则 `RETIREMENT_SCOPE_INVALID`
- Outbox：多订阅者注册表；补齐经营/退市事件消费者；撤销人工值触发重算事件
- 批次详情：可见性查询服务；未授权 404 风格；详情默认不含全量行
- TRD 稳定错误码：ApiError 子类 + 失败路径接线 + 契约测试
- P2：单位/币种/期间校验、信号已查看审计、退出文档去矛盾
- 前端：看板从 `sku_breakdown.sku_public_id` 下钻

## 复验门禁证据（本轮提交后由验收环境重跑）

```text
Reviewed range: 5c16ff8...HEAD (remediation)
scripts\check.ps1 / check.cmd: 待复验
```

合并或推进阶段六前必须：关闭全部 P1、全量门禁通过、严格复审 GO。
