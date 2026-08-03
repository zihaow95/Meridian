# 阶段6 存量产品、受控文件、站内通知与试用准备 —— 完成检查点

日期：2026-08-03

状态：**条件 GO（NO-GO 审阅后的 P1 整改已提交待复验；不得改为正式 GO，直至双轴 P0/P1=0 且全量门禁通过）**

对应计划：`docs/superpowers/plans/2026-07-30-phase-6-controlled-files-notifications-pilot-readiness.md`

对应矩阵：`docs/implementation/phase-6-test-matrix.md`

## 范围结论

- 受控文件目录化上传、材料历史链、专业确认、老品基线发布与材料门禁已落地。
- 站内通知为权威通道：六类 × 三级、未读/已读/关闭、Todo 同步；钉钉通道显式关闭。
- 非生产临时账号密码登录、LAN 启动边界与 `provision_pilot_user` 已落地；生产开启硬失败。
- `pilot` 域完成内部验收批次与反馈闭环；阶段6 **不**标记真实业务试用完成。
- 阶段6 GO **不**等于真实用户试用开始；下一步只能是阶段7生产化收尾。

## 本轮已执行验证（2026-08-03 P1 整改）

```text
Branch: codex/phase-6-controlled-files-notifications-pilot-readiness
Focused pytest: products + pilot + notifications + dual-control/publish + request_parsing
Frontend: LoginView.spec (4 passed); Prettier on LoginView / PilotBatchView
```

## 本轮未在检查点正文宣称通过（见矩阵分栏）

- 完整 `scripts\check.cmd`（含全量 pytest / 前端门禁 / 全套 Playwright / Docker）
- `scripts\verify-trd.ps1`（整改前审阅方曾通过；本轮整改后需重跑）
- Standards / Spec 双轴复审（P1 整改后待验收）

## GO 条件

只有在测试矩阵记录：**全量门禁通过、双轴审阅 P0/P1=0、本检查点与矩阵一致** 后，方可将状态改写为无条件 GO 并进入阶段7。

## 明确非目标

- 钉钉登录/通知/组织同步
- 公网入口与生产临时密码登录
- 真实业务用户首轮试用运行结论
