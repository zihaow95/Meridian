# TRD 04：运营监控、迭代与退市

版本：V0.1

日期：2026-06-30

状态：已确认基线

基线确认日期：2026-07-02

上游文档：

- `../prd/04-operations-iteration-retirement-prd.md`
- `00-system-master-trd.md`
- `01-opportunity-case-project-trd.md`
- `02-product-profile-version-migration-trd.md`
- `03-development-launch-execution-trd.md`

## 1. 范围与非目标

本文设计SKU × 渠道 × 时间经营事实、数据接入、人工有效值、指标汇总、风险信号、经营议题、迭代提案转换和退市重大阶段门。

首期不建设数据仓库、实时流平台、任意公式脚本引擎、复杂风险等级、自动处罚或自动启动迭代项目。

## 2. 模块与依赖

- `operations`：经营事实、指标、风险信号、议题和退市计划；
- `integrations`：数据源、接入批次、映射和错误；
- `products`：产品、SKU、渠道及发布结果；
- `opportunities`：从议题创建迭代提案；
- `stage_gates`：退市重大阶段门；
- `projects`：关联迭代或退市准备项目；
- `authorization`、`audit`、`notifications`：权限、审计和提醒。

外部经营事实的权威来源仍是专业系统；本系统保存标准化副本、人工有效值和决策快照。

## 3. 数据流

```mermaid
flowchart LR
    S["接口 / Excel / 手工"] --> B["接入批次"]
    B --> T["暂存校验"]
    T --> F["标准经营事实"]
    F --> E["当前有效值"]
    E --> A["SKU / 产品汇总"]
    A --> R["风险规则"]
    R --> G["风险信号"]
    G --> I["经营议题"]
    I --> O["产品迭代提案"]
    I --> X["退市阶段门"]
```

业务最小标准粒度为SKU、渠道和时间期间。原始粒度必须保留，不允许把季度数据拆成伪造的日数据。

## 4. 表设计

### 4.1 `integrations_data_source`

| 字段 | 说明 |
|---|---|
| `source_code`、`name` | 数据源标识 |
| `source_type` | API/FILE/MANUAL |
| `owner_department_id` | 数据责任部门 |
| `sensitivity_level` | 数据等级 |
| `status` | ACTIVE/INACTIVE |
| `configuration_version_id` | 连接和映射配置版本，不含明文凭据 |

凭据由部署密钥管理，不写入数据库配置正文或审计日志。

### 4.2 `integrations_ingestion_batch`

| 字段 | 说明 |
|---|---|
| `source_id` | 数据源 |
| `batch_key` | 来源批次幂等键 |
| `input_file_version_id` | 文件导入时使用 |
| `business_period_from/to` | 业务期间 |
| `status` | RECEIVED/VALIDATING/READY/IMPORTING/PARTIAL_SUCCESS/SUCCESS/FAILED |
| `total_count`、`success_count`、`warning_count`、`error_count`、`skipped_count` | 统计 |
| `started_at`、`completed_at` | 运行时间 |

唯一：`source_id, batch_key`。

### 4.3 `integrations_ingestion_row`

保存批次行号、外部业务键、原始值摘要、标准化结果、SKU/渠道映射、错误和警告。完整原始载荷仅在必要时加密保存或引用受控文件，不复制无关个人信息。

状态：

- VALID；
- WARNING；
- ERROR；
- UNMAPPED；
- IMPORTED；
- SKIPPED。

结构错误和未映射阻止写入事实；合理范围异常默认WARNING并允许授权用户确认。

### 4.4 `operations_metric_definition_version`

| 字段 | 说明 |
|---|---|
| `metric_code`、`name` | 指标 |
| `version_number` | 版本 |
| `value_type`、`unit`、`currency` | 值语义 |
| `source_field_codes` | 来源字段 |
| `calculation_type` | SUM/AVERAGE/LAST/RATIO/CONTROLLED_RULE |
| `aggregation_rule` | SKU、产品和时间汇总规则 |
| `window_definition` | 日、周、月、季度或滚动窗口 |
| `coverage_requirement` | 最低数据覆盖要求 |
| `valid_from`、`valid_to` | 口径适用时间 |
| `status` | DRAFT/PUBLISHED/RETIRED |

不允许在数据库保存并执行任意Python或SQL表达式。复杂指标使用代码中受控计算器代码加版本化参数。

### 4.5 `operations_operating_fact`

| 字段 | 类型 | 说明 |
|---|---|---|
| `sku_id` | bigint | SKU |
| `channel_id` | bigint | 渠道 |
| `metric_definition_id` | bigint | 指标版本 |
| `period_granularity` | varchar(12) | DAY/WEEK/MONTH/QUARTER |
| `period_start`、`period_end` | date | 实际粒度期间 |
| `numeric_value` | decimal(24,6) | 数值 |
| `text_value` | text | 非数值指标，可空 |
| `unit`、`currency` | varchar | 单位与币种 |
| `source_id`、`batch_id`、`source_record_key` | bigint/varchar | 来源 |
| `fact_status` | varchar(16) | VALID/SUPERSEDED/INVALID |
| `source_timestamp` | datetime | 外部事实时间 |

业务唯一键：来源、外部记录键、指标、SKU、渠道和期间。迟到修订新增事实版本并将旧版本标为SUPERSEDED，不原位覆盖。

### 4.6 `operations_manual_effective_value`

| 字段 | 说明 |
|---|---|
| `sku_id`、`channel_id`、`metric_definition_id` | 业务对象与指标 |
| `period_start`、`period_end`、`period_granularity` | 业务期间 |
| `original_fact_id` | 当前来源事实 |
| `numeric_value`、`text_value` | 人工确认值 |
| `reason` | 修改说明 |
| `valid_from`、`valid_to` | 有效区间 |
| `status` | ACTIVE/REVOKED/SUPERSEDED |
| `active_slot` | ACTIVE时固定为1，其他状态为空 |
| `confirmed_by`、`confirmed_at` | 经营监督人 |

唯一约束覆盖SKU、渠道、指标、期间和`active_slot`；利用MySQL允许多个NULL的规则，数据库级保证同一业务键只有一个ACTIVE人工值。撤销后恢复选取当前有效来源事实。原始事实始终保留。

### 4.7 `operations_metric_aggregate`

保存可重建的查询汇总：

- grain_type：SKU/PRODUCT；
- grain_id；
- channel_id，可空；
- metric_definition_id；
- period；
- value；
- coverage_rate；
- source_count；
- has_manual_value；
- calculated_at；
- calculation_run_id。

汇总不是原始权威事实，可以根据事实重建。口径不兼容的渠道不强行相加，结果标记`NOT_COMPARABLE`。

### 4.8 `operations_risk_rule_version`

| 字段 | 说明 |
|---|---|
| `rule_code`、`version_number` | 规则版本 |
| `metric_codes` | 使用指标 |
| `evaluator_code` | 代码中受控规则计算器 |
| `parameters_json` | 阈值、窗口和适用范围 |
| `scope_type` | PRODUCT/SKU/SKU_CHANNEL |
| `status` | DRAFT/PUBLISHED/RETIRED |
| `valid_from` | 新周期生效时间 |

“四分之一效期最低生产量”使用固定受控计算器，参数包含最低生产量、效期、窗口、目标消化比例和适用SKU/渠道。

### 4.9 `operations_risk_signal`

| 字段 | 说明 |
|---|---|
| `rule_version_id` | 触发规则 |
| `scope_type`、`scope_id`、`channel_id` | 信号范围 |
| `scope_key` | 规范化范围键，消除空值唯一性歧义 |
| `period_start`、`period_end` | 触发期间 |
| `status` | NEW/VIEWED/CLOSED/ESCALATED |
| `actual_value`、`threshold_value` | 实际与阈值 |
| `formula_snapshot` | 公式和参数摘要 |
| `data_snapshot_id` | 不可变依据 |
| `coverage_status` | SUFFICIENT/INSUFFICIENT |
| `closed_reason`、`closed_by`、`closed_at` | 关闭信息 |

唯一：`rule_version_id, scope_key, period_start, period_end`。数据覆盖不足时记录评估结果但不生成“正常”或风险信号。

### 4.10 `operations_signal_recalculation`

迟到数据或人工值变化后保存原信号、新计算值、原因、时间和影响结论。历史信号及被决策引用快照不重写；必要时生成新信号或标记当前显示已重算。

### 4.11 `operations_operating_issue`

| 字段 | 说明 |
|---|---|
| `business_no`、`title` | 议题编号和标题 |
| `product_id` | 产品 |
| `status` | PENDING/ANALYZING/OBSERVING/ACTIONING/CONVERTED_TO_PROPOSAL/RETIREMENT_REVIEW/CLOSED |
| `owner_id` | 经营监督人或指定负责人 |
| `phenomenon_summary` | 现象摘要 |
| `recommendation_type` | 继续观察、调价、渠道、市场、供应、迭代、暂停、退市、关闭 |
| `data_snapshot_id` | 创建时数据快照 |
| `target_review_at` | 建议研判时间 |
| `linked_opportunity_id`、`linked_project_id` | 后续链路，可空 |

### 4.12 `operations_issue_signal`

`issue_id`、`signal_id`、`is_primary`、`active_primary_slot`、`linked_at`、`unlinked_at`。

活动主关联的`active_primary_slot`为1，结束后为空；唯一约束`signal_id, active_primary_slot`保证一个信号同一时间只能属于一个未关闭主议题。一个议题可有多个信号。

### 4.13 `operations_issue_decision`

追加保存研判结论、行动说明、责任人、计划时间、决策材料快照和操作人。轻量行动不扩展为复杂审批子系统。

### 4.14 `operations_retirement_plan`

| 字段 | 说明 |
|---|---|
| `product_id`、`issue_id`、`project_id` | 来源 |
| `scope_snapshot` | 产品版本、SKU和渠道范围 |
| `inventory_plan` | 库存和临期处理 |
| `supply_contract_impact` | 供应与合同影响 |
| `customer_market_plan` | 客户和市场沟通 |
| `replacement_plan` | 替代产品/用户承接 |
| `stop_production_at`、`stop_sale_at`、`retire_at` | 计划日期 |
| `status` | DRAFT/SUBMITTED/APPROVED/EXECUTING/COMPLETED/PASSED |
| `stage_gate_id` | 退市重大阶段门 |

退市计划是经营议题下的轻量执行对象，不建立独立重型子系统。

## 5. 数据接入

### 5.1 接口

- 拉取或接收数据先创建批次；
- 同步失败不删除或覆盖上次有效事实；
- 重试沿用批次幂等键或创建明确重试批次；
- 部分失败保留成功事实和错误行；
- 数据映射缺失进入待处理区。

### 5.2 Excel/CSV

```text
上传 → 解析 → 结构校验 → 映射 → 预览 → 用户确认 → 写入事实
```

确认前不写入有效事实。结果报告包含新增、修订、跳过、警告和错误行。

### 5.3 手工数据

手工录入作为MANUAL数据源进入相同批次和校验链路；人工有效值则使用独立覆盖表，两者不能混淆。

### 5.4 校验

结构性错误：

- SKU/渠道无法映射；
- 时间、数值、单位或币种非法；
- 必需业务键缺失；
- 批次内重复且无法确定版本。

结构性错误阻止该行。合理范围异常只警告。用户确认WARNING时记录确认人。

## 6. 当前有效值

`ResolveEffectiveOperatingValue`按以下顺序：

1. 当前ACTIVE人工确认值；
2. 当前有效来源事实，按数据源优先级和来源时间选择；
3. 无有效值则返回数据不足。

页面和汇总显示：

- 有效值；
- 是否人工确认；
- 原始来源；
- 来源更新时间；
- 适用期间；
- 数据覆盖状态。

经营监督人只能在授权产品/渠道范围内创建、修改或撤销人工值，无需双人复核。

## 7. 汇总与指标

- 先按SKU、渠道和真实时间粒度计算；
- 再按指标定义汇总至SKU和产品；
- 汇总结果必须可下钻到参与计算的事实；
- 人工值参与计算并设置标记；
- 比例指标使用分子分母重算，不能直接平均比例；
- 不同币种或不兼容口径不汇总；
- 指标版本只用于其生效后的新计算周期；
- 决策快照固定保存指标版本、覆盖率、值和来源。

汇总由Celery批次计算，可按事实变更增量重算。看板不在每次请求中扫描全部明细事实。

## 8. 风险规则与信号

### 8.1 规则执行

`EvaluateRiskRules`只对：

- 已发布规则；
- 适用产品/SKU/渠道；
- 已结束或达到计算条件的时间窗口；
- 覆盖率满足要求的数据执行。

结果包括公式、规则版本、实际值、阈值、期间、数据快照和解释文本。

### 8.2 信号状态

| 当前 | 命令 | 目标 |
|---|---|---|
| NEW | mark_viewed | VIEWED |
| NEW/VIEWED | close | CLOSED |
| NEW/VIEWED | escalate | ESCALATED |

经营监督人可直接关闭，必须填写简短理由。新周期再次触发创建新信号。相同规则、范围和期间的重复执行返回既有信号。

系统只创建风险信号，不自动创建经营议题、提案或项目。

## 9. 经营议题

### 9.1 创建

经营监督人选择一个或多个信号创建议题，系统锁定信号依据和当前数据快照。也允许产品组合复盘等无风险信号来源创建议题，但必须记录来源类型和材料。

### 9.2 状态

```text
PENDING → ANALYZING
          ├─ OBSERVING
          ├─ ACTIONING
          ├─ CONVERTED_TO_PROPOSAL
          ├─ RETIREMENT_REVIEW
          └─ CLOSED
```

继续观察或轻量行动可再次进入ANALYZING。已转换提案或进入退市评审后不可删除。

### 9.3 权限

经营监督人可首次研判、关闭轻微信号和议题、记录轻量行动。该角色不自动获得成本、供应商、工艺或立项全文访问权。

## 10. 转产品迭代提案

`ConvertIssueToIterationProposal`：

1. 锁定议题并校验尚未转换；
2. 校验指定提案负责人当前具备资格；
3. 调用01领域创建产品迭代提案草稿；
4. 预填产品、版本、信号、数据快照、问题摘要、建议方向和SKU/渠道；
5. 建立议题—机会来源关系；
6. 将议题置为`CONVERTED_TO_PROPOSAL`；
7. 写入审计和通知事件。

转换只创建草稿，不自动正式提交。之后必须完整经过提案、立案和立项。唯一约束`issue_id, conversion_type=ITERATION_PROPOSAL`防止重复转换。

迭代项目发布后，消费`product_version.published`事件，将项目、发布版本、生效时间和结果回写议题。

## 11. 退市

### 11.1 发起

经营议题、产品组合复盘、质量合规、战略调整或授权管理者可以创建退市计划。无经营议题来源时系统创建来源类型为DIRECT的轻量议题，以保持统一履历。

### 11.2 提交检查

`ValidateRetirementSubmission`检查：

- 退市产品、版本、SKU和渠道范围；
- 销售、毛利、库存、临期和客诉快照；
- 供应、合同和渠道影响；
- 库存处理和售后计划；
- 客户沟通和替代方案；
- 停产、停售和退市日期；
- 受控文件版本；
- 数据覆盖不足说明。

### 11.3 重大阶段门

`PRODUCT_RETIREMENT`：

- 记录经管会整体结论；
- 记录老板最终决策；
- 以老板决策迁移状态；
- 锁定退市范围、计划、数据和文件快照；
- 不记录个人投票。

结果支持通过、带例外通过、待补充、暂缓推进和Pass。带例外说明不能替代老板最终决策。

### 11.4 执行

`ExecuteRetirementPlan`在批准后按日期执行：

- 设置产品、版本、SKU和渠道的计划停产/停售/退市状态；
- 到达日期时调用02领域状态变更服务；
- 保留产品档案、历史经营事实和决策；
- 继续展示剩余库存、临期和售后跟踪；
- 完成所有计划动作后关闭计划和议题。

定时任务只执行已获批准的计划，不自行决定退市。执行失败保留批准结果，计划进入`EXECUTION_ERROR`派生状态并通知责任人。

## 12. 数据快照

重大研判、转迭代和退市阶段门使用不可变数据快照，至少保存：

- 产品、SKU、渠道和期间；
- 指标代码及版本；
- 实际值、阈值、覆盖率和人工值标记；
- 参与计算事实ID清单或可验证摘要；
- 生成时间；
- 生成者和用途。

迟到数据、人工值撤销或指标口径变化不改写快照。

## 13. 查询模型和页面

### 13.1 产品经营看板

- 产品核心指标、趋势和覆盖率；
- SKU/渠道贡献和下钻；
- 更新时间和人工值标记；
- 风险信号、经营议题和关联项目。

### 13.2 风险中心

- 按产品、指标、期间、状态和责任人筛选；
- 展示公式、阈值、实际值、数据覆盖和来源；
- 展示关闭、升级和重算历史。

### 13.3 议题工作台

- 信号与数据快照；
- 研判和轻量行动；
- 关联提案、项目、发布版本或退市计划；
- 最终结果。

首期使用MySQL查询和汇总表，不引入独立分析数据库或搜索引擎。

## 14. API设计

| 方法与路径 | 用途 |
|---|---|
| `POST /api/v1/operating-data/batches` | 创建文件/手工批次 |
| `GET /api/v1/operating-data/batches/{id}` | 批次状态和错误 |
| `POST /api/v1/operating-data/batches/{id}/confirm` | 确认写入事实 |
| `GET /api/v1/operating-data/unmapped` | 待映射数据 |
| `POST /api/v1/operating-values/overrides` | 创建人工有效值 |
| `POST /api/v1/operating-values/overrides/{id}/revoke` | 撤销人工值 |
| `GET /api/v1/products/{id}/operating-summary` | 产品经营看板 |
| `GET /api/v1/skus/{id}/operating-summary` | SKU汇总和下钻 |
| `GET /api/v1/risk-signals` | 风险中心 |
| `POST /api/v1/risk-signals/{id}/view` | 标记已查看 |
| `POST /api/v1/risk-signals/{id}/close` | 关闭信号 |
| `POST /api/v1/risk-signals/{id}/escalate` | 升级经营议题 |
| `GET/POST /api/v1/operating-issues` | 议题查询和创建 |
| `POST /api/v1/operating-issues/{id}/decisions` | 记录研判 |
| `POST /api/v1/operating-issues/{id}/iteration-proposal` | 转迭代提案 |
| `POST /api/v1/retirement-plans` | 创建退市计划 |
| `POST /api/v1/retirement-plans/{id}/validate` | 退市预检 |
| `POST /api/v1/retirement-plans/{id}/submit` | 提交退市阶段门 |
| `POST /api/v1/stage-gates/{id}/major-decision` | 退市重大决策 |

## 15. 权限动作

- `operating_fact.read`、`operating_detail.export`；
- `ingestion_batch.create`、`confirm`、`retry`；
- `mapping.resolve`；
- `manual_effective_value.create`、`modify`、`revoke`；
- `risk_signal.read`、`close`、`escalate`；
- `operating_issue.create`、`analyze`、`close`；
- `iteration_proposal.convert`；
- `retirement_plan.create`、`submit`、`execute`；
- `retirement.management_conclusion.record`；
- `retirement.final_decision.record`；
- `metric_rule.configure`。

权限同时限制产品、SKU、渠道、数据等级和导出动作。

## 16. 并发、幂等与约束

- 接入批次以数据源和批次键幂等；
- 事实业务键和来源版本唯一；
- 人工有效值同一业务键只能有一个ACTIVE；
- 风险信号按规则、范围和期间唯一；
- 一个信号只能有一个活动主议题；
- 议题转迭代提案只能成功一次；
- 退市阶段门只能决策一次；
- 退市执行按计划动作和日期幂等；
- 指标和风险规则发布后不可修改；
- 决策快照不可更新。

## 17. 领域事件与异步任务

领域事件：

- `operating_fact.imported`；
- `operating_value.overridden`；
- `risk_signal.created`、`risk_signal.closed`；
- `operating_issue.created`、`operating_issue.decided`；
- `iteration_proposal.created`；
- `retirement.approved`、`retirement.completed`。

异步任务：

- API同步和文件解析；
- 指标汇总和增量重算；
- 风险规则评估；
- 迟到数据影响重算；
- 未查看信号和议题截止提醒；
- 已批准退市计划日期执行；
- 数据接入失败重试和通知。

## 18. 审计事件

必须审计：

- 数据源和规则版本发布；
- 接入批次确认、重试和错误处理；
- 未映射数据人工归属；
- 人工有效值创建、修改和撤销；
- 风险信号生成、查看、关闭和升级；
- 经营议题研判和轻量行动；
- 转迭代提案；
- 退市计划、重大决策和执行；
- 经营明细导出；
- 迟到数据重算及对历史信号的影响。

## 19. 错误码

| 错误码 | 含义 |
|---|---|
| `INGESTION_BATCH_DUPLICATE` | 批次已存在 |
| `OPERATING_DATA_STRUCTURE_INVALID` | 结构性数据错误 |
| `OPERATING_DATA_MAPPING_REQUIRED` | SKU或渠道待映射 |
| `OPERATING_UNIT_MISMATCH` | 单位或币种不兼容 |
| `MANUAL_VALUE_SCOPE_FORBIDDEN` | 无权修改该产品/渠道 |
| `MANUAL_VALUE_ALREADY_ACTIVE` | 已有当前人工有效值 |
| `METRIC_DATA_INSUFFICIENT` | 数据覆盖不足 |
| `METRIC_DEFINITION_NOT_PUBLISHED` | 指标口径未发布 |
| `RISK_SIGNAL_ALREADY_PROCESSED` | 信号状态不允许当前操作 |
| `OPERATING_ISSUE_ALREADY_LINKED` | 信号已有活动主议题 |
| `ITERATION_PROPOSAL_ALREADY_CREATED` | 议题已转换提案 |
| `PROPOSAL_OWNER_NOT_ELIGIBLE` | 指定负责人无提案资格 |
| `RETIREMENT_SUBMISSION_INCOMPLETE` | 退市材料不完整 |
| `RETIREMENT_ALREADY_DECIDED` | 退市阶段门已完成 |
| `RETIREMENT_EXECUTION_FAILED` | 已批准计划执行失败 |

## 20. 测试设计

### 20.1 数据接入和有效值

- 接口、Excel和手工数据进入统一批次；
- 结构错误阻止单行，范围异常只警告；
- 同批次重试不重复累计；
- 接口失败不覆盖上次有效事实；
- 人工值参与汇总但保留原值；
- 撤销人工值恢复当前来源值；
- 季度数据不能伪造成日数据。

### 20.2 指标和信号

- 产品汇总可下钻到SKU和渠道事实；
- 比例按分子分母重算；
- 口径不兼容时不强行相加；
- 数据不足不生成正常结论或信号；
- 四分之一效期最低生产量规则展示参数和计算依据；
- 重复规则执行只产生一个信号；
- 新周期可再次触发；
- 迟到数据不改写历史决策快照。

### 20.3 议题和迭代

- 经营监督人可直接关闭轻微信号；
- 一个议题关联多个信号；
- 一个信号不能同时进入两个活动主议题；
- 转换仅创建预填提案草稿；
- 无提案资格的负责人不能转换；
- 迭代项目发布后结果回写议题。

### 20.4 退市

- 退市材料缺失时不能提交；
- 经管会结论和老板决策同时保留；
- 老板决策决定流程状态；
- 批准后按计划停用而不物理删除；
- 执行失败保留批准结果并可重试；
- 历史档案、经营数据和剩余库存跟踪可访问。

### 20.5 权限和并发

- 经营监督人不因角色看到成本、供应商和工艺；
- 未授权人员不能导出经营明细；
- 两次人工值并发创建只有一个ACTIVE；
- 两次议题转换只创建一个提案；
- 两次退市决策只有一个完成。

## 21. 需求追踪

| 需求 | 技术实现 |
|---|---|
| OPS-001 | `OperatingFact`标准粒度和真实期间 |
| OPS-002 | API、文件和手工接入批次 |
| OPS-003 | 暂存行、校验、幂等和结果报告 |
| OPS-004 | 人工有效值与原始事实分离 |
| OPS-005 | 可重建汇总表及下钻 |
| OPS-006 | 版本化指标和受控规则计算器 |
| OPS-007 | 风险规则、唯一信号和轻量状态机 |
| OPS-008 | 经营议题、信号关系和研判记录 |
| OPS-009 | `ConvertIssueToIterationProposal` |
| OPS-010 | 产品发布事件回写议题 |
| OPS-011 | `PRODUCT_RETIREMENT`重大阶段门 |
| OPS-012 | 退市计划和历史保留 |
| OPS-013 | 经营看板、风险中心和议题查询模型 |
| OPS-014 | 对象范围、数据等级和导出权限 |

## 22. 未决项

无阻塞实施的架构未决项。首批指标、数据源优先级、覆盖率、风险阈值和具体渠道映射作为版本化配置维护。
