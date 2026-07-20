# 阶段4 开发到首次上市 —— 完成检查点

日期：2026-07-20

状态：第十二轮 NO-GO（ARCHIVE_ONLY PENDING 建档事务、部分激活 consume、真实中途失败恢复、mypy Project 缩窄）已本地修复；待再次验收（Docker Hub 拉镜像被环境阻断，其余门禁已绿）。

对应计划：`docs/superpowers/plans/2026-07-14-phase-4-development-first-launch.md`

对应测试矩阵：`docs/implementation/phase-4-test-matrix.md`

基准：`9417a54` → 十一次 `1feed8b` / `816336e` → 十二次（本检查点提交后回填哈希）

## 十二次复审修复摘要（相对 `816336e`）

### Standards
- **P1**：ARCHIVE_ONLY 全部 `stage_controlled_content` + `pending_version_public_id` 持久化放入明确 `transaction.atomic`；存储激活在该事务提交之后。
- **P1**：激活/恢复成功后收集并 consume `staging_relpath`；中途失败也会消费已成功文件的 stage，并持久化部分进度。
- **P2 hard**：`result.project` 先绑定局部变量再传入要求 `Project` 的方法，修复 mypy 门禁。

### Spec
- **P1**：真实多文件中途失败（首文件 ACTIVE、次文件失败）+ 同键重试全量激活并 consume；PENDING 建档失败事务回滚无孤立行。

## 本轮实测证据

```text
Base commits reviewed: 1feed8b, 816336e
Remediation commit: <pending local commit>
scripts\check.ps1 (re-run after fix):
  preflight / compose / ruff / mypy(261) / django / migrations: pass
  MySQL pytest: 317 passed
  OpenAPI drift: pass
  Frontend lint / prettier / typecheck / vitest(48) / build / schema.d.ts: pass
  Playwright: 16 passed
  Docker backend/frontend image: BLOCKED (docker.io auth timeout)
  Legacy reference scan: pass (run separately after Docker abort)
```

Docker 构建因 `auth.docker.io` 连接超时被环境阻断；非本轮代码回归。再次验收可在可访问 Docker Hub 的环境复跑镜像步骤。
