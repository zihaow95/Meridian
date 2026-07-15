# 阶段4 开发到首次上市 —— 完成检查点

日期：2026-07-15

状态：NO-GO 验收项已本地修复并提交待再审；完整 `scripts\check.cmd` 未在本轮全绿声明

对应计划：`docs/superpowers/plans/2026-07-14-phase-4-development-first-launch.md`

对应测试矩阵：`docs/implementation/phase-4-test-matrix.md`

基准审查点：`ed74816` → 原退出提交 `4cc99dc` → 本轮修复提交见 git HEAD

## NO-GO 修复摘要（相对 `4cc99dc`）

### Spec
- **P0**：默认执行模板补齐 D1–L3 任务/交付物；`InitializeProjectRuntime` 通过 `materialize_template_*` 与 `open_execution_gates_for_stages` 物化任务、交付物与 `StageGateInstance`；E2E 断言真实立项后集合非空，不再手工补门遮盖缺口。
- **P1**：FIRST_LAUNCH 支持独立经管会结论人；计划级别服务端推断；逾期扫描覆盖交付物/确认/阶段门/紧急执行；迁移过滤跨阶段依赖；紧急执行完成入口；工作台自定义任务/交付物 POST；`CHANGE_EFFECTIVE` 批准后调用 `PublishAndHandover`。

### Standards
- **P1**：决策先授权再返回幂等；幂等键组织/目标约束；跨领域写入走公开服务；计划/紧急执行 `select_for_update`；导入错误不回传 `IntegrityError` 原文。
- **P2**：工作台列表分页；OpenAPI 集合 schema；任务状态走 transition 动作端点；pytest 插件挂到根 `conftest`。

## 本轮实测证据

```text
ruff check apps tests: passed (post-fix)
mypy apps/projects apps/work_items apps/stage_gates apps/operations: passed
pytest tests/projects tests/stage_gates tests/work_items: 64 passed
pytest tests/api/test_phase4_openapi.py tests/api/test_openapi.py: 3 passed
frontend vue-tsc -b: passed
frontend prettier (projects specs + store): formatted
```

## 尚未在本检查点声明为“本机当次全绿”的项

- 完整 `scripts\check.cmd`（阶段0–4 全部门禁）——再审时复跑
- 阶段四 Playwright 与平台 E2E 全量回归——再审时复跑
- Docker 镜像构建与旧原型依赖扫描

## 显式不在阶段4范围

阶段5 经营事实/指标/信号；通用 BPM；钉钉内状态迁移。
