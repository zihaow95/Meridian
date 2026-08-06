# 阶段6 Spec / Standards 双轴终审

终审日期：2026-08-06

- 初审范围：`a39414b...cfac4d1`
- 第一轮整改复验：`cfac4d1...46f65ce`
- 第二轮整改复验：`46f65ce...6590384`
- 第三轮整改复验：`6590384...9690cdb`
- 最终整改复验：`9690cdb...62ffea3`

结论：**GO**。Standards轴与Spec轴P0/P1/P2均为0；阶段6全量门禁、TRD校验、迁移回滚/增量重跑证据和阶段检查点均通过。阶段6可以退出并允许启动阶段7实施，但不代表阶段7已开始、真实用户试用已启动或正式生产上线。

## Standards

### 通过：迁移回滚与索引清理闭环

- `0017`使用forward noop、reverse条件删除`products_material_source_submission_uniq`；删除前确保外键列仍有可用索引。
- `0018`继续在任何唯一DDL前拒绝重复脏数据；重新前进时幂等恢复唯一约束，并清理临时FK helper索引。
- 真实MySQL MigrationExecutor测试覆盖`0018→0016→0018`，同时验证迁移记录、Django state、MySQL约束和完整索引集合恢复一致。
- 测试helper记录是否创建非托管索引，三个`finally`均恢复迁移叶子并条件清理；未留下测试顺序依赖。
- 未发现新的硬性工程标准违反或有证据的代码气味；本轴P0/P1/P2均为0。

## Spec

### 通过：唯一业务事实与配置语义无回归

- 一个`source_submission`只能晋升一次的服务与MySQL约束保持有效。
- 重复脏数据在DDL前停线，失败无唯一约束半成品，清理后可重跑。
- 已关闭的嵌套`materials[].material_type_code`唯一性校验未被本次迁移整改触及。
- 未发现缺失、scope creep或错误实现；本轴P0/P1/P2均为0。

## 当前运行证据

- 2026-08-06在HEAD `62ffea3`顺序执行`scripts\check.cmd`，exit 0，约531秒。
- 通过项：环境预检、Compose配置、锁文件、Ruff、格式、mypy、Django check、迁移漂移、清洁E2E种子、清洁阶段6种子、后端MySQL全套、OpenAPI、前端lint/格式/类型/单测/build/契约漂移、完整阶段1—6 Playwright、前后端Docker镜像和旧原型引用扫描。
- 整改方在提交前运行目标迁移测试：5 passed；本轮完整门禁再次覆盖该测试文件。
- `scripts\verify-trd.ps1`通过：6份文档、92项需求、4个重大阶段门。
- `git diff --check`及阶段6证据文档本地链接校验通过。

## 证据边界与阶段7输入

- 本次审阅没有修改实现代码，只更新审核证据文档。
- 未提交的`.cursor/*`、`.cursorignore`、`.cursorindexingignore`和`CONTEXT.md`不属于阶段6提交范围。
- `npm ci`报告的5个high severity advisory继续作为阶段7安全专项输入；阶段6差异未修改依赖锁文件，未完成正式联网分类，不以离线缓存结果宣称安全。
- GO只关闭阶段6；阶段7生产化、容量、安全、备份恢复、发布和真实用户试用启动条件仍须按阶段7计划独立实施与验收。
