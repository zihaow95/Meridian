# 阶段5 运营、迭代和退市 —— 完成检查点

日期：2026-07-29

状态：**GO（阶段5验收通过；阶段6尚未开始）** — 七次复验遗留的 3 个 Spec P2 / 2 个 Standards P2，以及八次复审新增的冷库所有权、seed 稳定快照、资源关闭保真和用户激活时间漂移问题均已关闭。最终 Standards / Spec 双轴均为 P0=0、P1=0、P2=0。

对应计划：`docs/superpowers/plans/2026-07-20-phase-5-operations-iteration-retirement.md`

## 八次验收补证要点

- `MigrationExecutor` 真实执行 0010 → 0011 后，除碰撞去重、非空字段外，直接插入同业务键 ACTIVE 分配并断言 MySQL 唯一约束拒绝。
- 服务撤销角色分配后，立即发起下一次 `authorize` 请求并断言默认拒绝，证明 `authorization.role.revoke` 不依赖缓存失效窗口。
- 新增隔离临时数据库验证器：空库完整迁移、执行 `seed_e2e_user` 两次、断言 11 条角色分配保持稳定且 `scope_id` / `scope_key` 均已规范化；无论成功或失败均删除临时库。
- `scripts/check.ps1` 将上述空库种子验证纳入全量门禁，并移除 `.env` 加载前的重复 npm cache 清理，只保留加载后的强制可写配置。
- 本检查点与测试矩阵只记录 2026-07-29 本轮实际执行结果；历史人工声明不作为本轮通过证据。
- 八次 Standards 初审发现 `CREATE DATABASE` 失败后可能误删同名既有库；现仅在创建成功后删除，并用失败路径测试证明未获所有权时不会执行 `DROP`，清理失败也不覆盖原始异常。
- 八次 Spec 初审发现只比较角色分配数量不能证明幂等；现逐行比较用户、角色分配、Todo、运营产品目录、数据源、指标/规则、监控范围 7 组稳定资产，并直接校验 `scope_key = scope_type:scope_id`。
- E2E Todo 的 `source_id` 改为用户 `public_id`；监控范围复用已有来源决策，冷库首次使用稳定决策标识，避免重复 seed 产生漂移记录。
- 八次再复审补充覆盖所有清理动作：DROP、cursor close、connection close 均独立尝试；有主异常时只附加报告清理错误，不再覆盖 migrate/seed 原始失败。
- 三名 E2E 用户只有首次创建、缺少激活时间或从非 ACTIVE 恢复时才写 `activated_at`；用户快照现包含该字段并证明重复 seed 不漂移。

## 本轮本地验证

```text
Code review range: 785f521...9402baa (eighth acceptance evidence remediation)
Focused MySQL pytest: 31 passed in 57.66s
Clean E2E seed: 11 normalized role assignments; 7 fixture groups stable; temporary database removed
Full scripts\check.cmd: All quality gates passed
Backend MySQL pytest: 488 passed in 158.12s
Frontend Vitest: 22 files / 59 tests passed
Playwright E2E: 19 passed
OpenAPI drift: passed
Docker backend/frontend images: built successfully
Legacy reference scan: passed
TRD verification: 92 requirements / 4 major stage gates passed
```

本轮门禁另报告既有非阻塞告警：npm audit 4 个 high severity、MySQL `W036` 条件唯一约束警告及前端构建体积/插件告警；本次未修改依赖锁文件或扩大整改范围。

验收结论：Standards GO；Spec GO；P0 / P1 / P2 均为 0。阶段5可以结束，阶段6仍需单独批准和规划后方可开始。
