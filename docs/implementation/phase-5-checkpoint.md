# 阶段5 运营、迭代和退市 —— 完成检查点

日期：2026-07-29

状态：**NO-GO（八次双轴复审待定）** — 七次复验遗留的 3 个 Spec P2 / 2 个 Standards P2 已补证：迁移后唯一约束真实拒绝重复 ACTIVE 分配；角色撤销在下一次授权请求立即生效；空库迁移与 E2E seed 重复执行纳入门禁；npm cache 只保留 `.env` 加载后的单一强制配置；检查点和测试矩阵改为本轮实测证据。双轴复审 GO 前不得推进阶段六。

对应计划：`docs/superpowers/plans/2026-07-20-phase-5-operations-iteration-retirement.md`

## 八次验收补证要点

- `MigrationExecutor` 真实执行 0010 → 0011 后，除碰撞去重、非空字段外，直接插入同业务键 ACTIVE 分配并断言 MySQL 唯一约束拒绝。
- 服务撤销角色分配后，立即发起下一次 `authorize` 请求并断言默认拒绝，证明 `authorization.role.revoke` 不依赖缓存失效窗口。
- 新增隔离临时数据库验证器：空库完整迁移、执行 `seed_e2e_user` 两次、断言 11 条角色分配保持稳定且 `scope_id` / `scope_key` 均已规范化；无论成功或失败均删除临时库。
- `scripts/check.ps1` 将上述空库种子验证纳入全量门禁，并移除 `.env` 加载前的重复 npm cache 清理，只保留加载后的强制可写配置。
- 本检查点与测试矩阵只记录 2026-07-29 本轮实际执行结果；历史人工声明不作为本轮通过证据。

## 本轮本地验证

```text
Reviewed range: 785f521...HEAD (eighth acceptance evidence remediation)
Focused MySQL pytest: 29 passed in 43.71s
Clean E2E seed: 11 normalized role assignments; repeat-run stable; temporary database removed
Full scripts\check.cmd: All quality gates passed
Backend MySQL pytest: 486 passed in 136.86s
Frontend Vitest: 22 files / 59 tests passed
Playwright E2E: 19 passed
OpenAPI drift: passed
Docker backend/frontend images: built successfully
Legacy reference scan: passed
TRD verification: 92 requirements / 4 major stage gates passed
```

本轮门禁另报告既有非阻塞告警：npm audit 4 个 high severity、MySQL `W036` 条件唯一约束警告及前端构建体积/插件告警；本次未修改依赖锁文件或扩大整改范围。

合并或推进阶段六前必须：Standards / Spec 双轴严格复审 GO，且 P0 / P1 / P2 均为 0。
