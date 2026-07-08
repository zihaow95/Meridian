# Project Meridian 阶段2提案到项目纵向切片实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可供业务试用的提案、立案、立项闭环，使产品机会资产可以经过两个重大阶段门后原子创建项目实例和产品草稿，并满足 OPP-001 至 OPP-015、GLB-001 至 GLB-003 的阶段验收。

**Architecture:** 保持 Django 模块化单体和 Vue 3 前端；`opportunities` 拥有机会、提案版本、成员、额度、拟立项方案、暂缓与复议模型，`stage_gates` 拥有两个重大阶段门的通用决策骨架，`projects` 与 `products` 在本阶段只提供立项创建所需的最小正式对象。所有关键写命令通过应用服务在 MySQL 事务内完成权限复核、状态迁移、审计和 outbox 登记；通知失败不得回滚已提交的业务事实。

**Tech Stack:** Python 3.13、Django 5.2、Django REST Framework、MySQL 8.0、Redis、Celery 5.6、Vue 3、TypeScript、Pinia、Element Plus、Vitest、Playwright、Docker Compose、GitHub Actions。

**Status:** 待执行

**Date:** 2026-07-08

## Global Constraints

- 正式工程根目录固定为 `D:\Projects\Meridian`。
- 阶段2必须从已合入阶段1 remediation 的最新 `main` 创建 `codex/phase-2-opportunity-to-project` 分支；当前 `codex/phase-1-batch2-minimal-apis` 不得被阶段2绕过。
- 不复制、引用或兼容 `npd-lcm-mvp/`、Node.js/SQLite/localStorage 旧原型。
- 阶段2不实现完整产品档案、存量产品导入、开发上市任务执行、经营运营、正式钉钉企业验收和生产化发布。
- 产品机会资产、项目实例和产品资产保持独立；不得用单表状态字段模拟三类对象。
- 四个重大阶段门代码固定；阶段2只实现 `PROPOSAL_TO_CASE` 和 `CASE_TO_PROJECT`。
- 产品经理和部门负责人可提交真实提案；普通员工只能作为联合成员参与。
- 提案版本、评审材料、阶段门决策、文件版本和审计记录不可覆盖。
- 权限采用 RBAC + ABAC + 审计，默认拒绝；前端按钮隐藏不能替代后端判权。
- 关键命令必须使用 MySQL 事务、行锁或唯一约束保证幂等；不得用 Redis/Celery 保存唯一业务事实。
- 所有新增 API 使用 `/api/v1`、UUID `public_id`、统一错误结构和 OpenAPI 生成类型。
- 测试必须使用 MySQL；不得以 SQLite 替代并发、唯一约束或事务行为。

---

## 1. 基线决策与边界

- 阶段0已完成，证据见 `docs/implementation/phase-0-checkpoint.md`。
- 阶段1已通过 remediation Batch 1-3 重新验收，证据见 `docs/implementation/phase-1-checkpoint.md` 和 `docs/implementation/phase-1-test-matrix.md`。
- 阶段2依赖阶段1提供的 `CommandContext`、默认拒绝权限、动作目录、审计、outbox、配置版本、受控文件、待办和前端 API 客户端。
- TRD 01 中提到立案评估任务和立项后项目模板初始化。为避免提前建设阶段4，本计划只实现阶段2必需的轻量评估项、受控文件引用、项目壳层和产品草稿壳层；完整 `work_items`、D1-L3 阶段模板、任务依赖、交付物专业确认和项目执行工作台留到阶段4。
- 产品档案的完整产品-版本-SKU-渠道模型留到阶段3。本阶段的 `products` 只建立可被后续阶段扩展的 `ProductAsset`、`ProductDraft` 和最小来源关系，不发布有效产品档案。
- 真实钉钉企业登录与通知投递验收仍按阶段6补齐；阶段2继续使用阶段1开发登录和假网关完成确定性验收。

## 2. 完成定义

1. 有资格产品经理或配置的部门负责人可以创建、编辑、提交提案；普通员工不能独立提交。
2. 联合成员邀请、接受、协作可追溯，成员上限和有效用户校验生效。
3. 四项核心内容、公开摘要、额度归属和版本号校验阻止不合格提交。
4. 同一机会重复提交或并发提交只产生一次有效额度账。
5. 提案评审生成 `PROPOSAL_TO_CASE` 重大阶段门，决策引用锁定版本。
6. 经管会整体结论和老板最终决策可同时记录；流程状态以老板最终决策为准，并展示差异。
7. 提案通过后可以创建拟立项方案，任命立案负责人和副组长。
8. 立案评估八类核心类别可录入，提交立项评审前校验完整性和受控文件引用。
9. `CASE_TO_PROJECT` 决策通过后，项目、产品草稿、来源关系、审计和 outbox 在同一事务中完成。
10. 暂缓、季度回看、Pass、复议、合并、拆分均保留不可变历史。
11. 机会列表、详情、文件、导出和通知摘要均按权限过滤；拒绝结果不泄露对象存在性。
12. 前端完成提案入口、我的提案、机会工作台、重大阶段门评审页、候选机会池和生命周期看板首版。
13. MySQL 集成测试、并发测试、前端单元测试、OpenAPI 漂移检查、Playwright 阶段2 E2E 和 `scripts\check.cmd` 全部通过。

## 3. 需求映射

| 需求 | 任务 |
|---|---|
| OPP-001、OPP-003、OPP-004、OPP-005、OPP-015 | Task 2.1-2.3 |
| OPP-002 | Task 2.2-2.3、Task 2.8 |
| OPP-006 | Task 2.4 |
| OPP-007、OPP-008、OPP-009 | Task 2.5 |
| OPP-010 | Task 2.7 |
| OPP-011、OPP-012 | Task 2.6 |
| OPP-013、OPP-014 | Task 2.6-2.7 |
| GLB-001 | Task 2.8-2.9 |
| GLB-002、GLB-003 | Task 2.7 |

## 4. 文件结构规划

- `backend/apps/opportunities/`：机会、提案版本、成员、额度、拟立项方案、评估、暂缓、复议、合并拆分和查询 API。
- `backend/apps/stage_gates/`：重大阶段门实例、不可变提交版本、经管会结论、老板最终决策和统一结果映射。
- `backend/apps/projects/`：阶段2最小项目实例、项目成员和机会来源关系；不展开阶段4任务执行。
- `backend/apps/products/`：阶段2最小产品资产、产品草稿和项目来源关系；不实现完整产品档案发布。
- `backend/tests/opportunities/`：领域、应用服务、权限、API、并发和阶段2验收测试。
- `backend/tests/stage_gates/`：重大阶段门决策和幂等测试。
- `backend/tests/projects/`、`backend/tests/products/`：原子创建项目和产品草稿所需测试。
- `frontend/src/modules/opportunities/`：提案入口、机会列表、工作台、候选池和状态管理。
- `frontend/src/modules/stage-gates/`：重大阶段门评审页面和决策结果展示。
- `tests/e2e/opportunity-to-project.spec.ts`：阶段2浏览器端到端闭环。
- `docs/implementation/phase-2-test-matrix.md`、`docs/implementation/phase-2-checkpoint.md`：阶段追踪与退出证据。

## 5. Task 2.0：建立阶段分支和测试矩阵

**Files:**

- Create: `docs/implementation/phase-2-test-matrix.md`
- Modify: `docs/development/01-phased-implementation-plan.md`

**Interfaces:**

- Consumes: 阶段1完成证据、当前 `scripts\check.cmd`、`scripts\verify-trd.ps1`
- Produces: 阶段2需求证据矩阵和执行分支

- [ ] 从阶段1 remediation 合入后的最新主线创建阶段分支。

```powershell
git switch main
git pull --ff-only origin main
git status --short
scripts\check.cmd
git switch -c codex/phase-2-opportunity-to-project
```

预期：工作区干净，阶段1完整门禁退出码0，新分支基于包含 `docs/implementation/phase-1-checkpoint.md` 最新状态的 `main`。

- [ ] 创建 `docs/implementation/phase-2-test-matrix.md`，逐项登记 OPP-001 至 OPP-015、GLB-001 至 GLB-003 的证据位置，初始状态统一为 `未实现`。
- [ ] 在主计划阶段2处链接本计划和测试矩阵，不提前修改阶段状态。
- [ ] 提交。

```powershell
git add docs
git commit -m "docs: establish phase 2 execution baseline"
```

## 6. Task 2.1：业务动作、配置和权限扩展

**Files:**

- Modify: `backend/apps/authorization/actions.py`
- Create: `backend/apps/opportunities/apps.py`
- Create: `backend/apps/opportunities/policies/identity_provider.py`
- Create: `backend/apps/opportunities/services/configuration.py`
- Create: `backend/tests/opportunities/test_action_catalog.py`
- Create: `backend/tests/opportunities/test_opportunity_permissions.py`
- Modify: `backend/config/settings/base.py`

**Interfaces:**

- Consumes: `apps.authorization.policies.engine.authorize(...)`、`identity_registry`
- Produces: `OpportunityIdentityProvider`、阶段2动作目录、提案配置读取函数

- [ ] 先写动作目录测试，断言阶段2动作均已注册。

```python
@pytest.mark.django_db
def test_phase_2_actions_are_seeded():
    required = {
        "opportunity.create",
        "opportunity.edit",
        "opportunity.submit",
        "opportunity.withdraw",
        "opportunity.full.read",
        "opportunity.public_summary.read",
        "opportunity.export",
        "opportunity.member.invite",
        "opportunity.member.manage",
        "candidate.create",
        "candidate.combine",
        "candidate.split",
        "candidate.leadership.assign",
        "candidate.assessment.edit",
        "candidate.submit_review",
        "major_gate.management_conclusion.record",
        "major_gate.final_decision.record",
        "deferred_item.review",
        "reconsideration.create",
    }
    assert required <= set(PermissionAction.objects.values_list("action_code", flat=True))
```

- [ ] 运行测试并确认失败。

```powershell
Set-Location backend
uv run pytest tests/opportunities/test_action_catalog.py -q
```

- [ ] 扩展动作目录和 seed migration；动作类别使用 READ、WRITE、ADMIN，不引入动态表达式策略。
- [ ] 实现 `OpportunityIdentityProvider`，提案负责人、有效联合成员、立案负责人、副组长按对象身份授予最小动作。
- [ ] 实现 `get_opportunity_rule_snapshot(organization, now)`，从已发布配置读取成员上限、额度规则、提案资格角色和决策角色；配置缺失时返回明确错误码，不使用隐式默认授权。
- [ ] 验证权限默认拒绝、平台管理员不能读取高敏业务全文、联合成员不能读取未授权敏感评估。

```powershell
uv run pytest tests/opportunities/test_action_catalog.py tests/opportunities/test_opportunity_permissions.py -q
uv run python manage.py makemigrations --check --dry-run --settings=config.settings.test
```

- [ ] 提交。

```powershell
git add backend
git commit -m "feat: add phase 2 opportunity authorization actions"
```

## 7. Task 2.2：机会、提案版本、成员和额度模型

**Files:**

- Create: `backend/apps/opportunities/models/opportunity.py`
- Create: `backend/apps/opportunities/models/proposal_version.py`
- Create: `backend/apps/opportunities/models/member.py`
- Create: `backend/apps/opportunities/models/quota.py`
- Create: `backend/apps/opportunities/models/__init__.py`
- Create: `backend/apps/opportunities/migrations/0001_initial.py`
- Create: `backend/tests/opportunities/test_models.py`
- Create: `backend/tests/opportunities/test_quota.py`

**Interfaces:**

- Consumes: `OrganizationOwnedModel`、`identity.User`、`identity.Department`
- Produces: `Opportunity`、`ProposalVersion`、`OpportunityMember`、`SubmissionQuota`、`QuotaLedger`

- [ ] 先写模型不变量测试。

```python
@pytest.mark.django_db
def test_locked_proposal_version_cannot_be_changed(opportunity, proposal_version):
    proposal_version.lock_for_review(now=timezone.now())
    proposal_version.market_analysis = "changed"
    with pytest.raises(ProposalVersionLocked):
        proposal_version.save()

@pytest.mark.django_db
def test_one_opportunity_counts_quota_once(opportunity, quota_owner):
    QuotaLedger.objects.create(
        organization=opportunity.organization,
        opportunity=opportunity,
        quarter="2026Q3",
        owner_type="USER",
        owner_id=quota_owner.id,
        count_status="COUNTED",
    )
    with pytest.raises(IntegrityError):
        QuotaLedger.objects.create(
            organization=opportunity.organization,
            opportunity=opportunity,
            quarter="2026Q3",
            owner_type="USER",
            owner_id=quota_owner.id,
            count_status="COUNTED",
        )
```

- [ ] 运行测试并确认模型不存在导致失败。

```powershell
uv run pytest tests/opportunities/test_models.py tests/opportunities/test_quota.py -q
```

- [ ] 实现机会、版本、成员、额度规则和额度账模型；所有核心表包含 `organization_id`、`public_id`、状态码和必要索引。
- [ ] `ProposalVersion` 使用 `version_status` 表达 DRAFT、SUBMITTED、LOCKED、SUPERSEDED；锁定版本禁止内容更新。
- [ ] `OpportunityMember` 使用有效区间和邀请状态；同一用户同一机会只能有一条有效成员记录。
- [ ] `QuotaLedger` 对 `opportunity_id` 建唯一约束，保证复议或重复提交不重复计数。
- [ ] 生成迁移并验证。

```powershell
uv run python manage.py makemigrations opportunities --settings=config.settings.test
uv run python manage.py migrate --settings=config.settings.test
uv run pytest tests/opportunities/test_models.py tests/opportunities/test_quota.py -q
```

- [ ] 提交。

```powershell
git add backend
git commit -m "feat: add opportunity proposal and quota models"
```

## 8. Task 2.3：提案提交应用服务和 API

**Files:**

- Create: `backend/apps/opportunities/services/create_draft.py`
- Create: `backend/apps/opportunities/services/invite_member.py`
- Create: `backend/apps/opportunities/services/submit_proposal.py`
- Create: `backend/apps/opportunities/services/withdraw_proposal.py`
- Create: `backend/apps/opportunities/queries/opportunities.py`
- Create: `backend/apps/opportunities/api/opportunities.py`
- Create: `backend/apps/opportunities/api/urls.py`
- Create: `backend/tests/opportunities/test_submit_proposal.py`
- Create: `backend/tests/opportunities/test_opportunity_api.py`
- Modify: `backend/config/urls.py`
- Modify: `backend/config/settings/base.py`

**Interfaces:**

- Consumes: `CommandContext.for_actor(actor)`、`append_event(AuditRecord)`、`register_outbox_event(OutboxMessage)`、`authorize(...)`
- Produces: `CreateOpportunityDraft.execute() -> Opportunity`、`SubmitProposal.execute() -> Opportunity`

- [ ] 先写提案提交失败测试。

```python
@pytest.mark.django_db
def test_submit_proposal_requires_eligible_owner(active_user, opportunity):
    context = CommandContext.for_actor(active_user)
    service = SubmitProposal(
        context=context,
        opportunity_public_id=opportunity.public_id,
        version_no=opportunity.version_no,
        idempotency_key="submit-1",
    )
    with pytest.raises(ProposalSubmitterNotEligible):
        service.execute()
    opportunity.refresh_from_db()
    assert opportunity.proposal_status == "DRAFT"
```

- [ ] 先写 API 契约测试，拒绝结果使用统一错误结构且不泄露数据库主键。
- [ ] 运行测试并确认失败。

```powershell
uv run pytest tests/opportunities/test_submit_proposal.py tests/opportunities/test_opportunity_api.py -q
```

- [ ] 实现 `CreateOpportunityDraft`、`InviteOpportunityMember`、`SubmitProposal`、`WithdrawProposal`；所有写命令先判权，再在事务内 `select_for_update()` 锁定机会并校验 `version_no`。
- [ ] 提交时校验资格、四项核心内容、公开摘要、额度归属、成员有效性和重复提交；失败保留草稿。
- [ ] 成功提交时锁定提交版本、登记唯一额度账、写审计、登记 `proposal.submitted` outbox 和待办事件。
- [ ] 注册 API：`POST /api/v1/opportunities`、`GET/PATCH /api/v1/opportunities/{id}`、`POST /api/v1/opportunities/{id}/members/invitations`、`POST /api/v1/opportunities/{id}/submit`、`POST /api/v1/opportunities/{id}/withdraw`、`GET /api/v1/opportunities/{id}/versions`。
- [ ] 生成 OpenAPI 并验证前端类型可生成。

```powershell
uv run pytest tests/opportunities/test_submit_proposal.py tests/opportunities/test_opportunity_api.py -q
uv run python manage.py spectacular --file openapi/schema.yaml --validate --settings=config.settings.test
Set-Location ..\frontend
npm.cmd run api:generate
Set-Location ..\backend
```

- [ ] 提交。

```powershell
git add backend frontend/src/api/generated/schema.d.ts
git commit -m "feat: add proposal submission workflow"
```

## 9. Task 2.4：重大阶段门骨架和提案进入立案

**Files:**

- Create: `backend/apps/stage_gates/apps.py`
- Create: `backend/apps/stage_gates/models.py`
- Create: `backend/apps/stage_gates/services/create_review_cycle.py`
- Create: `backend/apps/stage_gates/services/record_major_decision.py`
- Create: `backend/apps/stage_gates/api/decisions.py`
- Create: `backend/apps/stage_gates/api/urls.py`
- Create: `backend/apps/stage_gates/migrations/0001_initial.py`
- Create: `backend/tests/stage_gates/test_major_decision.py`
- Create: `backend/tests/opportunities/test_proposal_to_case.py`
- Modify: `backend/config/urls.py`

**Interfaces:**

- Consumes: `ProposalVersion.lock_for_review(...)`、`append_event`、`register_outbox_event`
- Produces: `StageGateInstance`、`MajorGateDecision`、`RecordMajorGateDecision.execute()`

- [ ] 先写老板最终决策优先测试。

```python
@pytest.mark.django_db
def test_final_decision_controls_proposal_to_case_state(review_cycle):
    decision = RecordMajorGateDecision(
        context=CommandContext.for_actor(review_cycle.final_decision_actor),
        stage_gate_public_id=review_cycle.stage_gate.public_id,
        management_conclusion="APPROVED",
        final_decision="NEEDS_INFO",
        decision_summary="Boss requires more evidence.",
        idempotency_key="gate-1",
    ).execute()
    review_cycle.subject.refresh_from_db()
    assert decision.has_conclusion_difference is True
    assert review_cycle.subject.proposal_status == "NEEDS_INFO"
```

- [ ] 运行测试并确认失败。

```powershell
uv run pytest tests/stage_gates/test_major_decision.py tests/opportunities/test_proposal_to_case.py -q
```

- [ ] 实现 `StageGateInstance`、`GateMaterialReference`、`MajorGateDecision`；决策结果代码只使用总 TRD 固定值。
- [ ] 实现 `CreateProposalReviewCycle`，绑定 `PROPOSAL_TO_CASE` 和当前锁定提案版本，禁止同一材料版本进入多个活动评审周期。
- [ ] 实现 `RecordMajorGateDecision`；经管会整体结论与老板最终决策均必填，状态迁移只按老板最终决策。
- [ ] 决策为 APPROVED 时创建初始 `ProjectCandidate`；NEEDS_INFO、DEFERRED、PASSED 分别写入对应机会状态和历史。
- [ ] 注册 `POST /api/v1/opportunities/{id}/review-cycles` 和 `POST /api/v1/stage-gates/{id}/major-decision`。
- [ ] 验证并提交。

```powershell
uv run pytest tests/stage_gates tests/opportunities/test_proposal_to_case.py -q
uv run python manage.py makemigrations --check --dry-run --settings=config.settings.test
git add backend
git commit -m "feat: add proposal major stage gate"
```

## 10. Task 2.5：拟立项方案、立案评估和立项评审

**Files:**

- Create: `backend/apps/opportunities/models/candidate.py`
- Create: `backend/apps/opportunities/models/assessment.py`
- Create: `backend/apps/opportunities/services/assign_case_leadership.py`
- Create: `backend/apps/opportunities/services/update_assessment.py`
- Create: `backend/apps/opportunities/services/submit_project_review.py`
- Create: `backend/apps/opportunities/api/candidates.py`
- Create: `backend/tests/opportunities/test_candidate_assessment.py`
- Create: `backend/tests/opportunities/test_case_to_project_review.py`

**Interfaces:**

- Consumes: `DocumentVersion` for受控文件引用、`StageGateInstance`
- Produces: `ProjectCandidate`、`CandidateSource`、`CaseAssessment`、`SubmitProjectReview.execute()`

- [ ] 先写立案评估完整性测试。

```python
@pytest.mark.django_db
def test_submit_project_review_requires_all_core_assessments(candidate, case_owner):
    with pytest.raises(CaseAssessmentIncomplete) as exc:
        SubmitProjectReview(
            context=CommandContext.for_actor(case_owner),
            candidate_public_id=candidate.public_id,
            version_no=candidate.version_no,
            idempotency_key="project-review-1",
        ).execute()
    assert "COST" in exc.value.missing_categories
    candidate.refresh_from_db()
    assert candidate.status == "ASSESSING"
```

- [ ] 运行测试并确认失败。

```powershell
uv run pytest tests/opportunities/test_candidate_assessment.py tests/opportunities/test_case_to_project_review.py -q
```

- [ ] 实现 `ProjectCandidate`、`CandidateSource`、`CaseAssessment`；八类核心评估代码固定为 `PRODUCTION_PARTY`、`COOPERATION`、`FACTORY`、`PROCESS`、`RAW_PACKAGING`、`COST`、`SCHEDULE`、`RISK`。
- [ ] 实现 `AssignCaseLeadership`；非产品经理来源提案必须指定原提案组有效成员为副组长。
- [ ] 实现评估结论更新和受控文件引用；只允许引用 ACTIVE/CONTROLLED 文档版本。
- [ ] 实现 `SubmitProjectReview`，校验评估、资源风险、建议排期、文件版本和负责人后创建 `CASE_TO_PROJECT` 阶段门。
- [ ] 注册候选方案 API：`POST /api/v1/project-candidates`、`POST /api/v1/project-candidates/{id}/leadership`、`PATCH /api/v1/project-candidates/{id}/assessments/{code}`、`POST /api/v1/project-candidates/{id}/submit-review`。
- [ ] 验证并提交。

```powershell
uv run pytest tests/opportunities/test_candidate_assessment.py tests/opportunities/test_case_to_project_review.py -q
uv run python manage.py spectacular --file openapi/schema.yaml --validate --settings=config.settings.test
git add backend
git commit -m "feat: add project candidate assessment workflow"
```

## 11. Task 2.6：暂缓、季度回看、Pass、复议、合并和拆分

**Files:**

- Create: `backend/apps/opportunities/models/defer.py`
- Create: `backend/apps/opportunities/models/reconsideration.py`
- Create: `backend/apps/opportunities/services/defer_subject.py`
- Create: `backend/apps/opportunities/services/quarterly_review.py`
- Create: `backend/apps/opportunities/services/start_reconsideration.py`
- Create: `backend/apps/opportunities/services/combine_candidate_sources.py`
- Create: `backend/apps/opportunities/services/split_project_candidate.py`
- Create: `backend/apps/opportunities/api/deferred.py`
- Create: `backend/apps/opportunities/api/reconsiderations.py`
- Create: `backend/tests/opportunities/test_deferred_reconsideration.py`
- Create: `backend/tests/opportunities/test_combine_split.py`

**Interfaces:**

- Consumes: `Opportunity`、`ProjectCandidate`、`StageGateInstance`
- Produces: `DeferRecord`、`Reconsideration`、合并/拆分服务

- [ ] 先写暂缓和复议测试。

```python
@pytest.mark.django_db
def test_defer_accepts_restart_trigger_without_reason(review_cycle, final_decision_actor):
    record = DeferSubject(
        context=CommandContext.for_actor(final_decision_actor),
        subject_type="OPPORTUNITY",
        subject_public_id=review_cycle.subject.public_id,
        stage_code="PROPOSAL_TO_CASE",
        defer_reason="",
        restart_trigger="Competitor launch evidence arrives.",
        next_review_quarter="2026Q4",
    ).execute()
    assert record.restart_trigger == "Competitor launch evidence arrives."

@pytest.mark.django_db
def test_reconsideration_creates_new_cycle_without_editing_pass_record(passed_opportunity, eligible_owner):
    old_cycle_id = passed_opportunity.latest_review_cycle_id
    reconsideration = StartReconsideration(
        context=CommandContext.for_actor(eligible_owner),
        original_subject_public_id=passed_opportunity.public_id,
        target_stage_code="PROPOSAL_TO_CASE",
        reason="New customer evidence.",
    ).execute()
    assert reconsideration.original_cycle_id == old_cycle_id
    assert reconsideration.new_cycle_id != old_cycle_id
```

- [ ] 运行测试并确认失败。

```powershell
uv run pytest tests/opportunities/test_deferred_reconsideration.py tests/opportunities/test_combine_split.py -q
```

- [ ] 实现暂缓记录、季度回看、Pass记录和复议记录；原记录不可编辑，新动作追加新行。
- [ ] 实现合并：只新增 `CandidateSource`，不合并机会记录；所有来源机会必须已通过进入立案。
- [ ] 实现拆分：为同一机会创建多个独立候选方案，每个方案独立评估、评审和创建项目。
- [ ] 来源机会出现新决策时将相关候选方案标记为 `SOURCE_RECONFIRM_REQUIRED` 并阻止提交立项评审。
- [ ] 注册 `POST /api/v1/deferred-items/{id}/quarterly-review`、`POST /api/v1/reconsiderations`、`POST /api/v1/project-candidates/{id}/sources`、`POST /api/v1/project-candidates/{id}/split`、`GET /api/v1/opportunity-pool`。
- [ ] 验证并提交。

```powershell
uv run pytest tests/opportunities/test_deferred_reconsideration.py tests/opportunities/test_combine_split.py -q
git add backend
git commit -m "feat: add deferred reconsideration and candidate source flows"
```

## 12. Task 2.7：原子创建项目和产品草稿

**Files:**

- Create: `backend/apps/projects/apps.py`
- Create: `backend/apps/projects/models.py`
- Create: `backend/apps/projects/services/create_project_from_candidate.py`
- Create: `backend/apps/projects/api/projects.py`
- Create: `backend/apps/projects/api/urls.py`
- Create: `backend/apps/products/apps.py`
- Create: `backend/apps/products/models.py`
- Create: `backend/apps/products/services/create_draft_from_candidate.py`
- Create: `backend/apps/projects/migrations/0001_initial.py`
- Create: `backend/apps/products/migrations/0001_initial.py`
- Create: `backend/tests/opportunities/test_project_creation.py`
- Create: `backend/tests/projects/test_project_shell.py`
- Create: `backend/tests/products/test_product_draft_shell.py`
- Modify: `backend/config/urls.py`

**Interfaces:**

- Consumes: `ProjectCandidate`、`RecordMajorGateDecision`、`ConfigurationSnapshot`
- Produces: `Project`、`ProjectMember`、`ProjectOpportunitySource`、`ProductAsset`、`ProductDraft`

- [ ] 先写重复立项和失败回滚测试。

```python
@pytest.mark.django_db(transaction=True)
def test_approve_candidate_creates_one_project_for_repeated_request(approved_candidate, boss):
    first = ApproveAndCreateProject(
        context=CommandContext.for_actor(boss),
        candidate_public_id=approved_candidate.public_id,
        idempotency_key="create-project-1",
    ).execute()
    second = ApproveAndCreateProject(
        context=CommandContext.for_actor(boss),
        candidate_public_id=approved_candidate.public_id,
        idempotency_key="create-project-1",
    ).execute()
    assert first.project.public_id == second.project.public_id
    assert Project.objects.filter(candidate=approved_candidate).count() == 1

@pytest.mark.django_db(transaction=True)
def test_project_creation_failure_rolls_back_product_draft(approved_candidate, boss, monkeypatch):
    monkeypatch.setattr(
        "apps.products.services.create_draft_from_candidate.create_product_draft",
        raise_database_error,
    )
    with pytest.raises(ProjectCreationFailed):
        ApproveAndCreateProject(
            context=CommandContext.for_actor(boss),
            candidate_public_id=approved_candidate.public_id,
            idempotency_key="create-project-fails",
        ).execute()
    assert Project.objects.filter(candidate=approved_candidate).count() == 0
    assert ProductDraft.objects.count() == 0
```

- [ ] 运行测试并确认失败。

```powershell
uv run pytest tests/opportunities/test_project_creation.py tests/projects/test_project_shell.py tests/products/test_product_draft_shell.py -q
```

- [ ] 实现最小项目模型：`Project`、`ProjectMember`、`ProjectOpportunitySource`，包含组织、业务编号、候选方案、项目类型、状态、项目组长和来源机会。
- [ ] 实现最小产品模型：`ProductAsset`、`ProductDraft`，新品创建研发中产品和初始草稿，老品迭代关联已有产品并创建变更草稿。
- [ ] 实现 `ApproveAndCreateProject`：锁定候选方案、阶段门、来源关系，写重大决策，创建项目和产品草稿，建立来源关系，置候选方案为 `PROJECT_CREATED`，写审计和 outbox。
- [ ] 使用 `candidate_id` 唯一约束防止重复创建；幂等键返回第一次成功结果。
- [ ] 注册只读项目和产品草稿详情 API，支持前端立项成功后跳转。
- [ ] 验证并提交。

```powershell
uv run pytest tests/opportunities/test_project_creation.py tests/projects tests/products -q
uv run python manage.py makemigrations --check --dry-run --settings=config.settings.test
git add backend
git commit -m "feat: create project and product draft atomically"
```

## 13. Task 2.8：阶段2前端最小闭环

**Files:**

- Create: `frontend/src/modules/opportunities/store.ts`
- Create: `frontend/src/modules/opportunities/OpportunityListView.vue`
- Create: `frontend/src/modules/opportunities/OpportunityCreateView.vue`
- Create: `frontend/src/modules/opportunities/OpportunityWorkbenchView.vue`
- Create: `frontend/src/modules/opportunities/OpportunityPoolView.vue`
- Create: `frontend/src/modules/opportunities/ProposalQuotaPanel.vue`
- Create: `frontend/src/modules/stage-gates/MajorGateDecisionView.vue`
- Create: `frontend/src/modules/opportunities/OpportunityWorkbenchView.spec.ts`
- Create: `frontend/src/modules/stage-gates/MajorGateDecisionView.spec.ts`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/app/App.vue`

**Interfaces:**

- Consumes: OpenAPI generated types、`apiFetch<T>()`、auth store
- Produces: 阶段2页面路由和前端状态

- [ ] 先写前端表单和权限体验测试。

```typescript
it('blocks submit button until the four required proposal fields are present', async () => {
  const wrapper = mount(OpportunityCreateView, { global: { plugins: [pinia] } })
  expect(wrapper.get('[data-test="submit-proposal"]').attributes('disabled')).toBeDefined()
  await wrapper.get('[data-test="title"]').setValue('Greek Yogurt Cup')
  await wrapper.get('[data-test="market-analysis"]').setValue('Channel demand exists')
  await wrapper.get('[data-test="core-selling-points"]').setValue('High protein')
  await wrapper.get('[data-test="target-users-needs"]').setValue('Breakfast replacement')
  await wrapper.get('[data-test="suggested-retail-price"]').setValue('9.90')
  await wrapper.get('[data-test="public-summary"]').setValue('High protein yogurt')
  expect(wrapper.get('[data-test="submit-proposal"]').attributes('disabled')).toBeUndefined()
})
```

- [ ] 运行测试并确认失败。

```powershell
Set-Location frontend
npm.cmd run test:unit -- --run OpportunityWorkbenchView.spec.ts MajorGateDecisionView.spec.ts
```

- [ ] 实现提案入口：我的草稿、我负责的提案、我参与的联合提案、新建提案和季度额度提示。
- [ ] 实现机会工作台：当前阶段、状态、版本、成员、评估、文件、阶段门、暂缓/Pass/复议历史和来源关系。
- [ ] 实现重大阶段门评审页：材料版本、经管会结论、老板最终决策、差异提示和决策后状态预览。
- [ ] 实现候选机会池：按停留阶段、责任人、季度回看状态、触发条件和最近评审时间筛选。
- [ ] 前端只做体验校验；所有提交、撤回、决策、合并、拆分和立项创建仍以后端响应为准。
- [ ] 验证前端门禁。

```powershell
npm.cmd run api:generate
npm.cmd run lint
npm.cmd run format:check
npm.cmd run typecheck
npm.cmd run test:unit -- --run
npm.cmd run build
```

- [ ] 提交。

```powershell
git add frontend backend/openapi/schema.yaml
git commit -m "feat: add opportunity workflow UI"
```

## 14. Task 2.9：生命周期看板首版和阶段2 E2E

**Files:**

- Create: `backend/apps/opportunities/queries/lifecycle_board.py`
- Create: `backend/apps/opportunities/api/lifecycle_board.py`
- Create: `backend/tests/acceptance/test_opportunity_to_project.py`
- Create: `tests/e2e/opportunity-to-project.spec.ts`
- Modify: `tests/e2e/playwright.config.ts`
- Modify: `scripts/check.ps1`
- Modify: `frontend/src/modules/opportunities/LifecycleBoardView.vue`
- Modify: `frontend/src/router/index.ts`

**Interfaces:**

- Consumes: `Opportunity`、`Project`、`ProductDraft`、开发登录、OpenAPI generated types
- Produces: `GET /api/v1/lifecycle-board`、阶段2 E2E

- [ ] 先写后端验收测试，串联产品经理独立提案到创建项目。

```python
@pytest.mark.django_db(transaction=True)
def test_product_manager_can_submit_review_and_create_project(
    client, product_manager, phase2_configuration
):
    client.force_login(product_manager)
    create_response = client.post(
        "/api/v1/opportunities",
        data={
            "title": "High protein yogurt",
            "initial_type": "NEW",
            "public_summary": "Breakfast protein yogurt",
            "market_analysis": "Demand exists in convenience channels.",
            "core_selling_points": "High protein and low sugar.",
            "target_users_needs": "Breakfast replacement.",
            "suggested_retail_price": "9.90",
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    opportunity_id = create_response.json()["public_id"]
    submit_response = client.post(
        f"/api/v1/opportunities/{opportunity_id}/submit",
        data={"idempotency_key": "submit-e2e"},
        content_type="application/json",
    )
    assert submit_response.status_code == 200
```

- [ ] 写 Playwright E2E：开发登录、新建提案、提交、记录两次重大阶段门、看到项目创建成功和生命周期看板出现项目。
- [ ] 运行测试并确认失败。

```powershell
Set-Location backend
uv run pytest tests/acceptance/test_opportunity_to_project.py -q
Set-Location ..\tests\e2e
npx.cmd playwright test opportunity-to-project.spec.ts
```

- [ ] 实现生命周期看板首版查询，统一展示立项前机会和已创建项目，支持阶段、状态、负责人筛选和稳定分页。
- [ ] 将阶段2 E2E 加入 `scripts/check.ps1`，不允许跳过、xfail 或 SQLite 替代。
- [ ] 验证后端验收、E2E 和全量门禁。

```powershell
Set-Location backend
uv run pytest tests/acceptance/test_opportunity_to_project.py -q
Set-Location ..
scripts\check.cmd
```

- [ ] 提交。

```powershell
git add backend frontend tests scripts
git commit -m "test: add phase 2 opportunity to project acceptance"
```

## 15. Task 2.10：阶段退出证据和文档闭合

**Files:**

- Create: `docs/implementation/phase-2-checkpoint.md`
- Modify: `docs/implementation/phase-2-test-matrix.md`
- Modify: `docs/development/01-phased-implementation-plan.md`
- Modify: `README.md`

**Interfaces:**

- Consumes: CI 结果、本地门禁、OpenAPI、E2E、测试矩阵
- Produces: 阶段2完成检查点

- [ ] 生成 OpenAPI 和前端类型，确认无漂移。

```powershell
Set-Location backend
uv run python manage.py spectacular --file openapi/schema.yaml --validate --settings=config.settings.test
Set-Location ..\frontend
npm.cmd run api:generate
Set-Location ..
git diff --exit-code -- backend/openapi/schema.yaml frontend/src/api/generated/schema.d.ts
```

- [ ] 执行最终门禁。

```powershell
scripts\preflight.cmd
scripts\check.cmd
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-trd.ps1
git status --short
git log --oneline --decorate -10
```

预期：所有命令退出码0；TRD校验仍为6份文档、92项需求、4个重大阶段门；工作区只显示本任务预期文档修改。

- [ ] 更新测试矩阵，OPP-001 至 OPP-015、GLB-001 至 GLB-003 均关联实际测试或E2E证据。
- [ ] 创建 `phase-2-checkpoint.md`，记录提交哈希、迁移、测试数量、E2E结果、CI链接、已知限制和下一阶段边界。
- [ ] 将主计划阶段2标记完成，README当前状态更新为“阶段2已完成，阶段3尚未开始”。
- [ ] 提交。

```powershell
git add docs README.md
git diff --cached --check
git commit -m "docs: record phase 2 completion evidence"
```

## 16. 阶段2明确不实现

- 完整产品档案、产品版本发布、SKU、渠道配置、营养成分和包装素材管理；
- 存量产品导入、重复识别和产品总监确认导入基线；
- D1-L3项目执行模板、任务依赖、逾期、计划调整、完整交付物和专业确认；
- 新品首次上市 `FIRST_LAUNCH` 和产品退市 `PRODUCT_RETIREMENT`；
- 经营事实、风险信号、经营议题和运营监控；
- 真实钉钉企业登录、组织同步和真实通知投递验收；
- 外部业务数据接入、迁移演练、备份恢复和离线发布。

## 17. 执行风险与停线条件

| 风险 | 处理 |
|---|---|
| 阶段1 remediation 未合入主线 | 停止阶段2开发，先合入并复跑阶段1门禁 |
| 立案评估任务与阶段4项目执行边界混淆 | 只实现 `CaseAssessment` 和文件引用，不创建通用 `work_items` |
| 产品草稿被实现成完整产品档案 | 停止并拆回阶段3，阶段2只保留最小 `ProductDraft` |
| 权限在 View 或前端硬编码 | 停止并补充对象身份提供器与动作目录 |
| 审计或 outbox 不在事务内 | 关键命令不得合并 |
| 合并/拆分破坏机会历史 | 保留独立机会和来源关系，只追加关系，不覆盖历史 |
| 重复立项创建多个项目 | 必须用 `candidate_id` 唯一约束和幂等键修复 |
| E2E 依赖真实钉钉 | 改用开发登录和假网关，真实钉钉验收留阶段6 |
| 计划超过一个可审查 PR | 按 Task 2.1-2.3、2.4-2.6、2.7、2.8-2.10 拆为连续 PR |
