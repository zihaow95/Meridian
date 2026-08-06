# 阶段6 存量产品、受控文件、站内通知与试用准备 —— 测试矩阵

状态：**GO（最终整改复验Standards / Spec P0/P1/P2均为0）** — 分支 `codex/phase-6-controlled-files-notifications-pilot-readiness`，HEAD `62ffea3`。

对应范围：`docs/superpowers/specs/2026-07-30-phase-6-internal-pilot-scope.md`

对应计划：`docs/superpowers/plans/2026-07-30-phase-6-controlled-files-notifications-pilot-readiness.md`

对应检查点：`docs/implementation/phase-6-checkpoint.md`

> 状态取值：`未实现` / `进行中` / `已通过：<测试位置>` / `后置：<阶段>` / `阻塞：<原因>` / `本轮未跑`。
> 「已通过」必须对应本阶段6检出上的真实自动化证据。

## 1. 本轮命令与结果（2026-08-06）

| 检查 | 命令 | 结果 | 提交/备注 |
|---|---|---|---|
| 冷启动 Phase6 种子 | `scripts\check.cmd`内置`verify_phase6_seed_cold_start.py` | **通过**：20 products / 120 document versions / 16 stable fixture groups，两次seed行级稳定 | 当前HEAD `62ffea3` |
| 后端MySQL | `scripts\check.cmd` | **通过**：全套MySQL pytest及ruff/format/mypy/django check/migration drift通过 | 本轮独立全量门禁exit 0 |
| 前端 | `scripts\check.cmd` | **29 test files / 94 tests passed**；lint/format/typecheck/build通过 | OpenAPI生成类型无漂移 |
| Playwright | `scripts\check.cmd` | **通过**：整改方报告23 passed，本轮独立全量门禁exit 0 | 含阶段6老品、通知、pilot登录、反馈闭环 |
| Docker / 旧原型扫描 | `scripts\check.cmd` | **通过**：前后端镜像构建与legacy reference scan | `All quality gates passed.` |
| 目标迁移回滚测试 | `pytest tests/products/test_source_submission_uniq_migration.py -q` | **5 passed**（整改方提交前运行；完整门禁再次覆盖） | `0018→0016→0018`及索引清理 |
| `scripts\verify-trd.ps1` | `powershell -ExecutionPolicy Bypass -File scripts\verify-trd.ps1` | **通过**：6 documents / 92 requirements / 4 major stage gates | 当前HEAD `62ffea3` |
| Standards / Spec 双轴最终复验 | `/code-review`，`git diff 9690cdb...62ffea3` | **GO**：Standards 0；Spec 0 | P0/P1/P2均为0；见`phase-6-final-code-review.md` |

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
| 全量门禁本轮实测 | 已通过：2026-08-06，HEAD `62ffea3`，约531秒 |

## 6. P0 / P1 / P2 / P3（本轮）

| 级别 | 项 |
|---|---|
| P0 | 无 |
| P1 | 无；迁移回滚state/数据库约束漂移已关闭 |
| P2 | 无；测试helper索引污染已关闭 |
| P3 | D-1/D-2/D-3/D-5/D-6见计划19bis |

### 安全专项输入（不纳入本轮缺陷级别）

`npm ci`报告5个high severity advisory，但阶段6差异未修改依赖锁文件，且正式联网分类未获外部披露授权；该项进入阶段7安全专项输入，不以离线缓存结果宣称安全，也不混入P3体验问题。
