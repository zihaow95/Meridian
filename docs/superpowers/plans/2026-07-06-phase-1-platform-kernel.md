# Project Meridian 阶段1平台内核实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付所有后续业务域可直接复用的组织身份、认证、权限、审计、可靠事件、配置版本、受控文件、待办和通知内核，并满足PLT-001至PLT-013及PLT-016的基础验收。

**Architecture:** 保持Django模块化单体，各平台模块拥有独立模型和应用服务；写命令在同一MySQL事务内完成权限复核、业务变化、审计和发件箱登记。外部认证、通知和文件存储通过窄接口隔离，开发环境使用可控适配器，生产使用钉钉和NAS实现；Vue只提供登录、我的待办和必要管理闭环，不承载权威权限规则。

**Tech Stack:** Python 3.13、Django 5.2、Django REST Framework、MySQL 8.0、Redis、Celery 5.6、httpx、jsonschema、Vue 3、TypeScript、Pinia、Element Plus、Vitest、Playwright、Docker Compose、GitHub Actions。

**Status:** 待执行

**Date:** 2026-07-06

---

## 1. 基线决策与边界

- 阶段0检查点`ce65270`已验收；执行前必须从最新`main`创建`codex/phase-1-platform-kernel`。
- 主计划将钉钉正式接入安排在阶段6。本计划在阶段1先建立认证抽象层：实现开发登录适配器与钉钉认证/通知适配器代码，并用假网关和`httpx.MockTransport`完成契约与端到端确定性测试。真实钉钉企业环境的一次性外部验收（真实登录与通知投递）依赖企业应用凭据和回调白名单，记为阶段6前完成的延后验收项，不阻塞阶段1闭合；PLT-001、PLT-012在阶段1以假网关和契约测试作为证据，真实环境证据在阶段6补齐。
- 钉钉岗位、部门和职级不得自动授予关键业务角色。
- PLT-014外部业务数据接入批次、PLT-015备份恢复不在本阶段实现。
- 阶段1不创建提案、产品、项目、阶段门或交付物模型；项目身份通过扩展接口接入，阶段2再注册真实提供者。
- NAS开发替代目录与生产NFS使用同一文件系统适配器；不引入MinIO和云对象存储。
- 组织、用户、配置、文件和待办API只实现平台内核所需闭环，不建设通用低代码管理台。
- 运行看板（TRD 18）中依赖外部集成与备份的部分随PLT-014/015后置；阶段1只在需要时提供最小MySQL/Redis/NAS健康检查，不建设完整运行看板。
- 远端策略：GitHub为主仓库并触发CI，Gitee为镜像；每个PR合并到`main`后执行`git push gitee main`保持镜像一致。

## 2. 完成定义

1. 钉钉认证成功但内部用户非ACTIVE时不能建立会话；开发登录在生产设置下不可注册。阶段1以假网关和契约测试验证该规则，真实钉钉环境验收见第16节延后说明。
2. 单组织边界进入所有平台核心表和查询；用户、部门和外部身份历史不被覆盖。
3. RBAC + ABAC默认拒绝，列表、字段、预览、下载、导出和通知分别判权。
4. 平台管理角色不能绕过业务数据权限；关键角色只允许人工配置。
5. 双人复核开关、专项授权和排障访问按有效期实时判定且全程留痕。
6. 关键写命令的业务变化、审计和发件箱同事务提交；审计失败则整体回滚。
7. Redis不可用时MySQL业务事实和PENDING事件不丢失，恢复后可继续投递且消费幂等。
8. 发布配置不可修改；新版本不改变既有快照。
9. 文件流式上传、SHA-256、PENDING—ACTIVE补偿、不可变版本链和单用途下载票据可运行。
10. 系统待办是权威入口；重复事件不产生重复OPEN待办；钉钉失败不回滚业务。
11. 前端完成登录、当前用户、我的待办及最小管理页面闭环。
12. MySQL集成测试、前端测试、Playwright平台内核冒烟测试和CI全部通过。

## 3. 需求映射

| 需求 | 任务 |
|---|---|
| PLT-001、PLT-002、PLT-016 | Task 1.1—1.3 |
| PLT-003、PLT-004、PLT-005、PLT-006 | Task 1.4 |
| PLT-007、PLT-008 | Task 1.6 |
| PLT-009 | Task 1.8 |
| PLT-010 | Task 1.9 |
| PLT-011、PLT-012 | Task 1.10—1.11 |
| PLT-013 | Task 1.5 |
| 全部可靠异步处理 | Task 1.7 |
| PLT-014、PLT-015 | 本阶段不实现，见阶段6集成与阶段7生产化 |

## 4. Task 1.0：建立阶段分支和测试基线

**Files:**

- Modify: `docs/development/01-phased-implementation-plan.md`
- Create: `docs/implementation/phase-1-test-matrix.md`

- [ ] 更新主分支并确认阶段0门禁仍通过。

```powershell
git switch main
git pull --ff-only origin main
git status --short
scripts\check.cmd
git switch -c codex/phase-1-platform-kernel
```

预期：工作区干净，20项阶段0门禁退出码0，新分支从`ce65270`或其后继提交创建。

- [ ] 在测试矩阵中逐项登记PLT-001至PLT-013、PLT-016的自动化证据位置，初始状态统一为`未实现`，禁止预填“通过”；PLT-014、PLT-015单列并标注“本阶段不实现，见阶段6/阶段7”，PLT-001、PLT-012额外标注“真实钉钉环境验收延后至阶段6”。
- [ ] 在主计划阶段1处链接本计划和测试矩阵，不提前修改阶段状态。
- [ ] 提交。

```powershell
git add docs
git commit -m "docs: establish phase 1 execution baseline"
```

## 5. Task 1.1：建立平台通用契约和自定义用户迁移边界

**Files:**

- Create: `backend/apps/platform/models/base.py`
- Create: `backend/apps/platform/api/errors.py`
- Create: `backend/apps/platform/api/exception_handler.py`
- Create: `backend/apps/platform/request_context.py`
- Create: `backend/tests/api/test_error_contract.py`
- Modify: `backend/config/settings/base.py`
- Modify: `backend/config/urls.py`
- Modify: `backend/apps/platform/api/health.py`
- Modify: `backend/tests/api/test_health.py`

- [ ] 先编写错误契约测试，要求未知对象和无权对象均返回相同404式结构：

```python
def test_hidden_resource_error_does_not_reveal_existence(api_client) -> None:
    response = api_client.get("/api/v1/_test/hidden-resource")
    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
    assert set(response.json()) == {"code", "message", "details", "trace_id"}
```

- [ ] 运行测试并确认因统一异常处理器不存在而失败。

```powershell
Set-Location backend
uv run pytest tests/api/test_error_contract.py -q
```

- [ ] 实现`PublicIdModel`、`OrganizationOwnedModel`和只负责生成/透传`trace_id`的请求上下文；统一异常处理器不得返回SQL、堆栈、服务器路径和对象存在性。
- [ ] 将DRF认证默认设为会话认证、权限默认设为拒绝；本任务同步把健康检查由现有`permission_classes = []`改为显式`AllowAny`并保留其测试，并确认`/api/v1/schema`与`/api/v1/docs`在默认拒绝下仍显式放行，使CI的OpenAPI生成与契约测试不受影响。后续认证起点也必须逐个显式放行。
- [ ] 在设置中加入`django.contrib.sessions`、`django.contrib.auth`及对应中间件，但本任务不创建用户表。
- [ ] 验证错误契约和阶段0回归。

```powershell
uv run pytest tests/api/test_error_contract.py tests/api/test_health.py -q
uv run python manage.py check --settings=config.settings.test
```

- [ ] 提交。

```powershell
git add backend
git commit -m "feat: add platform API and model contracts"
```

## 6. Task 1.2：实现组织、用户和身份绑定

**Files:**

- Create: `backend/apps/identity/apps.py`
- Create: `backend/apps/identity/models/organization.py`
- Create: `backend/apps/identity/models/department.py`
- Create: `backend/apps/identity/models/user.py`
- Create: `backend/apps/identity/models/binding.py`
- Create: `backend/apps/identity/services/change_user_status.py`
- Create: `backend/apps/identity/migrations/0001_initial.py`
- Create: `backend/tests/identity/test_models.py`
- Create: `backend/tests/identity/test_user_status.py`
- Modify: `backend/config/settings/base.py`

- [ ] 先编写MySQL测试，固定以下不变量：

```python
@pytest.mark.django_db
def test_same_dingtalk_identity_cannot_bind_two_users(
    organization, active_user, another_active_user
) -> None:
    IdentityBinding.objects.create(
        user=active_user,
        provider="DINGTALK",
        provider_tenant_id="corp-1",
        provider_user_id="user-1",
    )
    with pytest.raises(IntegrityError):
        IdentityBinding.objects.create(
            user=another_active_user,
            provider="DINGTALK",
            provider_tenant_id="corp-1",
            provider_user_id="user-1",
        )
```

- [ ] 运行测试并确认模型未定义。
- [ ] 实现单一活动`Organization`、有效区间`Department`、`UserDepartment`、自定义`User(AbstractBaseUser)`和`IdentityBinding`；内部外键只引用用户主键，不引用姓名、工号或钉钉ID。
- [ ] 设置`AUTH_USER_MODEL = "identity.User"`。由于阶段0无业务数据，重建本地开发数据库，不编写兼容旧Django默认用户表的数据迁移。`identity` app必须在首次`migrate`前进入`INSTALLED_APPS`，使`auth`/`contenttypes`迁移基于swapped用户建立；工程未安装`django.contrib.admin`，无额外外键残留。CI与任何新环境天然从空库迁移，无需删卷；`docker volume rm`仅针对本地已迁移的开发库。

```powershell
docker compose -f deploy/compose/compose.dev.yml --env-file .env exec mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "SHOW TABLES FROM \`$MYSQL_DATABASE\`;"'
docker compose -f deploy/compose/compose.dev.yml --env-file .env down
docker volume rm meridian_mysql_data
docker compose -f deploy/compose/compose.dev.yml --env-file .env up -d
Set-Location backend
uv run python manage.py migrate --settings=config.settings.development
```

预期：第一条命令只能看到阶段0的Django基础表；若发现人工表或人工数据则停止，不执行后续删除命令。

- [ ] `ChangeUserStatus`在停用/离职时记录时间，不删除身份和部门历史。

```powershell
uv run pytest tests/identity -q
uv run python manage.py makemigrations --check --dry-run --settings=config.settings.test
```

- [ ] 提交。

```powershell
git add backend
git commit -m "feat: add organization and identity models"
```

## 7. Task 1.3：实现开发登录和钉钉认证适配器

**Files:**

- Create: `backend/apps/integrations/dingtalk/contracts.py`
- Create: `backend/apps/integrations/dingtalk/http_gateway.py`
- Create: `backend/apps/integrations/dingtalk/fake_gateway.py`
- Create: `backend/apps/identity/services/authenticate_dingtalk.py`
- Create: `backend/apps/identity/api/auth.py`
- Create: `backend/apps/identity/api/me.py`
- Create: `backend/apps/identity/api/urls.py`
- Create: `backend/tests/identity/test_authentication.py`
- Create: `backend/tests/identity/test_production_auth_settings.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/config/settings/base.py`
- Modify: `backend/config/settings/development.py`
- Modify: `backend/config/settings/test.py`
- Modify: `backend/config/settings/production.py`

- [ ] 添加`httpx`并锁定依赖。

```powershell
Set-Location backend
uv add "httpx>=0.28,<0.29"
```

- [ ] 先编写认证拒绝测试：

```python
@pytest.mark.django_db
def test_dingtalk_success_cannot_log_in_disabled_internal_user(
    client, disabled_user, dingtalk_binding, fake_dingtalk_gateway
) -> None:
    response = client.get("/api/v1/auth/dingtalk/callback?code=valid&state=valid")
    assert response.status_code == 403
    assert response.json()["code"] == "USER_NOT_ACTIVE"
    assert "_auth_user_id" not in client.session
```

- [ ] 实现`DingTalkGateway.exchange_code(code) -> DingTalkIdentity`和通知发送窄接口；领域服务不得直接导入第三方SDK。
- [ ] `state`只存服务端哈希、原跳转路径和短时过期时间，成功或失败使用一次后立即失效；回调只允许站内相对深链接。
- [ ] 开发登录端点只在`DEBUG`且`ENABLE_DEV_LOGIN=true`时注册；生产设置检测到该开关必须启动失败。
- [ ] 实现`GET /api/v1/auth/dingtalk/start`、回调、退出和`GET /api/v1/me`，所有写操作启用CSRF；提供CSRF cookie下发方式（登录成功或`GET /api/v1/me`时以`ensure_csrf_cookie`下发），前端后续POST以`X-CSRFToken`头携带，否则写请求会被拒绝。
- [ ] 测试真实HTTP网关使用`httpx.MockTransport`，不访问外网；测试环境再使用`FakeDingTalkGateway`做端到端认证。

```powershell
uv run pytest tests/identity -q
uv run python manage.py check --settings=config.settings.production --deploy
```

- [ ] 提交。

```powershell
git add backend
git commit -m "feat: add session and DingTalk authentication"
```

## 8. Task 1.4：实现RBAC、ABAC和对象身份扩展点

**Files:**

- Create: `backend/apps/authorization/models/role.py`
- Create: `backend/apps/authorization/models/assignment.py`
- Create: `backend/apps/authorization/actions.py`
- Create: `backend/apps/authorization/context.py`
- Create: `backend/apps/authorization/policies/engine.py`
- Create: `backend/apps/authorization/policies/identity_provider.py`
- Create: `backend/apps/authorization/services/assign_role.py`
- Create: `backend/apps/authorization/queries/visible_resources.py`
- Create: `backend/apps/authorization/api/admin.py`
- Create: `backend/apps/authorization/migrations/0001_initial.py`
- Create: `backend/tests/authorization/test_engine.py`
- Create: `backend/tests/authorization/test_role_assignment.py`
- Create: `backend/tests/authorization/test_query_filtering.py`

- [ ] 先写默认拒绝和平台管理权隔离测试：

```python
def test_platform_admin_cannot_read_highly_sensitive_business_resource(
    platform_admin_subject, highly_sensitive_resource
) -> None:
    decision = authorize(
        platform_admin_subject,
        action="product.formula.read",
        resource=highly_sensitive_resource,
        context=AuthorizationContext.now(),
    )
    assert decision.allowed is False
    assert decision.reason_code == "NO_ALLOWING_POLICY"
```

- [ ] 实现动作目录、角色、角色动作、有效区间分配及ORGANIZATION/DEPARTMENT/PRODUCT_SET范围。
- [ ] 实现固定敏感等级枚举和`authorize(subject, action, resource, context)`八步判定；未知动作、缺失提供者和不完整上下文全部拒绝。
- [ ] 定义`ObjectIdentityProvider`协议及注册表；阶段1只提供空实现和测试实现，禁止创建项目假表。
- [ ] 列表查询必须通过`VisibleResourceFilter`生成数据库过滤条件，高敏字段通过字段策略投影，不允许先全量读取再在前端隐藏。
- [ ] 角色分配服务在事务内重新判权；关键角色只接受人工命令，不读取钉钉职位自动分配。

```powershell
Set-Location backend
uv run pytest tests/authorization -q
```

- [ ] 提交。

```powershell
git add backend
git commit -m "feat: add RBAC and ABAC authorization kernel"
```

## 9. Task 1.5：实现不可变审计和事务命令边界

**Files:**

- Create: `backend/apps/audit/models.py`
- Create: `backend/apps/audit/services/append_event.py`
- Create: `backend/apps/audit/queries/events.py`
- Create: `backend/apps/audit/api/admin.py`
- Create: `backend/apps/audit/migrations/0001_initial.py`
- Create: `backend/apps/platform/application/command.py`
- Create: `backend/tests/audit/test_append_only.py`
- Create: `backend/tests/audit/test_transactional_audit.py`
- Modify: `backend/apps/identity/services/change_user_status.py`
- Modify: `backend/apps/authorization/services/assign_role.py`

- [ ] 先写审计失败必须回滚业务事实的测试：

```python
@pytest.mark.django_db(transaction=True)
def test_critical_command_rolls_back_when_audit_write_fails(
    active_user, monkeypatch
) -> None:
    monkeypatch.setattr("apps.audit.services.append_event.append_event", raise_database_error)
    with pytest.raises(AuditWriteFailed):
        ChangeUserStatus(actor=active_user, target=active_user, status="DISABLED").execute()
    active_user.refresh_from_db()
    assert active_user.status == "ACTIVE"
```

- [ ] `AuditEvent`保存角色快照、动作、资源公开ID、结果、必要前后摘要、原因、trace_id和关联快照；禁止保存令牌、Cookie、请求头和文件正文。
- [ ] 应用服务通过`CommandContext`显式接收actor、trace_id和当前时间；关键写命令在`transaction.atomic()`内重新判权并追加审计。
- [ ] 业务代码不提供更新或删除审计的服务和API；生产部署文档要求数据库账号对审计表仅INSERT/SELECT。
- [ ] 管理查询API使用`audit.read`且只返回脱敏摘要。

```powershell
uv run pytest tests/audit tests/identity/test_user_status.py -q
```

- [ ] 提交。

```powershell
git add backend
git commit -m "feat: add transactional append-only audit"
```

## 10. Task 1.6：实现双人复核、专项授权和排障访问

**Files:**

- Create: `backend/apps/authorization/models/admin_change.py`
- Create: `backend/apps/authorization/models/special_grant.py`
- Create: `backend/apps/authorization/models/troubleshoot.py`
- Create: `backend/apps/authorization/services/request_admin_change.py`
- Create: `backend/apps/authorization/services/review_admin_change.py`
- Create: `backend/apps/authorization/services/create_special_grant.py`
- Create: `backend/apps/authorization/services/open_troubleshoot_access.py`
- Create: `backend/apps/authorization/api/grants.py`
- Create: `backend/tests/authorization/test_dual_control.py`
- Create: `backend/tests/authorization/test_special_grants.py`
- Create: `backend/tests/authorization/test_troubleshoot.py`

- [ ] 先写双人复核规则测试：

```python
@pytest.mark.django_db
def test_proposer_cannot_review_own_admin_change(change_request) -> None:
    with pytest.raises(ReviewerMustDiffer):
        ReviewAdminChange(actor=change_request.proposed_by, request=change_request).approve()
    change_request.refresh_from_db()
    assert change_request.status == "PENDING"
```

- [ ] 实现版本化`SecuritySetting.dual_control_enabled`和一次性`AdminChangeRequest`状态机。
- [ ] 关闭开关时仅指定超级管理员可直接执行；开启时超级管理员变更、关键角色授权、排障开启及开关变更必须生成请求。
- [ ] 专项授权创建时使用相同动作、对象范围和敏感等级验证授权人，禁止越权转授。
- [ ] 排障访问绑定最小对象、动作、等级和有效期；每次请求实时比较`valid_to`，到期扫描只做补充。
- [ ] 以上变更全部走Task 1.5命令边界并写审计。

```powershell
uv run pytest tests/authorization -q
```

- [ ] 提交。

```powershell
git add backend
git commit -m "feat: add controlled administrative access"
```

## 11. Task 1.7：实现MySQL事件发件箱和Celery幂等消费

**Files:**

- Create: `backend/apps/platform/outbox/models.py`
- Create: `backend/apps/platform/outbox/services.py`
- Create: `backend/apps/platform/outbox/dispatcher.py`
- Create: `backend/apps/platform/outbox/tasks.py`
- Create: `backend/apps/platform/outbox/consumer.py`
- Create: `backend/apps/platform/outbox/migrations/0001_initial.py`
- Create: `backend/config/celery.py`
- Create: `backend/tests/platform/test_outbox.py`
- Create: `backend/tests/platform/test_consumer_idempotency.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/config/settings/base.py`
- Modify: `backend/apps/platform/application/command.py`
- Modify: `README.md`

- [ ] 添加并锁定Celery/Redis依赖。

```powershell
Set-Location backend
uv add "celery>=5.6,<5.7" "redis>=6,<7"
uv lock --check
```

> 版本核实：Celery 5.6、redis-py 6.x 为工程规范既定基线（与Django 5.2、Python 3.13同属本时间线较新版本）。执行时以`uv`实际解析为准；若某版本尚未发布或与kombu不兼容，回退到最新可用5.x并同步更新`docs/development/02-engineering-standards.md`，不得静默偏离基线。

- [ ] 先写Redis投递失败不丢业务事件的测试：

```python
@pytest.mark.django_db(transaction=True)
def test_publish_failure_keeps_committed_event_pending(outbox_event, failing_publisher) -> None:
    dispatch_pending_events(publisher=failing_publisher, limit=10)
    outbox_event.refresh_from_db()
    assert outbox_event.status == "PENDING"
    assert outbox_event.attempt_count == 1
    assert outbox_event.next_attempt_at is not None
```

- [ ] `OutboxEvent`与业务事实同事务创建，载荷只含公开标识和最小必要数据。
- [ ] 分发器用短事务和`select_for_update(skip_locked=True)`领取事件；投递失败保留PENDING/FAILED和下次重试时间。
- [ ] `ConsumerReceipt(event_id, consumer_code)`唯一约束保证重复投递只产生一次业务副作用。
- [ ] 测试设置使用Celery eager模式；README给出宿主机worker和beat启动命令。阶段1不把应用进程塞入开发Compose，避免引入容器内数据库地址和源码挂载的额外分支。

```powershell
uv run pytest tests/platform -q
uv run celery -A config worker --help
uv run celery -A config beat --help
```

- [ ] 提交。

```powershell
git add backend README.md
git commit -m "feat: add transactional outbox and Celery delivery"
```

## 12. Task 1.8：实现不可变配置版本和引用快照

**Files:**

- Create: `backend/apps/configuration/models.py`
- Create: `backend/apps/configuration/schema_registry.py`
- Create: `backend/apps/configuration/services/create_draft.py`
- Create: `backend/apps/configuration/services/validate_version.py`
- Create: `backend/apps/configuration/services/publish_version.py`
- Create: `backend/apps/configuration/services/create_snapshot.py`
- Create: `backend/apps/configuration/api/configurations.py`
- Create: `backend/apps/configuration/migrations/0001_initial.py`
- Create: `backend/tests/configuration/test_publish.py`
- Create: `backend/tests/configuration/test_snapshots.py`
- Modify: `backend/pyproject.toml`

- [ ] 添加`jsonschema`并先写不可变测试：

```python
@pytest.mark.django_db
def test_published_configuration_cannot_be_edited(published_version) -> None:
    with pytest.raises(PublishedConfigurationImmutable):
        published_version.replace_content({"changed": True})
```

- [ ] 实现`Definition`、`Version`、`Snapshot`及DRAFT→VALIDATING→PUBLISHED/FAILED→RETIRED状态规则。
- [ ] Schema由代码注册，内容JSON只保存业务配置；管理员不能提交任意可执行表达式。
- [ ] 发布在事务内校验Schema和引用、记录差异摘要、保留上一发布版本，并登记`configuration.published`事件。
- [ ] 快照保存配置版本ID、内容副本和哈希；V2发布不得改变V1快照。

```powershell
uv add "jsonschema>=4.24,<5"
uv run pytest tests/configuration -q
```

- [ ] 提交。

```powershell
git add backend
git commit -m "feat: add immutable configuration versions"
```

## 13. Task 1.9：实现受控文件、补偿和下载票据

**Files:**

- Create: `backend/apps/documents/models.py`
- Create: `backend/apps/documents/storage/base.py`
- Create: `backend/apps/documents/storage/filesystem.py`
- Create: `backend/apps/documents/services/uploads.py`
- Create: `backend/apps/documents/services/versions.py`
- Create: `backend/apps/documents/services/tickets.py`
- Create: `backend/apps/documents/services/reconcile.py`
- Create: `backend/apps/documents/api/uploads.py`
- Create: `backend/apps/documents/api/documents.py`
- Create: `backend/apps/documents/migrations/0001_initial.py`
- Create: `backend/tests/documents/test_uploads.py`
- Create: `backend/tests/documents/test_versions.py`
- Create: `backend/tests/documents/test_download_tickets.py`
- Create: `backend/tests/documents/test_reconciliation.py`

- [ ] 先写上传中断不产生ACTIVE对象的测试：

```python
@pytest.mark.django_db
def test_atomic_move_failure_never_activates_file(
    upload_session, storage_that_fails_move
) -> None:
    with pytest.raises(StorageMoveFailed):
        complete_upload(upload_session.public_id, storage=storage_that_fails_move)
    assert not FileObject.objects.filter(storage_status="ACTIVE").exists()
    assert not DocumentVersion.objects.filter(status="CONTROLLED").exists()
```

- [ ] 文件通过`UploadedFile.chunks()`写临时目录并同步计算SHA-256和大小，不整文件读入内存。文件类型白名单和大小上限从已发布配置版本（Task 1.8）读取；配置尚未就绪时从settings读取默认值并预留配置接入点，不硬编码。
- [ ] 对象键使用UUID路径且不含原文件名；本地/NFS适配器使用同文件系统`os.replace`完成原子移动。
- [ ] 实现文件对象、逻辑文档、不可变版本链、业务链接和PENDING—ACTIVE补偿；同名文件不覆盖。
- [ ] 下载票据数据库只存令牌哈希，绑定用户、版本、动作和短时有效期；成功使用后原子标记已消费。
- [ ] API返回Nginx内部重定向头（X-Accel-Redirect），不直接暴露NAS目录；预览与下载分别调用权限动作并记录审计。本地与CI无前置Nginx，测试只断言“返回内部重定向头且不泄露NAS真实路径”，真实X-Accel端到端验收随部署（阶段7）完成；如需可在`deploy/nginx`补充受控`internal location`示例并标注后置。
- [ ] 巡检只标记MISSING和清理超时临时/PENDING文件，绝不删除受控历史。

```powershell
Set-Location backend
uv run pytest tests/documents -q
```

- [ ] 提交。

```powershell
git add backend
git commit -m "feat: add controlled document storage"
```

## 14. Task 1.10：实现权威待办、站内通知和钉钉投递

**Files:**

- Create: `backend/apps/notifications/models.py`
- Create: `backend/apps/notifications/services/todos.py`
- Create: `backend/apps/notifications/services/notifications.py`
- Create: `backend/apps/notifications/consumers.py`
- Create: `backend/apps/notifications/channels/dingtalk.py`
- Create: `backend/apps/notifications/api/todos.py`
- Create: `backend/apps/notifications/api/notifications.py`
- Create: `backend/apps/notifications/migrations/0001_initial.py`
- Create: `backend/tests/notifications/test_todos.py`
- Create: `backend/tests/notifications/test_permission_filtering.py`
- Create: `backend/tests/notifications/test_dingtalk_delivery.py`

- [ ] 先写重复事件和外部失败测试：

```python
@pytest.mark.django_db
def test_duplicate_event_creates_one_open_todo(event, todo_consumer) -> None:
    todo_consumer.consume(event)
    todo_consumer.consume(event)
    assert Todo.objects.filter(assignee=event.assignee, status="OPEN").count() == 1

@pytest.mark.django_db
def test_dingtalk_failure_does_not_remove_authoritative_todo(todo, failing_gateway) -> None:
    deliver_notification(todo.notification_id, gateway=failing_gateway)
    todo.refresh_from_db()
    assert todo.status == "OPEN"
```

- [ ] 实现Todo唯一活动去重键、状态变化服务、Notification和Delivery；待办永远先于外部投递落库。
- [ ] 通知消费者按接收人重新判权，只生成最小摘要和站内深链接；无权字段不得先写入再隐藏。
- [ ] 钉钉渠道只通知和跳转，不承载确认、审批或状态变更；失败有限重试并保存脱敏错误码。
- [ ] 点击深链接后由目标API实时判权；通知去重键使用事件、接收人和通知类型。

```powershell
uv run pytest tests/notifications tests/platform/test_consumer_idempotency.py -q
```

- [ ] 提交。

```powershell
git add backend
git commit -m "feat: add authoritative todos and notifications"
```

## 15. Task 1.11：交付平台内核前端闭环

**Files:**

- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/modules/auth/store.ts`
- Create: `frontend/src/modules/auth/LoginView.vue`
- Create: `frontend/src/modules/auth/AccessDeniedView.vue`
- Create: `frontend/src/modules/todos/TodoListView.vue`
- Create: `frontend/src/modules/todos/store.ts`
- Create: `frontend/src/modules/admin/UserAccessView.vue`
- Create: `frontend/src/modules/admin/ConfigurationListView.vue`
- Create: `frontend/src/modules/admin/AuditListView.vue`
- Create: `frontend/src/modules/admin/DocumentWorkbenchView.vue`
- Create: `frontend/src/modules/auth/store.spec.ts`
- Create: `frontend/src/modules/todos/TodoListView.spec.ts`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/app/App.vue`

- [ ] 先写路由守卫测试，未认证用户访问待办必须进入登录页，403不显示目标标题：

```typescript
it('does not reveal a protected object after access denial', async () => {
  api.get.mockRejectedValue({ status: 404, code: 'RESOURCE_NOT_FOUND' })
  await router.push('/documents/secret-id')
  expect(wrapper.text()).toContain('无权访问或内容不存在')
  expect(wrapper.text()).not.toContain('secret-id')
})
```

- [ ] API客户端统一携带会话Cookie和CSRF，解析标准错误结构；不得把敏感响应持久化到localStorage。
- [ ] 登录页生产只显示钉钉入口，开发设置下才显示开发登录；`/me`是前端权限摘要来源。
- [ ] 我的待办支持状态、截止时间和深链接；处理动作仍在系统目标页完成。
- [ ] 管理页面只覆盖用户角色、专项授权、配置发布、文件上传/版本和审计查询，不建设通用CRUD生成器。
- [ ] 每个按钮的隐藏只改善体验，后端测试仍是权限证据。

```powershell
Set-Location frontend
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
git commit -m "feat: add platform kernel user interface"
```

## 16. Task 1.12：平台内核E2E、CI和阶段退出证据

**Files:**

- Create: `tests/e2e/platform-kernel.spec.ts`
- Create: `backend/tests/acceptance/test_platform_kernel.py`
- Modify: `tests/e2e/playwright.config.ts`
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/check.ps1`
- Modify: `backend/openapi/schema.yaml`
- Modify: `frontend/src/api/generated/schema.d.ts`
- Modify: `docs/implementation/phase-1-test-matrix.md`
- Create: `docs/implementation/phase-1-checkpoint.md`
- Modify: `docs/development/01-phased-implementation-plan.md`

- [ ] 后端验收测试串联：活动用户登录→人工角色→默认拒绝/允许→受控文件→待办→审计→发件箱；另一路验证平台管理员不能读取高敏测试资源。
- [ ] Playwright使用开发适配器完成登录、查看待办、打开配置页和无权深链接；不依赖真实钉钉网络。
- [ ] CI的backend job启动Celery eager测试配置；E2E job增加MySQL/Redis、后端服务和测试文件目录。
- [ ] `scripts/check.ps1`增加迁移、平台内核验收和前端E2E，不允许跳过、xfail或SQLite替代。
- [ ] 生成OpenAPI和前端类型并验证无漂移。

```powershell
Set-Location backend
uv run python manage.py spectacular --file openapi/schema.yaml --validate --settings=config.settings.test
uv run pytest -q
Set-Location ..\frontend
npm.cmd run api:generate
Set-Location ..
scripts\check.cmd
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-trd.ps1
```

预期：全部退出码0；PLT-001至PLT-013及PLT-016在测试矩阵中均有实际证据。

- [ ] 在检查点记录提交哈希、数据库迁移、测试数量、CI链接、真实钉钉测试结果和已知限制。
- [ ] PLT-001和PLT-012在阶段1以假网关和契约测试作为通过证据；真实钉钉企业环境的一次登录与通知投递验收记为阶段6前完成的延后项，在测试矩阵中单列并标注“待阶段6真实环境验收”，不阻塞阶段1闭合。
- [ ] 将主计划阶段1标记完成并提交。

```powershell
git add .
git diff --cached --check
git commit -m "docs: record phase 1 completion evidence"
```

## 17. 阶段1明确不实现

- 提案、立案、立项、项目、产品档案和阶段门；
- 项目成员、任务R、专业确认人等真实项目身份表；
- 外部销售/运营数据接入、批次映射和人工覆盖；
- 备份执行器、恢复演练和完整运行看板；
- Office在线预览、转码、杀毒和跨权限哈希去重；
- 通用策略表达式、低代码表单平台、通用工作流引擎；
- 钉钉内审批和状态变更。

## 18. 执行风险与停线条件

| 风险 | 处理 |
|---|---|
| 自定义用户模型切换 | 只允许在无业务数据的阶段0数据库上重建；发现人工数据立即停止 |
| 钉钉接口或权限未开通 | 本地实现继续，阶段验收不得把假网关写成真实通过 |
| NAS测试挂载未提供 | 文件适配器和本地集成测试继续，生产NFS验收保持未通过 |
| 权限策略出现跨域临时判断 | 停止并补充资源身份接口，不在View中硬编码 |
| 审计与业务写入无法同事务 | 该命令不得上线，不接受异步补审计 |
| Celery/Redis故障导致业务回滚 | 修正为发件箱保留；通知失败不得影响权威业务事实 |
| 计划执行超过一个可审查PR | 按Task 1.1—1.4、1.5—1.7、1.8—1.10、1.11—1.12拆为四个连续PR |
