# 阶段6 存量产品、受控文件、站内通知与试用准备 —— 测试矩阵

状态：**实现完成，验收证据更新中** — 分支 `codex/phase-6-controlled-files-notifications-pilot-readiness`。

对应范围：`docs/superpowers/specs/2026-07-30-phase-6-internal-pilot-scope.md`

对应计划：`docs/superpowers/plans/2026-07-30-phase-6-controlled-files-notifications-pilot-readiness.md`

对应检查点：`docs/implementation/phase-6-checkpoint.md`

> 状态取值：`未实现` / `进行中` / `已通过：<测试位置>` / `后置：<阶段>` / `阻塞：<原因>` / `本轮未跑`。
> 「已通过」必须对应本阶段6检出上的真实自动化证据。

## 1. 本轮命令与结果（2026-08-03）

| 检查 | 命令 | 结果 | 提交/备注 |
|---|---|---|---|
| 冷启动 Phase6 种子 | `uv run python tests/identity/verify_phase6_seed_cold_start.py` | **通过**：20 products / 120 document versions / 12 fixture groups，两次 seed 行级稳定 | 工作区含 seed 命令；基线 tip 见 git log |
| Phase6 Playwright | `npx playwright test controlled-files-notifications-pilot-readiness.spec.ts` | **4 passed (12.1s)** | 含老品幂等发布、六类通知、pilot 登录、反馈闭环 |
| LoginView 单测 | `npx vitest run src/modules/auth/LoginView.spec.ts` | **3 passed** | 含 vite 显式关闭 |
| 全量 `scripts\check.cmd` | `scripts\check.cmd` | **本轮未跑完整门禁**（检查点为条件 GO） | 已把 Phase6 冷启动与 E2E 纳入 `check.ps1` |
| `scripts\verify-trd.ps1` | `scripts\verify-trd.ps1` | **本轮未跑** | — |
| Standards / Spec 双轴审阅 | `/code-review` since phase6 base | **本轮未完成终审记录** | 进入无条件 GO 前必补 |

## 2. 基线已知缺陷处置

| 编号 | 状态 |
|---|---|
| B-1 employee_no MySQL 唯一 | 已通过：`test_employee_no_uniqueness.py` + `identity/0003` |
| B-2 todo open_slot | 已通过：notifications `0002` + 并发测试 |
| B-3 配置发布唯一 | 已通过：`current_published_slot` |
| B-4 AdminChangeRequest HTTP | 配置双人复核路径落地；其余后置评估 |
| B-5 DocumentLink / ObjectIdentityProvider | 登记 D-1/D-2，阶段6后裁决 |
| B-6 PublishLegacyBaseline 材料门禁 | 已通过：D-4 关闭 |
| B-7/B-8 通知/钉钉解耦 | 已通过：lifecycle + `ENABLE_DINGTALK_NOTIFICATIONS` |

## 3. 领域切片证据

| 切片 | 测试位置 | 状态 |
|---|---|---|
| 配置定义/双人发布/唯一槽 | `backend/tests/configuration/` | 已通过（既有套件） |
| 目录化上传/待整理 | `backend/tests/documents/`、`test_legacy_material_intake.py` | 已通过 |
| 材料链/确认/要求 | `backend/tests/products/test_material_*.py` | 已通过 |
| 老品基线 | `test_manual_legacy_baseline.py`、`test_legacy_baseline_material_gate.py` | 已通过 |
| 通知分类/生命周期/API | `backend/tests/notifications/` | 已通过 |
| employee_no / pilot 登录 | `backend/tests/identity/test_employee_no_*.py`、`test_pilot_*.py` | 已通过 |
| 试用批次与反馈 | `backend/tests/pilot/` | 已通过（11） |
| Phase6 种子冷启动 | `verify_phase6_seed_cold_start.py` | 已通过 |
| 纵向 E2E | `tests/e2e/controlled-files-notifications-pilot-readiness.spec.ts` | 已通过（4） |

## 4. 验收数据基线

| 项 | 目标 | 实际（冷启动种子） | 状态 |
|---|---|---|---|
| 存量产品 | ≤20 | 20 (`P6-PRD-*`) | 已通过 |
| 正式受控文件版本 | ≥100 | 100+ 当前 CONTROLLED | 已通过 |
| 可信历史版本 | ≥20 | 20（v1 非当前） | 已通过 |
| 待整理资料 | ≥10 | 10 (`phase6-pending-*`) | 已通过 |
| 单文件上限 | 50MB 配置 | `platform.file_upload.max_bytes=52428800` | 已通过 |
| 文件总量 | ≤2GB，不入 Git | 极小文本字节，仅 FILE_STORAGE_ROOT | 已通过 |
| 两次种子稳定 | 行级一致 | 冷启动校验通过 | 已通过 |

## 5. 门禁纳入

| 检查 | 结果 |
|---|---|
| `check.ps1` 增加 Phase6 冷启动步骤 | 已改 |
| `check.ps1` Playwright 增加 phase6 spec | 已改 |
| `playwright.config.ts` 使用 `seed_phase6_acceptance` | 已改 |
| 全量门禁本轮实测 | 本轮未跑 |

## 6. P0 / P1 / P2 / P3（本轮）

| 级别 | 项 |
|---|---|
| P0 | 无（以已跑套件为准） |
| P1 | 无（以已跑套件为准） |
| P2 | 全量 check / TRD / 双轴审阅待补证据后方可无条件 GO |
| P3 | D-1/D-2/D-3/D-5/D-6 见计划 19bis |
