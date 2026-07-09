# Project Meridian 阶段3产品档案与存量迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付统一产品档案、产品版本、SKU、渠道配置和存量产品导入闭环，使阶段2创建的研发中产品草稿可以演进为受控产品档案，并满足 PIM-001 至 PIM-014、GLB-004、GLB-005、GLB-010 和 NFR-006 的阶段验收。

**Architecture:** 保持 Django 模块化单体和 Vue 3 前端；`products` 是产品定义、产品版本、SKU、渠道配置、产品变更集和存量导入的权威写模型，`configuration` 提供发布后的属性 Schema 版本，`documents` 提供受控文件版本引用，`authorization`、`audit`、`platform.outbox` 继续承担默认拒绝、审计和可靠事件。阶段3不展开 D1-L3 项目执行、首次上市阶段门、经营监控和退市流程，只提供可被阶段4/5 调用的产品档案、草稿、发布和迁移能力。

**Tech Stack:** Python 3.13、Django 5.2、Django REST Framework、MySQL 8.0、Redis、Celery 5.6、jsonschema、Vue 3、TypeScript、Pinia、Element Plus、Vitest、Playwright、Docker Compose、GitHub Actions。

**Status:** 待实施

**Date:** 2026-07-09

## Global Constraints

- 正式工程根目录固定为 `D:\Projects\Meridian`。
- 阶段3从阶段2已完成状态开始；阶段2证据为 `docs/implementation/phase-2-checkpoint.md`、`docs/implementation/phase-2-test-matrix.md` 和当前 `README.md`。
- 阶段3范围固定为产品档案与存量迁移，不实现 D1-L3 项目执行模板、任务依赖、交付物专业确认工作台、`FIRST_LAUNCH` 重大阶段门、运营事实、经营议题、退市、真实钉钉集成和生产化发布。
- 产品机会资产、项目实例、产品资产、产品版本、SKU 和渠道配置保持独立身份，不得用单表状态字段或任意 JSON 模拟主模型。
- `ProductChangeSet` 是阶段3统一草稿/变更/导入基线模型；阶段2的 `ProductDraft` 只能作为兼容迁移入口，不得继续扩展为完整产品档案事实表。
- 可变草稿与不可变发布版本分开存储；历史产品版本、属性快照、文件素材、确认和批准依据不可覆盖。
- 固定核心字段使用实体列；可配置属性组使用发布后的 Schema 版本和经校验的 `values_json`，不得把产品名称、状态、条码、价格等核心字段复制到属性 JSON 作为权威事实。
- 所有关键命令必须通过应用服务执行，在 MySQL 事务内重新判权、校验 `version_no`、写审计和登记 outbox；Redis/Celery 不保存唯一业务事实。
- 权限采用 RBAC + ABAC + 审计，默认拒绝；列表先过滤，详情再按字段/文件动作投影；平台管理员不能读取高敏业务值。
- 所有新增 API 使用 `/api/v1`、UUID `public_id`、统一错误结构和 OpenAPI 生成类型；前端不能长期维护手写重复类型。
- 测试必须使用 MySQL；并发、唯一约束、发布回滚、导入幂等和权限拒绝不得用 SQLite 或纯 mock 替代。

---

## 1. 基线决策与阶段边界

- 阶段2已创建 `ProductAsset`、`ProductDraft`、项目到产品草稿的来源关系，以及只读 `ProductDraftDetailView`。阶段3必须在此基础上演进，不重建阶段2提案到立项闭环。
- 阶段3的核心领域术语固定如下：
  - `ProductAsset`：长期产品身份。
  - `ProductVersion`：某一时期的核心产品定义，不可原位覆盖。
  - `SKU`：实际售卖、库存和效期管理单元，必须属于一个 `ProductVersion`。
  - `ChannelConfiguration`：SKU 在具体渠道下的带时间版本配置。
  - `ProductChangeSet`：新品草稿、老品迭代草稿、存量导入基线和录入纠正的统一变更载体。
  - `AttributeSchemaVersion`：已发布属性组和字段定义的不可变版本。
  - `ImportBatch` / `ImportItem`：存量产品迁移批次和逐行处理事实。
- `products` 的外部 Interface 应保持深：调用方通过 `CreateProductChangeSet`、`EditProductChangeSet`、`SubmitProductConfirmation`、`PublishProductChangeSet`、`ConfirmLegacyImportBatch` 等命令完成业务动作，不直接拼接多表写入。
- `configuration` 已有 `ConfigurationVersion` 和 `ConfigurationSnapshot`，阶段3可以复用其不可变配置思想，但产品属性 Schema 需要明确查询和校验 Interface，不能让 API 层直接解释任意配置 JSON。
- `documents` 已有 `DocumentVersion`、`VersionStatus`、下载票据和文件补偿，阶段3只建立产品素材到受控文件版本的引用，不复制文件二进制。
- 本计划默认不新增搜索引擎；产品查询使用受控查询服务、MySQL 索引和分页。

## 2. 完成定义

1. 产品资产、产品版本、版本适用范围、SKU、渠道配置、营养表、产品素材、属性组值、属性确认、外部绑定、导入批次和导入行均有模型、迁移和 MySQL 约束。
2. 阶段2立项后创建的产品草稿能够进入 `ProductChangeSet(NEW_PRODUCT)`，并保留项目、候选方案和来源机会追溯。
3. 老品迭代可以基于当前有效档案创建 `ProductChangeSet(ITERATION)`，保存基线指纹并在基线变化后阻止旧草稿发布。
4. 固定字段和可配置属性组均可编辑、校验、差异比较、提交确认和按字段权限投影。
5. 关键属性组确认绑定 `group_value_id + content_hash`；属性组内容变化后旧确认失效。
6. 发布前检查返回结构化阻塞项，覆盖核心字段、Schema 必填、关键确认、营养标签一致性、受控文件、条码/外部编码、scope 冲突、基线变化、批准依据和权限。
7. `PublishProductChangeSet` 原子发布产品版本、SKU、渠道配置、属性有效快照和素材关系；失败时有效档案保持原状；重复发布返回第一次成功结果。
8. 产品档案搜索、概览、详情、版本/SKU/渠道查询按权限过滤和字段投影，普通员工不能看到配方、成本、高敏未上市包装和无下载权限文件。
9. 存量产品 Excel 导入支持模板版本、逐行校验、重复候选、人工处理、确认导入草稿、产品总监发布基线和重复确认幂等。
10. 前端完成产品列表、产品详情、变更集工作台、发布预检、属性确认和导入工作台最小闭环。
11. 阶段3后端测试、前端测试、OpenAPI 漂移、前端 build、阶段3 E2E 和 `verify-trd.ps1` 均通过；如本地 Docker 或 Python 前置环境阻塞，必须在检查点中明确披露。

## 3. 需求映射

| 需求 | 任务 |
|---|---|
| PIM-001 | Task 3.2 |
| PIM-002 | Task 3.3 |
| PIM-003 | Task 3.4、Task 3.5 |
| PIM-004 | Task 3.4 |
| PIM-005 | Task 3.3、Task 3.5 |
| PIM-006 | Task 3.4 |
| PIM-007 | Task 3.5 |
| PIM-008 | Task 3.2、Task 3.5 |
| PIM-009 | Task 3.6、Task 3.8 |
| PIM-010 | Task 3.7 |
| PIM-011 | Task 3.7 |
| PIM-012 | Task 3.7 |
| PIM-013 | Task 3.2、Task 3.7 |
| PIM-014 | Task 3.1、Task 3.6、Task 3.8 |
| GLB-004、NFR-006 | Task 3.2、Task 3.4、Task 3.5 |
| GLB-005 | Task 3.5、Task 3.7 |
| GLB-010 | Task 3.7 |

## 4. 文件结构规划

- `backend/apps/products/models/`：将当前单文件 `models.py` 拆为 `asset.py`、`version.py`、`change_set.py`、`attribute.py`、`nutrition.py`、`material.py`、`import_batch.py`、`external_binding.py`。如果拆分导致迁移噪音过大，先保留单文件并在同一任务内完成行为，不做无关重构。
- `backend/apps/products/services/`：产品变更集创建、编辑、差异、确认、发布、导入确认和基线发布命令。
- `backend/apps/products/queries/`：产品搜索、详情、版本树、草稿差异和导入结果只读查询。
- `backend/apps/products/api/`：产品档案、变更集、确认、发布预检、导入批次 API；所有接口补齐 `extend_schema`，并同步 `backend/openapi/schema.yaml` 与前端生成类型。
- `backend/apps/products/policies/identity_provider.py`：产品负责人、项目组长、项目成员、属性确认人、产品总监和迁移审核人对象身份。
- `backend/apps/products/tasks.py`：Excel 解析、重复候选生成、查询模型刷新和定时激活；任务只传 ID，重新读取权威数据。
- `backend/tests/products/`：模型、服务、权限、API、并发、迁移和 E2E 支撑测试。
- `frontend/src/modules/products/`：产品列表、详情、变更集工作台、发布预检、属性确认、导入工作台、Pinia store 和组件测试。
- `tests/e2e/product-profile-migration.spec.ts`：阶段3浏览器端到端主路径。
- `docs/implementation/phase-3-test-matrix.md`、`docs/implementation/phase-3-checkpoint.md`：阶段3需求追踪与退出证据。

## 5. PR 拆分

| PR | 范围 | 可独立验收结果 |
|---|---|---|
| PR1 | Task 3.0-3.2 | 阶段3分支、测试矩阵、动作目录、产品主模型和兼容迁移 |
| PR2 | Task 3.3-3.5 | 属性 Schema、变更集、确认、发布预检和原子发布 |
| PR3 | Task 3.6、3.8 | 产品查询 API、产品前端档案页和变更集工作台 |
| PR4 | Task 3.7、3.9 | 存量导入、阶段3 E2E、测试矩阵和阶段退出证据 |

## 6. Task 3.0：建立阶段三分支、基线和测试矩阵

**Files:**

- Create: `docs/implementation/phase-3-test-matrix.md`
- Modify: `docs/development/01-phased-implementation-plan.md`

**Interfaces:**

- Consumes: 阶段2完成检查点、`scripts\check.cmd`、`scripts\verify-trd.ps1`
- Produces: 阶段3需求证据矩阵和执行分支

- [ ] 从阶段2完成后的最新主线创建阶段3分支。

```powershell
git switch main
git pull --ff-only origin main
git status --short
scripts\check.cmd
git switch -c codex/phase-3-product-profile-migration
```

预期：工作区干净，阶段2完整门禁退出码0，新分支基于包含 `docs/implementation/phase-2-checkpoint.md` 最新状态的主线。

- [ ] 创建 `docs/implementation/phase-3-test-matrix.md`，逐项登记 PIM-001 至 PIM-014、GLB-004、GLB-005、GLB-010、NFR-006 的证据位置，初始状态统一为 `未实现`。
- [ ] 在主计划阶段3处链接本计划和测试矩阵，不提前修改阶段状态。
- [ ] 提交。

```powershell
git add docs
git commit -m "docs: establish phase 3 execution baseline"
```

## 7. Task 3.1：产品动作目录、对象身份和阶段3权限骨架

**Files:**

- Modify: `backend/apps/authorization/actions.py`
- Create: `backend/apps/products/policies/identity_provider.py`
- Create: `backend/tests/products/test_product_actions.py`
- Create: `backend/tests/products/test_product_permissions.py`
- Modify: `backend/config/settings/base.py`

**Interfaces:**

- Consumes: `authorize(...)`、`identity_registry`、`ResourceDescriptor`
- Produces: 阶段3产品动作目录、`ProductIdentityProvider`

- [ ] 先写动作目录测试。

```python
@pytest.mark.django_db
def test_phase_3_product_actions_are_seeded() -> None:
    required = {
        "product.search",
        "product.read_basic",
        "product.read_sensitive",
        "product_version.history.read",
        "product_draft.create",
        "product_draft.edit_group",
        "product_draft.submit",
        "attribute_group.confirm",
        "attribute_group.return",
        "confirmer.reassign",
        "product.publish_new",
        "product.publish_iteration",
        "product.publish_baseline",
        "product.correct_baseline",
        "product_material.preview",
        "product_material.download_original",
        "product.export",
        "external_binding.manage",
        "migration.upload",
        "migration.review",
        "migration.confirm",
    }
    assert required <= set(PermissionAction.objects.values_list("action_code", flat=True))
```

- [ ] 运行测试并确认失败。

```powershell
Set-Location backend
uv run pytest tests/products/test_product_actions.py -q
```

- [ ] 在 `backend/apps/authorization/actions.py` 增加 `PRODUCT_ACTIONS`，并创建 seed migration；动作类别使用 READ、WRITE、DECIDE、EXPORT、ADMIN，不新增动态权限表达式。
- [ ] 实现 `ProductIdentityProvider`：产品负责人、来源项目组长、项目成员、属性确认人、产品总监和迁移审核人按对象身份授予最小动作。
- [ ] 注册产品身份提供器；无注册动作时仍默认拒绝。
- [ ] 写权限矩阵测试，覆盖普通员工 basic read、无范围用户拒绝、平台管理员读取高敏字段拒绝、产品总监发布基线允许、系统管理员只配置 Schema 但不能读敏感值。
- [ ] 验证并提交。

```powershell
uv run pytest tests/products/test_product_actions.py tests/products/test_product_permissions.py -q
uv run python manage.py makemigrations --check --dry-run --settings=config.settings.test
git add backend
git commit -m "feat: add phase 3 product authorization actions"
```

## 8. Task 3.2：产品主模型和阶段2草稿兼容迁移

**Files:**

- Modify: `backend/apps/products/models.py`
- Modify: `backend/apps/products/services/create_draft_from_candidate.py`
- Modify: `backend/apps/projects/models.py`
- Create: `backend/apps/products/migrations/0003_product_profile_core.py`
- Create: `backend/tests/products/test_product_core_models.py`
- Modify: `backend/tests/products/test_product_draft_shell.py`
- Modify: `backend/tests/projects/test_project_shell.py`

**Interfaces:**

- Consumes: `ProductAsset`、阶段2 `ProductDraft`、`Project.product_draft`
- Produces: `ProductVersion`、`ProductVersionScope`、`SKU`、`ChannelConfiguration`、`ProductChangeSet`

- [ ] 先写产品主模型关系测试。

```python
@pytest.mark.django_db
def test_product_version_sku_and_channel_configuration_are_linked(product_asset, channel_dict) -> None:
    version = ProductVersion.objects.create(
        organization=product_asset.organization,
        product=product_asset,
        version_code="V1",
        version_name="Initial version",
        status=ProductVersionStatus.DRAFT,
        definition_summary="Initial definition",
    )
    sku = SKU.objects.create(
        organization=product_asset.organization,
        product_version=version,
        sku_code="SKU-001",
        name="Single cup",
        specification="120g cup",
        net_content_value=Decimal("120.0000"),
        net_content_unit="g",
        sales_unit="cup",
    )
    channel = ChannelConfiguration.objects.create(
        organization=product_asset.organization,
        sku=sku,
        channel_code="KA",
        configuration_version=1,
        suggested_retail_price=Decimal("9.90"),
        channel_status=ChannelStatus.PLANNED,
    )
    assert channel.sku.product_version.product_id == product_asset.id
```

- [ ] 先写阶段2兼容测试，证明立项后返回的是 `ProductChangeSet(NEW_PRODUCT)` 且项目仍可查到产品草稿详情。

```python
@pytest.mark.django_db
def test_project_creation_creates_new_product_change_set(approved_candidate, boss) -> None:
    result = ApproveAndCreateProject(
        context=CommandContext.for_actor(boss),
        candidate_public_id=approved_candidate.public_id,
        idempotency_key="phase3-change-set",
    ).execute()
    change_set = ProductChangeSet.objects.get(public_id=result.product_draft.public_id)
    assert change_set.change_type == ChangeSetType.NEW_PRODUCT
    assert change_set.status == ChangeSetStatus.DRAFT
    assert change_set.product.lifecycle_status == ProductLifecycleStatus.DEVELOPING
```

- [ ] 运行测试并确认失败。

```powershell
uv run pytest tests/products/test_product_core_models.py tests/products/test_product_draft_shell.py tests/projects/test_project_shell.py -q
```

- [ ] 扩展 `ProductAsset` 固定字段：`brand_code`、`category_code`、`primary_version`、`retired_at`、`source_type`、`source_project`、必要索引；暂用字符串字典码，不提前建设完整字典服务。
- [ ] 新增 `ProductVersion`、`ProductVersionScope`、`SKU`、`ChannelConfiguration`，使用 varchar 状态码、DECIMAL 金额/计量值、组织范围、业务唯一约束和查询索引。
- [ ] 引入 `ProductChangeSet`，将阶段2 `ProductDraft` 语义迁移为变更集；保留 `/api/v1/product-drafts/{id}` 作为只读兼容端点，但内部读取 `ProductChangeSet`。
- [ ] 修改 `create_product_draft(...)` 的返回对象兼容名，保持 `ApproveAndCreateProjectResult.product_draft` 暂不破坏阶段2调用方；计划内后续任务逐步迁移前端命名。
- [ ] 验证迁移从空库可执行，且阶段2项目创建测试仍通过。

```powershell
uv run python manage.py makemigrations products projects --settings=config.settings.test
uv run python manage.py migrate --settings=config.settings.test
uv run pytest tests/products tests/projects tests/opportunities/test_project_creation.py -q
```

- [ ] 提交。

```powershell
git add backend
git commit -m "feat: add product profile core model"
```

## 9. Task 3.3：属性 Schema、属性组值和草稿差异

**Files:**

- Modify: `backend/apps/products/models.py`
- Create: `backend/apps/products/services/attribute_schema.py`
- Create: `backend/apps/products/services/edit_change_set.py`
- Create: `backend/apps/products/services/diff_change_set.py`
- Create: `backend/tests/products/test_attribute_schema.py`
- Create: `backend/tests/products/test_change_set_diff.py`

**Interfaces:**

- Consumes: `ConfigurationVersion(PUBLISHED)`、`ProductChangeSet`
- Produces: `AttributeGroupDefinition`、`AttributeDefinition`、`AttributeGroupValue`、`EditProductChangeSet`、`BuildProductChangeSetDiff`

- [ ] 先写属性 Schema 校验测试。

```python
@pytest.mark.django_db
def test_unknown_attribute_code_is_rejected(change_set, published_product_schema) -> None:
    service = EditProductChangeSet(
        context=CommandContext.for_actor(change_set.created_by),
        change_set_public_id=change_set.public_id,
        version_no=change_set.version_no,
        group_code="PRODUCT_DEFINITION",
        values={"unexpected_field": "value"},
    )
    with pytest.raises(AttributeValueInvalid) as exc:
        service.execute()
    assert exc.value.code == "ATTRIBUTE_VALUE_INVALID"
```

- [ ] 先写差异测试，稳定字段代码而非显示名参与比较。

```python
@pytest.mark.django_db
def test_change_set_diff_compares_by_stable_field_code(iteration_change_set) -> None:
    EditProductChangeSet(
        context=CommandContext.for_actor(iteration_change_set.created_by),
        change_set_public_id=iteration_change_set.public_id,
        version_no=iteration_change_set.version_no,
        group_code="QUALITY_COMPLIANCE",
        values={"storage_condition": "Keep refrigerated"},
    ).execute()
    diff = BuildProductChangeSetDiff(
        actor=iteration_change_set.created_by,
        change_set_public_id=iteration_change_set.public_id,
    ).execute()
    assert diff.changed_fields[0].field_code == "storage_condition"
    assert diff.changed_fields[0].new_value == "Keep refrigerated"
```

- [ ] 运行测试并确认失败。

```powershell
uv run pytest tests/products/test_attribute_schema.py tests/products/test_change_set_diff.py -q
```

- [ ] 实现属性组定义和字段定义模型，字段类型覆盖文本、数值、金额、日期、单选、多选、布尔、人员、部门、对象引用、图片/文件引用和结构化明细表。
- [ ] 实现 `resolve_product_attribute_schema(organization, category_code, as_of)`，只返回已发布 Schema；缺失时抛 `ATTRIBUTE_SCHEMA_NOT_PUBLISHED`。
- [ ] 实现 `EditProductChangeSet`：事务内锁定变更集、校验 `version_no`、按 Schema 校验 `values_json`、计算规范化 `content_hash`、写审计和 outbox。
- [ ] 实现 `BuildProductChangeSetDiff`：输出固定字段、属性字段、文件版本、编辑人、更新时间、确认状态和关联依据；敏感字段旧值/新值按权限投影。
- [ ] 验证并提交。

```powershell
uv run pytest tests/products/test_attribute_schema.py tests/products/test_change_set_diff.py -q
uv run mypy config apps
git add backend
git commit -m "feat: add product attribute schema and diff"
```

## 10. Task 3.4：营养、素材和属性组专业确认

**Files:**

- Modify: `backend/apps/products/models.py`
- Create: `backend/apps/products/services/materials.py`
- Create: `backend/apps/products/services/confirm_attribute_group.py`
- Create: `backend/tests/products/test_nutrition_materials.py`
- Create: `backend/tests/products/test_attribute_confirmation.py`

**Interfaces:**

- Consumes: `DocumentVersion`、`VersionStatus.CONTROLLED`、`AttributeGroupValue.content_hash`
- Produces: `NutritionTable`、`NutritionItem`、`ProductMaterial`、`AttributeConfirmation`

- [ ] 先写营养标签一致性测试。

```python
@pytest.mark.django_db
def test_nutrition_label_mismatch_blocks_publication(change_set, controlled_label_file) -> None:
    NutritionTable.objects.create(
        organization=change_set.organization,
        change_set=change_set,
        basis="PER_100G",
        label_document_version=controlled_label_file,
        structured_summary_hash="structured-a",
        label_summary_hash="label-b",
    )
    result = ValidateProductPublication(
        actor=change_set.created_by,
        change_set_public_id=change_set.public_id,
    ).execute()
    assert "NUTRITION_LABEL_MISMATCH" in {block.code for block in result.blocks}
```

- [ ] 先写确认失效测试。

```python
@pytest.mark.django_db
def test_editing_confirmed_attribute_group_supersedes_old_confirmation(change_set, confirmer) -> None:
    group_value = confirmed_group_value(change_set, confirmer)
    EditProductChangeSet(
        context=CommandContext.for_actor(change_set.created_by),
        change_set_public_id=change_set.public_id,
        version_no=change_set.version_no,
        group_code=group_value.group_definition.group_code,
        values={"core_selling_points": "Updated value"},
    ).execute()
    group_value.confirmations.get(decision=ConfirmationDecision.APPROVED).refresh_from_db()
    assert group_value.confirmations.get(decision=ConfirmationDecision.APPROVED).superseded_at is not None
```

- [ ] 运行测试并确认失败。

```powershell
uv run pytest tests/products/test_nutrition_materials.py tests/products/test_attribute_confirmation.py -q
```

- [ ] 实现营养表和营养明细模型；结构化值和标签文件摘要不一致时生成发布阻塞项。
- [ ] 实现产品素材模型，素材引用 `DocumentVersion` 且只允许 ACTIVE/LOCKED/CONTROLLED 的受控版本进入发布。
- [ ] 实现 `ApproveAttributeGroup`、`ReturnAttributeGroup`、`ReassignAttributeConfirmer`；确认绑定 `group_value_id + content_hash`，退回记录原因并使变更集回到可编辑状态。
- [ ] 属性组内容变化时通过同一服务使旧确认 `superseded_at` 生效，不删除历史确认。
- [ ] 验证并提交。

```powershell
uv run pytest tests/products/test_nutrition_materials.py tests/products/test_attribute_confirmation.py -q
git add backend
git commit -m "feat: add product materials and attribute confirmations"
```

## 11. Task 3.5：发布预检和产品变更集原子发布

**Files:**

- Create: `backend/apps/products/services/validate_publication.py`
- Create: `backend/apps/products/services/publish_change_set.py`
- Create: `backend/apps/products/services/create_change_set.py`
- Create: `backend/tests/products/test_publication_validation.py`
- Create: `backend/tests/products/test_publish_change_set.py`
- Create: `backend/tests/products/test_product_concurrency.py`

**Interfaces:**

- Consumes: `ProductChangeSet`、`AttributeConfirmation`、`ProductVersionScope`、`append_event`、`register_outbox_event`
- Produces: `ValidateProductPublication.execute() -> PublicationValidationResult`、`PublishProductChangeSet.execute() -> ProductPublicationResult`

- [ ] 先写发布回滚和幂等测试。

```python
@pytest.mark.django_db(transaction=True)
def test_publish_failure_keeps_effective_dossier_unchanged(ready_change_set, monkeypatch) -> None:
    before_primary_version = ready_change_set.product.primary_version_id
    monkeypatch.setattr(
        "apps.products.services.publish_change_set.create_channel_configurations",
        raise_database_error,
    )
    with pytest.raises(ProductPublicationFailed):
        PublishProductChangeSet(
            context=CommandContext.for_actor(ready_change_set.approved_by),
            change_set_public_id=ready_change_set.public_id,
            idempotency_key="publish-fails",
        ).execute()
    ready_change_set.product.refresh_from_db()
    assert ready_change_set.product.primary_version_id == before_primary_version
```

```python
@pytest.mark.django_db(transaction=True)
def test_repeated_publish_returns_first_result(ready_change_set) -> None:
    first = PublishProductChangeSet(
        context=CommandContext.for_actor(ready_change_set.approved_by),
        change_set_public_id=ready_change_set.public_id,
        idempotency_key="publish-1",
    ).execute()
    second = PublishProductChangeSet(
        context=CommandContext.for_actor(ready_change_set.approved_by),
        change_set_public_id=ready_change_set.public_id,
        idempotency_key="publish-1",
    ).execute()
    assert first.product_version.public_id == second.product_version.public_id
    assert ProductVersion.objects.filter(change_set=ready_change_set).count() == 1
```

- [ ] 运行测试并确认失败。

```powershell
uv run pytest tests/products/test_publication_validation.py tests/products/test_publish_change_set.py tests/products/test_product_concurrency.py -q
```

- [ ] 实现 `CreateProductChangeSet`，老品迭代保存当前有效版本、适用范围和 `base_fingerprint`，只克隆实际编辑对象。
- [ ] 实现 `ValidateProductPublication`，返回结构化阻塞项，不抛第一个错误后停止。
- [ ] 实现 `PublishProductChangeSet`：锁定产品、变更集、受影响版本和渠道范围；重新跑发布预检；创建或激活产品版本、SKU、渠道配置、属性快照和素材关系；更新 `primary_version` 与生命周期；写审计和 `product_version.published` outbox。
- [ ] 实现 scope 冲突检查：同一产品、同一 GLOBAL/CHANNEL 范围、同一有效时间不得重叠；CHANNEL 覆盖 GLOBAL 时必须显式展示。
- [ ] 实现基线变化阻断：旧 `base_fingerprint` 与当前有效档案不同则返回 `PRODUCT_BASELINE_CHANGED`。
- [ ] 实现并发测试，使用数据库唯一约束和事务锁证明两个并发发布只有一个成功或一个幂等返回。
- [ ] 验证并提交。

```powershell
uv run pytest tests/products/test_publication_validation.py tests/products/test_publish_change_set.py tests/products/test_product_concurrency.py -q
uv run python manage.py makemigrations --check --dry-run --settings=config.settings.test
git add backend
git commit -m "feat: publish product change sets atomically"
```

## 12. Task 3.6：产品档案查询、API 和 OpenAPI 契约

**Files:**

- Create: `backend/apps/products/queries/products.py`
- Create: `backend/apps/products/queries/change_sets.py`
- Create: `backend/apps/products/api/products.py`
- Create: `backend/apps/products/api/change_sets.py`
- Create: `backend/apps/products/api/imports.py`
- Modify: `backend/apps/products/api/urls.py`
- Modify: `backend/config/urls.py`
- Create: `backend/tests/products/test_product_api.py`
- Create: `backend/tests/products/test_product_query_permissions.py`
- Modify: `backend/openapi/schema.yaml`
- Modify: `frontend/src/api/generated/schema.d.ts`

**Interfaces:**

- Consumes: `ProductAsset`、`ProductVersion`、`SKU`、`ChannelConfiguration`、`ProductChangeSet`
- Produces: 阶段3 REST API 和 OpenAPI 契约

- [ ] 先写搜索权限测试。

```python
@pytest.mark.django_db
def test_basic_search_hides_sensitive_fields(api_client, ordinary_employee, active_product) -> None:
    api_client.force_login(ordinary_employee)
    response = api_client.get("/api/v1/products?search=yogurt")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert "formula_summary" not in item
    assert item["public_id"] == str(active_product.public_id)
```

- [ ] 先写 API 契约测试，详情返回产品、有效版本、SKU、渠道和历史来源但不返回数据库主键。

```python
@pytest.mark.django_db
def test_product_detail_returns_public_identifiers(api_client, product_manager, active_product) -> None:
    api_client.force_login(product_manager)
    response = api_client.get(f"/api/v1/products/{active_product.public_id}")
    assert response.status_code == 200
    body = response.json()
    assert "id" not in body
    assert body["public_id"] == str(active_product.public_id)
    assert body["versions"][0]["skus"][0]["public_id"]
```

- [ ] 运行测试并确认失败。

```powershell
uv run pytest tests/products/test_product_api.py tests/products/test_product_query_permissions.py -q
```

- [ ] 实现产品搜索、详情、版本、SKU、渠道、变更集详情、差异、提交确认、确认/退回、发布预检、发布 API。
- [ ] 所有列表分页并按稳定字段排序；查询服务先应用对象范围权限，再做字段投影。
- [ ] 为所有 API 添加 `extend_schema`，避免阶段3新增接口出现 `No response body`。
- [ ] 生成 OpenAPI 和前端类型。

```powershell
uv run pytest tests/products/test_product_api.py tests/products/test_product_query_permissions.py -q
uv run python manage.py spectacular --file openapi/schema.yaml --validate --settings=config.settings.test
Set-Location ..\frontend
npm.cmd run api:generate
Set-Location ..\backend
```

- [ ] 提交。

```powershell
git add backend frontend/src/api/generated/schema.d.ts
git commit -m "feat: add product dossier APIs"
```

## 13. Task 3.7：存量产品导入、重复识别和基线发布

**Files:**

- Modify: `backend/apps/products/models.py`
- Create: `backend/apps/products/services/import_template.py`
- Create: `backend/apps/products/services/import_batch.py`
- Create: `backend/apps/products/services/duplicate_detection.py`
- Create: `backend/apps/products/services/publish_legacy_baseline.py`
- Create: `backend/apps/products/tasks.py`
- Create: `backend/tests/products/test_legacy_import.py`
- Create: `backend/tests/products/test_import_duplicates.py`
- Create: `backend/tests/products/test_legacy_baseline_publish.py`

**Interfaces:**

- Consumes: `DocumentVersion`、`ProductChangeSet(LEGACY_BASELINE)`、`PublishProductChangeSet`
- Produces: `ImportBatch`、`ImportItem`、`ConfirmProductImportBatch`、`PublishLegacyBaseline`

- [ ] 先写逐行导入幂等测试。

```python
@pytest.mark.django_db(transaction=True)
def test_confirming_import_batch_twice_does_not_duplicate_products(parsed_import_batch, product_director) -> None:
    first = ConfirmProductImportBatch(
        context=CommandContext.for_actor(product_director),
        batch_public_id=parsed_import_batch.public_id,
        idempotency_key="confirm-import-1",
    ).execute()
    second = ConfirmProductImportBatch(
        context=CommandContext.for_actor(product_director),
        batch_public_id=parsed_import_batch.public_id,
        idempotency_key="confirm-import-1",
    ).execute()
    assert first.created_count == second.created_count
    assert ProductAsset.objects.filter(source_type=ProductSourceType.LEGACY_IMPORT).count() == first.created_count
```

- [ ] 先写重复候选测试。

```python
@pytest.mark.django_db
def test_exact_barcode_duplicate_requires_manual_review(import_item, existing_sku) -> None:
    import_item.normalized_payload = {"barcode": existing_sku.barcode, "name": "Similar product"}
    candidates = DetectProductImportDuplicates(item=import_item).execute()
    assert candidates[0].match_type == "BARCODE_EXACT"
    assert candidates[0].blocking is True
```

- [ ] 运行测试并确认失败。

```powershell
uv run pytest tests/products/test_legacy_import.py tests/products/test_import_duplicates.py tests/products/test_legacy_baseline_publish.py -q
```

- [ ] 实现导入模板版本和解析器；首期支持 CSV 或 Excel 中当前依赖已支持的格式，不新增重型解析依赖；如必须新增依赖，单独提交并更新锁文件。
- [ ] 实现 `ImportBatch` 和 `ImportItem`，保存行号、原始摘要、校验结果、重复候选、人工决策、目标对象和错误码。
- [ ] 实现重复识别顺序：外部编码、条码、标准化名称规格、品牌品类净含量；只有外部 ID 或条码精确冲突阻止自动新建。
- [ ] 实现 `ConfirmProductImportBatch`，按 `batch_id + row_number` 幂等创建或关联 `ProductChangeSet(LEGACY_BASELINE)`，单行失败不阻止其他有效行进入预览。
- [ ] 实现 `PublishLegacyBaseline`，产品总监一次确认后发布为 `ACTIVE`，不创建虚假项目或阶段门；发布后事实变化必须走迭代变更集。
- [ ] 注册导入 API：`POST /api/v1/product-import-batches`、`GET /api/v1/product-import-batches/{id}`、`POST /api/v1/product-import-batches/{id}/confirm`、`POST /api/v1/legacy-baselines/{id}/publish`。
- [ ] 验证并提交。

```powershell
uv run pytest tests/products/test_legacy_import.py tests/products/test_import_duplicates.py tests/products/test_legacy_baseline_publish.py -q
uv run python manage.py spectacular --file openapi/schema.yaml --validate --settings=config.settings.test
git add backend
git commit -m "feat: add legacy product baseline import"
```

## 14. Task 3.8：阶段3前端产品档案和导入工作台

**Files:**

- Create: `frontend/src/modules/products/store.ts`
- Create: `frontend/src/modules/products/ProductListView.vue`
- Create: `frontend/src/modules/products/ProductDetailView.vue`
- Create: `frontend/src/modules/products/ProductChangeSetView.vue`
- Create: `frontend/src/modules/products/ProductPublicationPanel.vue`
- Create: `frontend/src/modules/products/ProductImportPage.vue`
- Create: `frontend/src/modules/products/ProductListView.spec.ts`
- Create: `frontend/src/modules/products/ProductChangeSetView.spec.ts`
- Create: `frontend/src/modules/products/ProductImportPage.spec.ts`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/app/App.vue`

**Interfaces:**

- Consumes: OpenAPI generated types、`apiFetch<T>()`
- Produces: 产品档案前端最小闭环

- [ ] 先写前端搜索和敏感字段展示测试。

```typescript
it('renders product search results without sensitive formula fields', async () => {
  const wrapper = mount(ProductListView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  expect(wrapper.text()).toContain('High protein yogurt')
  expect(wrapper.text()).not.toContain('formula')
})
```

- [ ] 先写发布预检阻塞项测试。

```typescript
it('shows publication blockers before publish button can be used', async () => {
  const wrapper = mount(ProductPublicationPanel, {
    props: { changeSetPublicId: 'change-set-1' },
    global: { plugins: [pinia] },
  })
  await flushPromises()
  expect(wrapper.text()).toContain('PRODUCT_REQUIRED_FIELD_MISSING')
  expect(wrapper.get('[data-test="publish-change-set"]').attributes('disabled')).toBeDefined()
})
```

- [ ] 运行测试并确认失败。

```powershell
Set-Location frontend
npm.cmd run test:unit -- --run ProductListView.spec.ts ProductChangeSetView.spec.ts ProductImportPage.spec.ts
```

- [ ] 实现产品列表、产品详情、版本/SKU/渠道树、历史版本、来源项目、文件素材和字段权限投影展示。
- [ ] 实现变更集工作台：属性组编辑、差异查看、确认状态、发布预检、发布按钮幂等和 409 基线冲突提示。
- [ ] 实现导入工作台：模板下载入口、上传、解析进度、错误行、重复候选处理、确认导入和基线发布结果。
- [ ] 前端不保存敏感字段到 localStorage、URL 查询参数或日志；权限隐藏只做体验，后端仍为最终判权。
- [ ] 验证前端门禁并提交。

```powershell
npm.cmd run api:generate
npm.cmd run lint
npm.cmd run format:check
npm.cmd run typecheck
npm.cmd run test:unit -- --run
npm.cmd run build
git add frontend backend/openapi/schema.yaml
git commit -m "feat: add product dossier UI"
```

## 15. Task 3.9：阶段3 E2E、测试矩阵和退出证据

**Files:**

- Create: `backend/tests/acceptance/test_product_profile_migration.py`
- Create: `tests/e2e/product-profile-migration.spec.ts`
- Modify: `scripts/check.ps1`
- Modify: `docs/implementation/phase-3-test-matrix.md`
- Create: `docs/implementation/phase-3-checkpoint.md`
- Modify: `docs/development/01-phased-implementation-plan.md`
- Modify: `README.md`

**Interfaces:**

- Consumes: 阶段3 API、前端产品模块、开发登录、测试配置
- Produces: 阶段3退出证据

- [ ] 先写后端验收测试：新品产品草稿编辑、确认、发布后变为有效产品档案。

```python
@pytest.mark.django_db(transaction=True)
def test_new_product_change_set_can_publish_effective_dossier(api_client, phase3_ready_project, product_director) -> None:
    api_client.force_login(product_director)
    change_set_id = str(phase3_ready_project.product_change_set.public_id)
    validate_response = api_client.post(f"/api/v1/product-change-sets/{change_set_id}/validate-publication")
    assert validate_response.status_code == 200
    assert validate_response.json()["can_publish"] is True
    publish_response = api_client.post(
        f"/api/v1/product-change-sets/{change_set_id}/publish",
        data={"idempotency_key": "publish-e2e"},
        content_type="application/json",
    )
    assert publish_response.status_code == 200
    assert publish_response.json()["product_lifecycle_status"] == "ACTIVE"
```

- [ ] 先写后端验收测试：存量导入部分完整老品，产品总监发布基线后可搜索。

```python
@pytest.mark.django_db(transaction=True)
def test_legacy_import_baseline_is_searchable_after_director_publish(api_client, product_director, parsed_legacy_batch) -> None:
    api_client.force_login(product_director)
    confirm = api_client.post(f"/api/v1/product-import-batches/{parsed_legacy_batch.public_id}/confirm")
    assert confirm.status_code == 200
    baseline_id = confirm.json()["items"][0]["baseline_public_id"]
    publish = api_client.post(f"/api/v1/legacy-baselines/{baseline_id}/publish")
    assert publish.status_code == 200
    search = api_client.get("/api/v1/products?search=legacy")
    assert search.status_code == 200
    assert search.json()["items"]
```

- [ ] 写 Playwright E2E：开发登录、打开产品列表、进入产品详情、查看版本/SKU/渠道、进入导入工作台、上传样例文件、处理重复候选、确认基线、看到产品可搜索。
- [ ] 运行测试并确认失败。

```powershell
Set-Location backend
uv run pytest tests/acceptance/test_product_profile_migration.py -q
Set-Location ..\tests\e2e
npx.cmd playwright test product-profile-migration.spec.ts
```

- [ ] 实现缺失的 fixture、测试种子和 E2E 辅助 API；只在 `ENABLE_TEST_API=True` 下暴露确定性种子接口。
- [ ] 将阶段3 E2E 加入 `scripts/check.ps1` 的相关阶段门禁，保持失败可见。
- [ ] 执行最终门禁。

```powershell
Set-Location D:\Projects\Meridian
scripts\preflight.cmd
scripts\check.cmd
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-trd.ps1
git status --short
```

- [ ] 更新测试矩阵，PIM-001 至 PIM-014、GLB-004、GLB-005、GLB-010、NFR-006 均关联实际测试、E2E 或明确配置证据。
- [ ] 创建 `docs/implementation/phase-3-checkpoint.md`，记录提交哈希、迁移、测试数量、E2E结果、OpenAPI漂移、已知限制和阶段4边界。
- [ ] 将主计划阶段3标记完成，README 当前状态更新为“阶段3已完成，阶段4尚未开始”。
- [ ] 提交。

```powershell
git add docs README.md backend frontend tests scripts
git diff --cached --check
git commit -m "docs: record phase 3 completion evidence"
```

## 16. 阶段3明确不实现

- D1-L3 项目执行模板、任务依赖、逾期、计划调整和完整交付物工作台；
- 阶段4的交付物版本提交、专业确认工作台和 `FIRST_LAUNCH` 重大阶段门；
- 经营事实、指标汇总、风险信号、经营议题、产品迭代触发和产品退市；
- ERP、MES、WMS 主数据替代维护；
- 产品自动合并、复杂相似度搜索引擎和全文检索集群；
- 真实钉钉企业登录、组织同步和真实消息投递验收；
- 外部系统正式同步接口、容量压测、备份恢复演练和离线发布包。

## 17. 执行风险与停线条件

| 风险 | 处理 |
|---|---|
| `ProductDraft` 和 `ProductChangeSet` 同时承载权威草稿事实 | 停止开发，只保留 `ProductChangeSet` 为权威模型，`ProductDraft` 仅作为兼容路由或迁移别名 |
| 属性 Schema 被实现成完全自由 JSON | 停止并补固定核心字段和发布 Schema 校验；搜索/统计字段不得藏在任意 JSON |
| 产品版本发布绕过应用服务 | 停止合并，所有发布必须经 `PublishProductChangeSet` 事务 |
| 系统管理员可读取高敏产品属性 | 最低 P1，补字段级权限测试和查询投影 |
| 发布失败导致部分版本、SKU 或渠道生效 | 最低 P1，补事务回滚和幂等测试 |
| 存量导入自动合并重复产品 | 停止并改为人工处理候选；精确冲突只阻止自动新建 |
| 阶段3误实现阶段4项目执行 | 拆回阶段4计划；阶段3仅保存产品草稿和发布接口 |
| OpenAPI 新增接口仍出现空响应体 | 补 `extend_schema` 和前端类型生成，未修复不得进入阶段退出 |
| E2E 依赖真实外部系统或真实业务数据 | 改用测试种子和假适配器；真实集成留阶段6 |

## 18. 自检结果

- 需求覆盖：PIM-001 至 PIM-014 均映射到任务；GLB-004、GLB-005、GLB-010、NFR-006 已纳入阶段3证据范围。
- 模块边界：产品写模型集中在 `products`，配置、文件、权限、审计和 outbox 通过既有 Interface 协作。
- 范围控制：阶段4项目执行、阶段5运营和阶段6集成均列入明确不实现。
- 类型一致性：计划内统一使用 `ProductChangeSet` 表达草稿/迭代/导入基线；阶段2 `ProductDraft` 只作为兼容迁移入口。
