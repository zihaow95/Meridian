# 阶段5 运营、迭代和退市 —— 完成检查点

日期：2026-07-21

状态：**GO（已通过）** — OPS-001—014 已有自动化证据；全量门禁 `All quality gates passed.`；可推进阶段六。

对应计划：`docs/superpowers/plans/2026-07-20-phase-5-operations-iteration-retirement.md`

对应测试矩阵：`docs/implementation/phase-5-test-matrix.md`

基准：`edd50ce` → tip `c1a9a6a`（十七次提交，含配置→事实→汇总→风险→议题→迭代→退市→API→前端→E2E 与门禁修复）

## 验收结论（相对 `edd50ce...c1a9a6a`）

### 交付范围
- 经营数据源 / 监控范围 / 指标版本与权限种子；
- 接入批次、经营事实、人工有效值、汇总与快照；
- 风险规则与信号、经营议题、议题转迭代 DRAFT、退市重大门与执行；
- 受控 Operations API / OpenAPI、经营与退市工作台、双主链 Playwright E2E。

### 已知边界（有意保留）
- 议题/退市计划 GET 详情 API 偏薄时，前端通过列表/决策响应补齐；
- 重型数据源/指标/规则配置 UI 未做独立工作台；
- 迭代发布回写议题以单元覆盖为主（`test_iteration_result_consumer.py`）；E2E 断言转换至 DRAFT；
- 导出 CSV 有上限；未授权列表返回空 items。

## 最终门禁证据（验收环境）

```text
Reviewed range: edd50ce...c1a9a6a
scripts\preflight.ps1: pass
Ruff / format / mypy / Django / migration drift: pass
MySQL pytest: 405 passed
OpenAPI + frontend schema drift: pass
Frontend lint / Prettier / typecheck / build: pass
Vitest: 58 passed (22 files)
Playwright: 19 passed (workers: 1；含 operations-iteration-retirement 3)
Legacy scan: pass
Docker backend/frontend images: pass (meridian-backend:ci / meridian-frontend:ci)
scripts\verify-trd.ps1: pass (Documents: 6; Requirements: 92; Major stage gates: 4)
scripts\check.ps1: All quality gates passed.
```
