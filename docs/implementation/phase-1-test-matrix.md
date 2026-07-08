# 阶段1 平台内核 —— 测试矩阵

状态：已通过 remediation Batch 1–3 重新验收（2026-07-08）

日期：2026-07-08

对应计划：`docs/superpowers/plans/2026-07-06-phase-1-platform-kernel.md`

修复计划：`docs/implementation/phase-1-code-review-remediation-plan.md`

## PLT 需求追踪

| 需求 | 说明 | 自动化证据位置 | 状态 |
|---|---|---|---|
| PLT-001 | 钉钉认证、内部绑定和服务端会话 | `backend/tests/identity/test_authentication.py` | 已通过：`test_authentication.py` |
| PLT-002 | 用户状态、组织和历史有效区间 | `backend/tests/identity/test_models.py`, `test_user_status.py` | 已通过：`test_user_status.py` |
| PLT-003 | RBAC动作、ABAC上下文和默认拒绝算法 | `backend/tests/authorization/test_engine.py` | 已通过：`test_engine.py` |
| PLT-004 | 业务表项目身份和对象范围 | `backend/tests/authorization/test_engine.py` | 已通过：`test_engine.py` |
| PLT-005 | 字段、文件动作、导出和通知策略 | `backend/tests/authorization/test_query_filtering.py` | 已通过：`test_query_filtering.py` |
| PLT-006 | 关键角色人工分配 | `backend/tests/authorization/test_role_assignment.py`, `test_admin_api.py` | 已通过：`test_admin_api.py` |
| PLT-007 | 平台开关和管理变更复核请求 | `backend/tests/authorization/test_dual_control.py` | 已通过：`test_dual_control.py` |
| PLT-008 | 限时专项授权和排障访问 | `backend/tests/authorization/test_special_grants.py`, `test_troubleshoot.py` | 已通过：`test_troubleshoot.py` |
| PLT-009 | 通用配置版本和项目快照 | `backend/tests/configuration/` | 已通过：`test_configuration_api.py` |
| PLT-010 | 文档、不可变版本和NAS对象 | `backend/tests/documents/` | 已通过：`test_document_api.py` |
| PLT-011 | 权威待办及权限过滤通知 | `backend/tests/notifications/` | 已通过：`test_todo_api.py` |
| PLT-012 | 钉钉投递和系统深链接 | `backend/tests/notifications/test_dingtalk_delivery.py` | 后置：阶段6真实钉钉验收 |
| PLT-013 | 同事务追加审计 | `backend/tests/audit/test_transactional_audit.py` | 已通过：`test_transactional_audit.py` |
| PLT-014 | 适配器、同步运行、错误和重试 | — | 本阶段不实现，见阶段6 |
| PLT-015 | 备份运行和恢复验证记录 | — | 本阶段不实现，见阶段7 |
| PLT-016 | 组织字段和单组织边界 | `backend/tests/identity/test_models.py` | 已通过：`test_models.py` |

### 平台内核验收

- 后端验收链路：`backend/tests/acceptance/test_platform_kernel.py`
- E2E 真实前后端链路：`tests/e2e/platform-kernel.spec.ts`（CI `e2e` job）

### 延后验收说明

- **PLT-012**：阶段1以假网关和契约测试作为通过证据；真实钉钉企业环境的一次登录与通知投递验收延后至阶段6，不阻塞阶段1闭合。
- **文件 Nginx `X-Accel-Redirect`**：端到端验收延后至阶段7部署/Nginx验收。
