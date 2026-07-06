# 产品/项目全生命周期管理系统 TRD 索引

版本日期：2026-07-02

状态：已确认基线

## 文档入口

| 顺序 | 文档 | 范围 |
|---:|---|---|
| 00 | [系统总TRD](./00-system-master-trd.md) | 全局数据、API、权限、事务、文件和测试规则 |
| 01 | [提案—立案—立项TRD](./01-opportunity-case-project-trd.md) | 产品机会、重大阶段门、合并拆分和项目创建 |
| 02 | [产品档案、版本与迁移TRD](./02-product-profile-version-migration-trd.md) | 产品—版本—SKU—渠道、草稿发布和存量导入 |
| 03 | [开发—上市执行TRD](./03-development-launch-execution-trd.md) | 模板、阶段、任务、交付物、确认和首次上市 |
| 04 | [运营、迭代与退市TRD](./04-operations-iteration-retirement-trd.md) | 经营事实、风险、议题、迭代触发和退市 |
| 05 | [平台、权限、文件与集成TRD](./05-platform-permission-file-integration-trd.md) | 身份、RBAC+ABAC、文件、通知、审计和运行保障 |

## 阅读和实施顺序

1. 总体PRD和技术架构；
2. 00系统总TRD；
3. 05平台基础能力；
4. 01提案—立案—立项；
5. 02产品档案和版本；
6. 03开发—上市执行；
7. 04运营、迭代与退市；
8. 分阶段实施计划。

文档编号表示业务范围，不等于代码实施顺序。05中的身份、权限、审计、文件和事件发件箱必须作为其他领域的基础设施先落地。

## 统一约束

- 正式后端采用Python/Django/MySQL模块化单体；
- 对外API只使用UUID `public_id`；
- 阶段门只使用总TRD定义的统一结果代码；
- 四个重大阶段门不得由模板创建或删除；
- 业务写操作必须通过应用服务；
- 权限默认拒绝并在事务内复核；
- 关键业务审计与业务写入同事务；
- 文件、产品版本、模板、决策和数据快照不可覆盖历史；
- Redis和查询汇总不是业务事实来源；
- 所有子TRD需求必须可追踪至PRD编号。

## 自动检查

在Windows PowerShell中运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-trd.ps1
```

检查内容：

- 6份TRD是否存在；
- 92项PRD/NFR需求是否全部追踪；
- 子TRD基本结构；
- 上游文档引用；
- TODO/TBD占位；
- 四个重大阶段门代码；
- 非统一阶段门结果代码。

完整审计结论见[TRD完整性审计](./2026-06-30-trd-completeness-audit.md)。
