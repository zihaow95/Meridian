# 阶段4 开发到首次上市 —— 完成检查点

日期：2026-07-16

状态：第三次 NO-GO 复审项已本地修复；`scripts\check.ps1` 本轮从头到尾全绿。待再审。

对应计划：`docs/superpowers/plans/2026-07-14-phase-4-development-first-launch.md`

对应测试矩阵：`docs/implementation/phase-4-test-matrix.md`

基准：`4cc99dc` → 首次 `8ad9cc2`/`30be1bb` → 二次 `02c0792`/`de137ed` → 三次修复 `36c271b` + E2E 种子 `9bae8ff`

## 三次复审修复摘要（相对 `de137ed`）

### Spec
- **P0**：FIRST_LAUNCH 必须门状态 SUBMITTED、存在 `current_submission`、L2 为当前活动阶段，决策绑定锁定提交；禁止 OPEN 门越级决策。
- **P1**：删除单人组合端点 `/first-launch-decision`；FE/E2E 走管理会结论 + 终审双端点；计划 `planned_end_at` 仅日程变化为 MINOR，资源字段为 IMPORTANT；迁移历史文件经 work_items 创建真实 FileObject/DocumentVersion/DeliverableRevision；新增 `POST /projects/{id}/publish-repair`。

### Standards
- **P1**：确认幂等键绑定当前基线；迁移任务/交付物走 work_items 公开服务；紧急完成授权先于 COMPLETED 返回，审计码 `emergency_execution.complete`；初始化按模板期望集合判断完整性并可补齐半初始化；`advance_stage` 仅依赖 stage_gates 模型，API schema 拆到各域；双认证服务有允许/拒绝/审计/幂等/并发测试。
- **P2**：store 使用 OpenAPI 生成工作台类型；移除无调用方别名。

### 门禁修复
- 阶段二/产品/验收夹具补齐已发布模板与 PRODUCT/RD/OPS。
- E2E 种子对已发布配置不再 `update_or_create`；内容升级时发布下一不可变版本。
- Prettier / OpenAPI / 契约类型漂移已对齐。

## 本轮实测证据

```text
scripts\check.ps1: All quality gates passed.
Backend pytest (MySQL): 287 passed
Frontend vitest: 17 files / 41 tests
Playwright (kernel + phase2 + phase3 + phase4): 15 passed
OpenAPI drift / contract type drift: clean
Docker backend + frontend image builds: passed
Legacy reference scan: passed
```

## 显式不在阶段4范围

- 运营监控深化、退市主链、外部系统真实联调
