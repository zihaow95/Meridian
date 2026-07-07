# 阶段1 平台内核 —— 测试矩阵

状态：执行中

日期：2026-07-07

对应计划：`docs/superpowers/plans/2026-07-06-phase-1-platform-kernel.md`

PR 拆分：

| PR | 任务范围 | 分支 |
|---|---|---|
| PR1 | Task 1.0–1.4（契约、身份、认证、RBAC/ABAC） | `codex/phase-1-pr1-auth-kernel` |
| PR2 | Task 1.5–1.7（审计、双人复核/专项授权、发件箱） | `codex/phase-1-pr2-audit-outbox` |
| PR3 | Task 1.8–1.10（配置、文件、待办/通知） | `codex/phase-1-pr3-config-files-todos` |
| PR4 | Task 1.11–1.12（前端闭环、E2E、阶段退出） | `codex/phase-1-pr4-frontend-e2e` |

## PLT 需求追踪

| 需求 | 说明 | 自动化证据位置 | 状态 |
|---|---|---|---|
| PLT-001 | 钉钉认证、内部绑定和服务端会话 | `backend/tests/identity/test_authentication.py` | PR1 已实现，待 MySQL 验证 |
| PLT-002 | 用户状态、组织和历史有效区间 | `backend/tests/identity/test_models.py`, `test_user_status.py` | PR1 已实现，待 MySQL 验证 |
| PLT-003 | RBAC动作、ABAC上下文和默认拒绝算法 | `backend/tests/authorization/test_engine.py` | PR1 已实现，待 MySQL 验证 |
| PLT-004 | 业务表项目身份和对象范围 | `backend/tests/authorization/test_engine.py`（ObjectIdentityProvider 扩展点） | PR1 已实现，待 MySQL 验证 |
| PLT-005 | 字段、文件动作、导出和通知策略 | `backend/tests/authorization/test_query_filtering.py` | PR1 已实现，待 MySQL 验证 |
| PLT-006 | 关键角色人工分配 | `backend/tests/authorization/test_role_assignment.py` | PR1 已实现，待 MySQL 验证 |
| PLT-007 | 平台开关和管理变更复核请求 | `backend/tests/authorization/test_dual_control.py` | 未实现 |
| PLT-008 | 限时专项授权和排障访问 | `backend/tests/authorization/test_special_grants.py`, `test_troubleshoot.py` | 未实现 |
| PLT-009 | 通用配置版本和项目快照 | `backend/tests/configuration/` | 未实现 |
| PLT-010 | 文档、不可变版本和NAS对象 | `backend/tests/documents/` | 未实现 |
| PLT-011 | 权威待办及权限过滤通知 | `backend/tests/notifications/` | 未实现 |
| PLT-012 | 钉钉投递和系统深链接 | `backend/tests/notifications/test_dingtalk_delivery.py` | 未实现 |
| PLT-013 | 同事务追加审计 | `backend/tests/audit/test_transactional_audit.py` | 未实现 |
| PLT-014 | 适配器、同步运行、错误和重试 | — | 本阶段不实现，见阶段6 |
| PLT-015 | 备份运行和恢复验证记录 | — | 本阶段不实现，见阶段7 |
| PLT-016 | 组织字段和单组织边界 | `backend/tests/identity/test_models.py` | PR1 已实现，待 MySQL 验证 |

### 延后验收说明

- **PLT-001、PLT-012**：阶段1以假网关和契约测试作为通过证据；真实钉钉企业环境的一次登录与通知投递验收延后至阶段6，不阻塞阶段1闭合。
