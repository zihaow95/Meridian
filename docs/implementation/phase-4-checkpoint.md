# 阶段4 开发到首次上市 —— 完成检查点

日期：2026-07-15

状态：第二次 NO-GO 复审项已本地修复；待再审。完整 `scripts\check.cmd` 未在本轮全绿声明

对应计划：`docs/superpowers/plans/2026-07-14-phase-4-development-first-launch.md`

对应测试矩阵：`docs/implementation/phase-4-test-matrix.md`

基准：`4cc99dc` → 首次修复 `8ad9cc2`/`30be1bb` → 本轮二次修复见 git HEAD

## 二次复审修复摘要（相对 `30be1bb`）

### Spec
- **P0**：初始化仅将当前阶段门设为 READY，未来阶段保持 OPEN；提交要求所属阶段 ACTIVE/READY_FOR_GATE；批准后 `advance_stage` 激活下一阶段并 `mark_gate_ready`。
- **P1**：FIRST_LAUNCH 拆成管理会结论与老板终审两个认证动作端点，禁止代填 UUID；计划级别读库真值推断，`planned_end_at` 变更为 IMPORTANT；逾期通知补组长/产品总监；迁移失败可见、尝试恢复负责人/成员/计划/历史文件；紧急完成必须写证据；CHANGE_EFFECTIVE 交接错误回传 API；部门缺失 fail-closed。

### Standards
- **P1**：迁移/提交授权先于幂等返回且组织作用域；初始化事务+锁，半初始化不视为完成；历史任务 IntegrityError 失败可见；阶段推进走 projects 公开服务。

### 契约
- OpenAPI 增补 request/response serializers；新增 transition / custom POST / emergency complete / dual FIRST_LAUNCH 路径；契约测试校验 path+method；已重新生成 `openapi/schema.yaml` 与前端 `schema.d.ts`。

## 本轮实测证据

```text
ruff check (phase-4 apps): passed
mypy apps/projects|work_items|stage_gates|operations + lifecycle_board + seed_e2e: passed
pytest projects/stage_gates/work_items/phase4_openapi: run in this turn
spectacular --validate: exit 0
frontend api:generate + typecheck: run in this turn
```

## 尚未声明全绿

- 完整 `scripts\check.cmd` / `check.ps1`
- Playwright 阶段四与全量 E2E、Docker 构建、旧依赖扫描

## 显式不在阶段4范围

阶段5 经营事实/指标/信号；通用 BPM；钉钉内状态迁移；seed_e2e 大场景拆分（P2 judgment，未阻塞核心合规）。
