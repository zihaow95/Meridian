# 阶段1 Code Review 修复计划

日期：2026-07-08

目标：在进入阶段2前，把阶段1平台内核从“模型和服务雏形可用”修复到“真实可运行、可验收、可被业务模块安全复用”的状态。

适用仓库：`D:\Projects\Meridian`

对应基线：

- 阶段1计划：`docs/superpowers/plans/2026-07-06-phase-1-platform-kernel.md`
- 阶段1检查点：`docs/implementation/phase-1-checkpoint.md`
- 阶段1测试矩阵：`docs/implementation/phase-1-test-matrix.md`
- Review范围：阶段0完成点 `ce65270` 至当前阶段1 closeout 分支 HEAD

## 1. 总体判断

阶段1已经完成了大量底层模型、服务和测试雏形，包括身份、权限、审计、outbox、配置、文件、待办和前端入口。但 review 发现当前实现还不能作为阶段2业务开发的稳定平台内核，主要原因是：

1. 认证会话、可靠事件和管理授权存在真实运行风险；
2. 多个模块只有服务层能力，没有 API 和前端闭环；
3. E2E 与验收测试覆盖不足，不能证明阶段1整体链路可运行；
4. 文档状态与代码事实不一致，容易误导后续开发。

因此本计划把修复拆为三个 batch：

| Batch | 目标 | 性质 | 完成后状态 |
|---|---|---|---|
| Batch 1 | 修复平台内核阻断缺陷 | 必须先做 | 核心安全和可靠性规则可信 |
| Batch 2 | 补齐阶段1最小 API 与前端闭环 | 必须先于阶段2 | 平台内核可被真实操作 |
| Batch 3 | 补齐验收、CI 和文档一致性 | 阶段1重新验收 | 阶段1可关闭并进入阶段2 |

## 2. 全局规范

### 2.1 不扩大阶段范围

本计划只修阶段1平台内核，不引入阶段2业务对象。

禁止新增：

- 提案、立案、立项、项目、产品档案、阶段门模型；
- 项目成员、任务 R、交付物、专业确认等执行域模型；
- 外部销售数据接入、经营事实、风险信号；
- 备份执行器、恢复演练、完整运行看板；
- 通用工作流引擎、低代码表单平台、搜索集群。

### 2.2 权限规则

所有管理类 API 和关键写服务必须满足：

- 默认拒绝；
- 显式动作码；
- 服务层判权，不只依赖前端按钮隐藏；
- 写命令在事务内重新判权；
- 平台管理权与业务数据访问权分离；
- 无权访问业务对象时返回同一种 404 风格错误，不泄露对象存在性；
- 审计查询也必须判权和脱敏。

### 2.3 事务和可靠性规则

- MySQL 保存唯一业务事实；
- Redis 和 Celery 不保存唯一业务事实；
- 审计失败时关键业务写入必须回滚；
- outbox 事件必须可重试；
- 消费者幂等 receipt 只能在 handler 成功后生效，不能先写 receipt 再丢业务副作用；
- `select_for_update()` 必须在 `transaction.atomic()` 内执行；
- 文件对象、文档版本、配置版本、审计事件不可覆盖。

### 2.4 测试规则

每个修复任务必须先补失败测试，再改实现。测试必须表达业务意图：

- 权限同时测试允许和拒绝；
- 会话测试必须覆盖真实接口链路；
- 可靠事件测试必须覆盖失败后重试；
- 文件测试必须覆盖并发或重复完成；
- API 测试必须覆盖无权访问；
- E2E 必须覆盖真实前后端链路。

SQLite 不得替代 MySQL 关键行为。

### 2.5 提交和验收规则

建议三个 batch 分别形成可审查提交或 PR：

1. `fix: harden phase 1 platform kernel`
2. `feat: complete phase 1 minimal platform APIs`
3. `test: add phase 1 acceptance gates`

每个 batch 完成后必须记录：

- 修改文件；
- 新增或更新测试；
- 本轮实际运行命令；
- 未运行命令及原因；
- 剩余风险。

## 3. Batch 1：修复平台内核阻断缺陷

### 3.1 Batch 目标

让阶段1核心平台能力先变得可信：

- 登录后会话真实可用；
- 关键管理写服务不能被普通用户调用成功；
- 审计查询不能被任意登录用户读取；
- outbox 不会把事件标为已发布但实际未投递；
- outbox 消费失败不会因为 receipt 已写入而永久跳过；
- 文件上传完成逻辑在 MySQL 事务中正确锁定；
- 测试端点不会出现在生产 URL 中。

### 3.2 成功标准

Batch 1 完成后必须满足：

1. `POST /api/v1/auth/dev/login` 后立即 `GET /api/v1/me` 返回 200；
2. 无权限用户调用用户状态变更、管理复核、排障访问服务时失败且无审计成功记录；
3. 普通登录用户不能读取审计列表；
4. Celery outbox 默认执行路径不会无动作地吞事件；
5. handler 首次失败后，第二次消费仍可执行；
6. `complete_upload()` 中 `select_for_update()` 在事务内；
7. `git diff --check` 无输出；
8. 后端相关测试通过。

### 3.3 任务 1.1：修复 Django 登录会话

**问题：** `establish_session()` 直接写 session key，没有写 Django 需要的 `_auth_user_hash`，后续请求可能被 Django 刷掉会话。

**涉及文件：**

- Modify: `backend/apps/identity/services/authenticate_dingtalk.py`
- Modify: `backend/apps/identity/api/auth.py`
- Modify: `backend/tests/identity/test_authentication.py`

**实现规范：**

- 不手写 `_auth_user_id`、`_auth_user_backend`、`_auth_user_hash`；
- 使用 `django.contrib.auth.login(request, user, backend="django.contrib.auth.backends.ModelBackend")`；
- DingTalk callback 和 dev login 走同一会话建立函数；
- 测试必须覆盖真实登录后访问 `/api/v1/me`。

**测试要求：**

新增测试：

```python
@pytest.mark.django_db
def test_dev_login_session_can_access_me(client: Client, active_user) -> None:
    login_response = client.post(
        "/api/v1/auth/dev/login",
        data={"login_key": active_user.login_key},
        content_type="application/json",
    )
    assert login_response.status_code == 200

    me_response = client.get("/api/v1/me")
    assert me_response.status_code == 200
    assert me_response.json()["public_id"] == str(active_user.public_id)
```

运行：

```powershell
Set-Location backend
uv run pytest tests/identity/test_authentication.py -q
```

### 3.4 任务 1.2：关键管理服务补服务层授权

**问题：** 部分关键服务只校验状态，不校验操作者是否有权限。

**涉及文件：**

- Modify: `backend/apps/identity/services/change_user_status.py`
- Modify: `backend/apps/authorization/services/review_admin_change.py`
- Modify: `backend/apps/authorization/services/open_troubleshoot_access.py`
- Modify: `backend/apps/authorization/services/request_admin_change.py`
- Modify: `backend/tests/identity/test_user_status.py`
- Modify: `backend/tests/authorization/test_dual_control.py`
- Modify: `backend/tests/authorization/test_troubleshoot.py`

**动作码建议：**

| 场景 | 动作码 | 资源类型 |
|---|---|---|
| 修改用户状态 | `identity.user.status_change` | `identity.user` |
| 发起管理变更 | `authorization.admin_change.request` | `authorization.admin_change_request` |
| 审核管理变更 | `authorization.admin_change.review` | `authorization.admin_change_request` |
| 开启排障访问 | `authorization.troubleshoot.open` | `authorization.troubleshoot_access` |

**实现规范：**

- 每个服务在 `transaction.atomic()` 内重新调用 `authorize()`；
- 无权限时抛出稳定业务异常；
- 无权限失败不能写成功审计；
- 通过授权后必须写审计；
- 不能只在 API 层判权。

**测试要求：**

新增测试方向：

```python
@pytest.mark.django_db
def test_user_without_permission_cannot_change_another_user_status(
    active_user, another_active_user
) -> None:
    with pytest.raises(UserStatusChangeDenied):
        ChangeUserStatus(
            actor=active_user,
            target=another_active_user,
            status=UserStatus.DISABLED,
        ).execute()

    another_active_user.refresh_from_db()
    assert another_active_user.status == UserStatus.ACTIVE
```

```python
@pytest.mark.django_db
def test_reviewer_without_permission_cannot_approve_admin_change(
    change_request, another_active_user
) -> None:
    with pytest.raises(AdminChangeReviewDenied):
        ReviewAdminChange(actor=another_active_user, request=change_request).approve()

    change_request.refresh_from_db()
    assert change_request.status == AdminChangeStatus.PENDING
```

运行：

```powershell
Set-Location backend
uv run pytest tests/identity/test_user_status.py tests/authorization -q
```

### 3.5 任务 1.3：审计查询 API 接入权限和脱敏

**问题：** 当前审计 API 只要求登录，任意登录用户可读取审计摘要。

**涉及文件：**

- Modify: `backend/apps/audit/queries/events.py`
- Modify: `backend/apps/audit/api/admin.py`
- Modify: `backend/apps/authorization/api/grants.py`
- Modify: `backend/tests/audit/test_audit_api_permissions.py`

**实现规范：**

- 审计查询动作码使用 `audit.event.read`；
- 查询前按当前用户、组织、动作判权；
- 默认返回脱敏摘要；
- 不返回 `before_summary`、`after_summary` 原始内容；
- 后续如需要按资源过滤，只允许通过后端查询条件实现，不允许前端过滤。

**测试要求：**

新增测试：

```python
@pytest.mark.django_db
def test_authenticated_user_without_audit_permission_cannot_list_audit_events(
    client, active_user
) -> None:
    client.force_login(active_user)
    response = client.get("/api/v1/audit/events")
    assert response.status_code in {403, 404}
```

```python
@pytest.mark.django_db
def test_audit_reader_can_list_sanitized_audit_events(
    client, audit_reader_user, audit_event
) -> None:
    client.force_login(audit_reader_user)
    response = client.get("/api/v1/audit/events")
    assert response.status_code == 200
    row = response.json()[0]
    assert "before_summary" not in row
    assert "after_summary" not in row
```

运行：

```powershell
Set-Location backend
uv run pytest tests/audit -q
```

### 3.6 任务 1.4：修复 outbox 发布和消费可靠性

**问题：**

- Celery 默认 publisher 是空实现，会把事件标为 PUBLISHED；
- `consume_once()` 先写 receipt，再执行 handler，handler 失败后无法重试。

**涉及文件：**

- Modify: `backend/apps/platform/outbox/tasks.py`
- Modify: `backend/apps/platform/outbox/consumer.py`
- Modify: `backend/apps/platform/outbox/dispatcher.py`
- Modify: `backend/apps/notifications/consumers.py`
- Modify: `backend/tests/platform/test_outbox.py`
- Modify: `backend/tests/platform/test_consumer_idempotency.py`
- Modify: `backend/tests/notifications/test_todos.py`

**实现规范：**

- 阶段1不引入外部消息队列；
- 默认 Celery task 应把 outbox event 路由给本地注册消费者；
- 没有注册消费者的 event type 不得标记为 PUBLISHED，应保留 PENDING 或标记 FAILED，并记录错误码；
- `ConsumerReceipt` 必须在 handler 成功后写入；
- 如果 handler 和 receipt 需要同事务，则 handler 不得在事务外产生不可回滚副作用；
- 重复投递只能产生一次业务副作用。

**测试要求：**

新增测试：

```python
@pytest.mark.django_db(transaction=True)
def test_consumer_receipt_is_not_written_when_handler_fails(outbox_event) -> None:
    handler = FailingHandler()

    with pytest.raises(RuntimeError):
        consume_once(event=outbox_event, consumer_code="todo_projection", handler=handler)

    assert ConsumerReceipt.objects.filter(
        event=outbox_event,
        consumer_code="todo_projection",
    ).count() == 0
```

```python
@pytest.mark.django_db(transaction=True)
def test_unregistered_event_type_is_not_marked_published(outbox_event) -> None:
    outbox_event.event_type = "unknown.event"
    outbox_event.save(update_fields=["event_type", "updated_at"])

    dispatch_outbox_task(limit=10)

    outbox_event.refresh_from_db()
    assert outbox_event.status in {OutboxStatus.PENDING, OutboxStatus.FAILED}
    assert outbox_event.published_at is None
```

运行：

```powershell
Set-Location backend
uv run pytest tests/platform tests/notifications/test_todos.py -q
```

### 3.7 任务 1.5：修复文件上传事务锁

**问题：** `CompleteUpload.execute()` 在事务外执行 `select_for_update()`。

**涉及文件：**

- Modify: `backend/apps/documents/services/uploads.py`
- Modify: `backend/tests/documents/test_uploads.py`

**实现规范：**

- `UploadSession.objects.select_for_update()` 必须在 `transaction.atomic()` 内；
- 已完成 session 再次完成必须失败；
- 并发完成同一个 session 时最终只能有一个 CONTROLLED 版本；
- 文件移动失败不能产生 ACTIVE `FileObject` 或 CONTROLLED `DocumentVersion`。

**测试要求：**

新增测试：

```python
@pytest.mark.django_db(transaction=True)
def test_completed_upload_session_cannot_be_completed_twice(
    upload_session, file_storage, active_user
) -> None:
    complete_upload(upload_session.public_id, actor=active_user, storage=file_storage)

    with pytest.raises(UploadValidationFailed):
        complete_upload(upload_session.public_id, actor=active_user, storage=file_storage)

    assert DocumentVersion.objects.filter(status=VersionStatus.CONTROLLED).count() == 1
```

运行：

```powershell
Set-Location backend
uv run pytest tests/documents/test_uploads.py -q
```

### 3.8 任务 1.6：清理测试路由和格式问题

**涉及文件：**

- Modify: `backend/config/urls.py`
- Modify: `backend/tests/api/test_error_contract.py`
- Modify: `docs/implementation/phase-1-checkpoint.md`
- Modify: `tests/e2e/platform-kernel.spec.ts`

**实现规范：**

- `/api/v1/_test/hidden-resource` 只在测试设置下注册；
- OpenAPI 生成不应包含测试端点；
- 清理 `git diff --check` 报出的行尾空白。

运行：

```powershell
git diff --check
Set-Location backend
uv run pytest tests/api/test_error_contract.py -q
uv run python manage.py spectacular --file openapi/schema.yaml --validate --settings=config.settings.test
```

### 3.9 Batch 1 验收命令

```powershell
Set-Location backend
uv run ruff check .
uv run ruff format --check .
uv run mypy config apps
uv run python manage.py check --settings=config.settings.test
uv run python manage.py makemigrations --check --dry-run --settings=config.settings.test
uv run pytest tests/identity tests/authorization tests/audit tests/platform tests/documents -q
Set-Location ..
git diff --check
```

## 4. Batch 2：补齐阶段1最小 API 与前端闭环

### 4.1 Batch 目标

把阶段1从“服务层具备能力”补齐到“用户可以在系统中完成最小平台操作”。

最小闭环包括：

1. 登录；
2. 当前用户信息；
3. 我的待办；
4. 配置版本查看和发布；
5. 文件上传、完成、下载票据；
6. 审计查询；
7. 用户角色查看和角色分配入口；
8. 前端页面不再使用本地示例数据。

### 4.2 成功标准

Batch 2 完成后必须满足：

- OpenAPI 中出现待办、配置、文件、审计、角色相关路径；
- 前端类型由 OpenAPI 重新生成且无漂移；
- `TodoListView` 从后端读取当前用户待办；
- 配置、文件、审计、用户访问页面均调用真实 API；
- 生产构建不显示开发登录入口；
- 后端 API 权限测试覆盖允许和拒绝；
- 前端单元测试覆盖 API 成功、失败和空状态。

### 4.3 任务 2.1：建立 API 权限基类和动作码目录

**涉及文件：**

- Create: `backend/apps/authorization/actions.py`
- Create: `backend/apps/platform/api/permissions.py`
- Modify: `backend/apps/authorization/migrations/0003_seed_platform_actions.py`
- Modify: `backend/tests/authorization/test_action_catalog.py`

**实现规范：**

- 权限动作必须有稳定 action code；
- 基础动作目录通过数据迁移或确定性 seed 服务创建；
- API 权限类把 DRF request 转换为 `AuthorizationSubject`、`ResourceDescriptor` 和 `AuthorizationContext`；
- 未知动作默认拒绝。

**阶段1最小动作目录：**

| 动作码 | 用途 |
---|---|
| `identity.user.status_change` | 修改用户状态 |
| `authorization.role.read` | 查看角色目录 |
| `authorization.role.assign` | 分配角色 |
| `authorization.admin_change.request` | 发起管理变更 |
| `authorization.admin_change.review` | 审核管理变更 |
| `authorization.troubleshoot.open` | 开启排障访问 |
| `audit.event.read` | 查看审计事件 |
| `configuration.version.read` | 查看配置版本 |
| `configuration.version.publish` | 发布配置版本 |
| `document.version.upload` | 上传文件版本 |
| `document.version.download` | 下载文件版本 |
| `notification.todo.read` | 查看我的待办 |

**测试要求：**

```python
@pytest.mark.django_db
def test_platform_action_catalog_is_seeded_after_migration() -> None:
    assert PermissionAction.objects.filter(action_code="audit.event.read").exists()
    assert PermissionAction.objects.filter(action_code="notification.todo.read").exists()
```

### 4.4 任务 2.2：补齐待办 API

**涉及文件：**

- Create: `backend/apps/notifications/api/todos.py`
- Create: `backend/apps/notifications/api/urls.py`
- Modify: `backend/config/urls.py`
- Modify: `backend/tests/notifications/test_todo_api.py`

**接口范围：**

- `GET /api/v1/todos/my`
- 支持查询参数：`status=OPEN|COMPLETED|CANCELLED|EXPIRED`
- 返回字段：`public_id`、`title`、`status`、`due_at`、`deep_link`

**实现规范：**

- 只能返回当前用户自己的待办；
- 不返回无权目标对象标题；
- 深链只作为跳转，目标页面仍实时判权；
- 不在前端硬编码示例数据。

**测试要求：**

```python
@pytest.mark.django_db
def test_my_todos_returns_only_current_user_todos(client, active_user, another_active_user) -> None:
    client.force_login(active_user)
    create_todo_for(active_user, title="Mine")
    create_todo_for(another_active_user, title="Other")

    response = client.get("/api/v1/todos/my")

    assert response.status_code == 200
    titles = [row["title"] for row in response.json()]
    assert titles == ["Mine"]
```

### 4.5 任务 2.3：补齐配置 API

**涉及文件：**

- Create: `backend/apps/configuration/api/configurations.py`
- Create: `backend/apps/configuration/api/urls.py`
- Modify: `backend/config/urls.py`
- Modify: `backend/tests/configuration/test_configuration_api.py`

**接口范围：**

- `GET /api/v1/configurations/definitions`
- `GET /api/v1/configurations/definitions/{definition_code}/versions`
- `POST /api/v1/configurations/versions/{public_id}/publish`

**实现规范：**

- 读取需要 `configuration.version.read`；
- 发布需要 `configuration.version.publish`；
- 发布沿用现有服务，不在 view 中直接改状态；
- 失败返回统一错误结构；
- published 版本不可修改。

### 4.6 任务 2.4：补齐文件 API

**涉及文件：**

- Create: `backend/apps/documents/api/uploads.py`
- Create: `backend/apps/documents/api/documents.py`
- Create: `backend/apps/documents/api/urls.py`
- Modify: `backend/config/urls.py`
- Modify: `backend/tests/documents/test_document_api.py`

**接口范围：**

- `POST /api/v1/documents/uploads`
- `POST /api/v1/documents/uploads/{public_id}/complete`
- `GET /api/v1/documents/{document_public_id}/versions`
- `POST /api/v1/documents/versions/{version_public_id}/download-ticket`
- `GET /api/v1/documents/download/{token}`

**实现规范：**

- 文件写入必须使用 `UploadedFile.chunks()`；
- 文件类型和大小使用配置策略；
- 下载票据数据库只存 token hash；
- `GET /download/{token}` 返回 `X-Accel-Redirect`，不暴露 NAS 真实路径；
- 上传、下载、预览分别判权。

### 4.7 任务 2.5：补齐用户访问 API

**涉及文件：**

- Modify: `backend/apps/authorization/api/admin.py`
- Create: `backend/apps/authorization/api/assignments.py`
- Modify: `backend/config/urls.py`
- Modify: `backend/tests/authorization/test_admin_api.py`

**接口范围：**

- `GET /api/v1/authorization/roles`
- `GET /api/v1/authorization/users/{public_id}/assignments`
- `POST /api/v1/authorization/users/{public_id}/assignments`

**实现规范：**

- 角色目录读取需要 `authorization.role.read`；
- 分配角色必须调用 `AssignRole` 服务；
- 关键角色必须要求 approval reference；
- 不根据钉钉岗位自动授权。

### 4.8 任务 2.6：前端接入真实 API

**涉及文件：**

- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/generated/schema.d.ts`
- Modify: `frontend/src/modules/auth/LoginView.vue`
- Modify: `frontend/src/modules/auth/store.ts`
- Modify: `frontend/src/modules/todos/store.ts`
- Modify: `frontend/src/modules/todos/TodoListView.vue`
- Modify: `frontend/src/modules/admin/ConfigurationListView.vue`
- Modify: `frontend/src/modules/admin/DocumentWorkbenchView.vue`
- Modify: `frontend/src/modules/admin/AuditListView.vue`
- Modify: `frontend/src/modules/admin/UserAccessView.vue`
- Modify: `frontend/src/modules/**/*.spec.ts`
- Modify: `frontend/src/env.d.ts`

**实现规范：**

- `TodoListView` 调用 `GET /api/v1/todos/my`；
- 管理页面使用真实 API，不再显示“Phase 1 占位”；
- 生产模式不显示开发登录；
- API error 统一显示 code、message、trace_id；
- 不把敏感响应持久化到 localStorage；
- 按钮隐藏只优化体验，不能替代后端权限。

**环境变量建议：**

```typescript
const showDevLogin = import.meta.env.DEV && import.meta.env.VITE_ENABLE_DEV_LOGIN === 'true'
```

### 4.9 Batch 2 验收命令

```powershell
Set-Location backend
uv run pytest tests/notifications tests/configuration tests/documents tests/authorization tests/audit -q
uv run python manage.py spectacular --file openapi/schema.yaml --validate --settings=config.settings.test
Set-Location ..\frontend
npm.cmd run api:generate
npm.cmd run lint
npm.cmd run format:check
npm.cmd run typecheck
npm.cmd run test:unit -- --run
npm.cmd run build
Set-Location ..
git diff --exit-code -- backend/openapi/schema.yaml frontend/src/api/generated/schema.d.ts
```

## 5. Batch 3：补齐验收、CI 和文档一致性

### 5.1 Batch 目标

把阶段1重新变成可验收状态，并确保后续阶段不会基于错误文档继续开发。

### 5.2 成功标准

Batch 3 完成后必须满足：

- 存在后端平台内核验收测试；
- Playwright 覆盖真实登录、待办、配置页、无权深链；
- 本地 `scripts/check.cmd` 包含后端、前端、OpenAPI、E2E；
- CI E2E 启动后端、MySQL、Redis；
- `phase-1-test-matrix.md` 所有 PLT 状态与实际测试结果一致；
- `phase-1-checkpoint.md` 不再宣称未被证明的能力；
- README 当前状态准确。

### 5.3 任务 3.1：新增后端验收测试

**涉及文件：**

- Create: `backend/tests/acceptance/test_platform_kernel.py`
- Modify: `backend/tests/conftest.py`

**验收链路：**

1. 创建活动用户；
2. dev login 建立真实会话；
3. 分配角色；
4. 验证默认拒绝；
5. 创建并完成文件上传；
6. 创建待办；
7. 写审计；
8. 登记 outbox；
9. 消费 outbox；
10. 验证平台管理员不能读取高敏业务测试资源。

**测试要求：**

```python
@pytest.mark.django_db(transaction=True)
def test_platform_kernel_happy_path(client, platform_admin_user, active_user, file_storage) -> None:
    login_response = client.post(
        "/api/v1/auth/dev/login",
        data={"login_key": active_user.login_key},
        content_type="application/json",
    )
    assert login_response.status_code == 200

    me_response = client.get("/api/v1/me")
    assert me_response.status_code == 200

    todo_response = client.get("/api/v1/todos/my")
    assert todo_response.status_code == 200
```

### 5.4 任务 3.2：升级 Playwright E2E

**涉及文件：**

- Modify: `tests/e2e/playwright.config.ts`
- Modify: `tests/e2e/platform-kernel.spec.ts`
- Modify: `tests/e2e/package.json`
- Modify: `frontend/vite.config.ts`

**实现规范：**

- E2E 启动后端测试设置；
- E2E 使用 MySQL 和 Redis；
- 前端通过 Vite dev/proxy 或生产预览连接后端；
- 测试不依赖真实钉钉网络；
- 不允许只验证静态页面。

**E2E 场景：**

1. 未登录访问 `/todos` 跳转登录；
2. dev login 成功；
3. 进入 `/todos` 看到后端返回的待办；
4. 进入 `/admin/configurations` 看到配置列表或空状态；
5. 打开 `/documents/secret-id` 显示“无权访问或内容不存在”，不显示 `secret-id` 之外的敏感内容。

### 5.5 任务 3.3：更新本地质量门禁和 CI

**涉及文件：**

- Modify: `scripts/check.ps1`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`

**实现规范：**

- `scripts/check.ps1` 增加 E2E 步骤；
- CI 的 E2E job 必须启动 MySQL、Redis、后端服务和前端服务；
- CI 不访问真实钉钉；
- E2E 失败必须阻断 PR；
- README 说明完整质量门禁的前置条件。

### 5.6 任务 3.4：修正文档状态

**涉及文件：**

- Modify: `docs/implementation/phase-1-test-matrix.md`
- Modify: `docs/implementation/phase-1-checkpoint.md`
- Modify: `docs/development/01-phased-implementation-plan.md`
- Modify: `README.md`

**实现规范：**

- 测试矩阵中每条 PLT 的状态必须是以下之一：
  - `已通过：<测试文件或CI证据>`
  - `后置：阶段6真实钉钉验收`
  - `后置：阶段7部署/Nginx验收`
- 不得出现“已完成”与“待验证”并存；
- 检查点只能记录已经运行并通过的验证；
- README 当前状态必须反映 Django/Vue 正式工程已存在。

### 5.7 Batch 3 验收命令

```powershell
scripts\check.cmd
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-trd.ps1
git diff --check
git status --short
```

预期：

- `scripts\check.cmd` 退出码 0；
- TRD 校验通过；
- `git diff --check` 无输出；
- 只有本计划范围内文件发生变化。

## 6. 建议执行顺序

1. 先执行 Batch 1，修复阻断问题；
2. Batch 1 通过后做一次 code review；
3. 再执行 Batch 2，补齐最小 API 和前端闭环；
4. Batch 2 通过后做一次前后端联调检查；
5. 最后执行 Batch 3，补齐验收和文档；
6. Batch 3 通过后，重新评估阶段1是否可以关闭；
7. 阶段1重新关闭后再开始阶段2。

## 7. 停线条件

出现以下情况应停止继续开发并先修正：

- 关键写服务无法在事务内完成授权、业务变更、审计和 outbox；
- 审计查询无法实现后端权限过滤；
- outbox 无法证明失败可重试；
- 文件上传无法避免重复完成；
- E2E 只能通过 mock 页面而不能连接真实后端；
- 测试矩阵无法对应到真实测试文件；
- 为修阶段1问题而引入阶段2业务对象。

## 8. 阶段1重新关闭标准

阶段1只有在以下条件全部满足后才可以重新关闭：

1. Batch 1、Batch 2、Batch 3 全部完成；
2. 本地质量门禁通过；
3. CI 通过；
4. 测试矩阵状态一致；
5. 检查点只记录真实证据；
6. 真实钉钉验收和 Nginx 文件下载验收被明确标记为阶段6/阶段7后置项；
7. 没有引入阶段2业务模型；
8. code review 没有 Critical 或 Important 未处理问题。
