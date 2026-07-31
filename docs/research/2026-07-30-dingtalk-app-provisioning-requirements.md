# Project Meridian 阶段六：钉钉双应用创建与交付要求

> 核对日期：2026-07-30  
> 证据范围：仅使用钉钉开放平台及钉钉官方开发者百科。未用博客、厂商集成指南或其他二手资料补齐缺口。  
> 用途：交给公司钉钉管理员创建应用并向 Meridian 开发侧交付联调条件。
> 当前状态：2026-07-30 已确认钉钉登录、组织同步和钉钉通知全部退出阶段六，本文保留为后续版本研究输入，不构成阶段六任务或 GO 条件。

## 1. 结论与管理员执行摘要

请在 Meridian 所属组织下创建两个仅供本组织使用的单组织应用：

1. `Meridian 身份认证应用`
2. `Meridian 业务通知应用`

请使用 **Meridian** 的正确拼写，不使用 `Meridain`。

官方新权限模型说明：应用开发阶段不再以“内部/三方”区分应用本体；仅分发给创建者组织使用的应用属于“企业内部应用”，也即单组织应用（Single-tenant Application）。这两个应用均不应上架应用市场或分发给其他组织。  
来源：[获取应用的 Access Token（新）](https://open-dingtalk.github.io/developerpedia/docs/develop/permission/single_to_multi/new_get_app_token/)

两套应用必须分别使用自己的凭据，不得互换：

| 应用 | 负责能力 | 明确不负责 |
| --- | --- | --- |
| Meridian 身份认证应用 | 钉钉 OAuth 登录、读取当前登录用户身份、组织/部门/人员只读同步 | 发送业务通知、修改钉钉通讯录 |
| Meridian 业务通知应用 | 以应用身份向指定员工发送工作通知，通知中的按钮跳转 Meridian HTTPS 深链接 | 登录、组织同步、钉钉内审批或状态迁移 |

### 1.1 已被后续范围决定取代的阶段内验收拆分

> 以下拆分曾于 2026-07-30 确认，随后被“阶段六全部延期钉钉集成、先完成内部业务试用”的较新决定取代，不再生效。

由于稳定的入站 HTTPS 联调地址暂未具备，阶段六按以下顺序拆分，但仍属于同一个阶段：

- **6A 开发与契约验证**：完成双应用创建、权限和凭据交付、真实应用 token、组织只读同步、用户身份绑定、真实工作通知发送，以及使用 Fake Gateway / 契约测试覆盖 OAuth 回调、权限拒绝和深链接；同时完成本阶段外部数据与迁移工作。6A 不依赖公网回调地址。
- **6B 真实入口联调**：稳定的公司测试 HTTPS 地址、内部 HTTPS 地址或经安全审批的临时隧道具备后，完成真实钉钉登录回调、桌面端和移动端深链接、停用用户、无权限访问及摘要防泄露验证。

完成 6A 只能记录为“等待外部联调条件”，不得宣布阶段六 GO；只有 6B 和阶段六其余退出门禁全部通过后，阶段六才可验收。

## 2. 创建与管理前置条件

- 创建或配置应用的操作者需要具备钉钉开发者后台的“应用开发子管理员”能力；主管理员可在 OA 管理后台授予。  
  来源：[获得开发者权限](https://opensource.dingtalk.com/developerpedia/docs/explore/portal/grant-admin/)
- 组织读取类应用权限需要管理员同意；权限应遵循最小化原则。官方区分“委托权限”和“应用权限”：登录用户个人资料适合委托访问，后台组织同步适合应用访问。  
  来源：[权限概述](https://opensource.dingtalk.com/developerpedia/docs/learn/permission/intro/overview/)
- 两套应用的可见/授权范围至少覆盖阶段六联调人员；生产是否扩展到全组织应在联调验收后单独确认。

## 3. 应用一：Meridian 身份认证应用

### 3.1 创建时需配置

- 应用名称：`Meridian 身份认证应用`
- 使用范围：仅本组织。
- “安全设置”中的重定向 URL：
  - 联调回调 URL：由 Meridian 部署后提供，必须是开发者后台登记的精确 URL；
  - 生产回调 URL：由生产域名确定后另行登记；
  - 不接受通配重定向，也不把临时公网隧道地址作为生产配置。
- 若后台要求为 H5/网页应用配置首页 URL，则由 Meridian 提供对应 HTTPS 地址。
- 通讯录授权范围：
  - 联调期先限定阶段六测试部门和测试人员；
  - 全量组织同步验收前再由管理员扩大到全组织。

官方 OAuth 文档要求重定向 URL 预先登记，并在回调中返回 `authCode` 和 `state`。  
来源：[浏览器内获取用户委托的访问凭证](https://opensource.dingtalk.com/developerpedia/docs/develop/permission/token/browser/get_user_app_token_browser/)

### 3.2 登录所需最小权限与配置

管理员需要确认以下两类 scope：

| 用途 | 官方已确认的 scope/权限 | 说明 |
| --- | --- | --- |
| 标识登录用户 | OAuth scope `openid` | 用于完成当前用户身份获取 |
| 同时标识用户选择的组织 | OAuth scope `corpid` | 登录请求建议使用 `openid corpid`；换取用户 token 时可返回所选 `corpId` |
| 读取当前用户基础通讯录信息 | 委托权限 `Contact.User.Read` | 仅在需要读取当前用户 ID、姓名、头像等基础资料时申请 |

不要默认申请 `Contact.User.mobile`。只有 Meridian 已确认手机号是必要身份匹配字段，且完成个人信息合规审查后，才追加该权限。  
来源：[浏览器内获取用户委托的访问凭证](https://opensource.dingtalk.com/developerpedia/docs/develop/permission/token/browser/get_user_app_token_browser/)

当前官方浏览器 OAuth 路线为：

1. 跳转 `https://login.dingtalk.com/oauth2/auth`，传入 `client_id`、已登记的 `redirect_uri`、`state`、`response_type=code`、`prompt=consent` 和 `scope=openid%20corpid`；
2. 回调取得 `authCode`，服务端校验 `state`；
3. `POST https://api.dingtalk.com/v1.0/oauth2/userAccessToken` 换取用户访问凭证；
4. 调用“获取用户通讯录个人信息”获取用户 ID 等登录身份信息。

来源：

- [浏览器内获取用户委托的访问凭证](https://opensource.dingtalk.com/developerpedia/docs/develop/permission/token/browser/get_user_app_token_browser/)
- [获取用户 token](https://open.dingtalk.com/document/isvapp/obtain-user-token)
- [获取用户通讯录个人信息](https://open.dingtalk.com/document/isvapp/dingtalk-retrieve-user-information)

### 3.3 组织同步所需最小能力

身份应用只做只读同步。请在开发者后台为下列官方 API 关联的权限申请授权：

| 同步能力 | 官方 API 页面 | 后台权限处理 |
| --- | --- | --- |
| 枚举下级部门 | [获取部门列表 V2](https://open.dingtalk.com/document/orgapp-server/obtain-the-department-list-v2) | 在页面查看“权限要求”，申请对应的部门读取权限 |
| 枚举部门人员 | [获取部门下人员列表](https://open.dingtalk.com/document/orgapp-server/obtains-the-list-of-people-under-a-department) | 申请对应的部门成员读取权限 |
| 读取部门用户完整信息 | [查询部门用户完整信息](https://open.dingtalk.com/document/orgapp-server/queries-the-complete-information-of-a-department-user) | 申请对应的用户详情读取权限 |
| 必要时由 unionId 换 userId | [根据 unionId 查询用户](https://open.dingtalk.com/document/orgapp-server/query-a-user-by-the-union-id) | 仅当实际登录响应需要该转换时申请关联权限 |

已确认的项目同步范围（2026-07-30）：

- 联调阶段只授权和同步测试部门及测试人员；
- 生产最终范围覆盖全组织全部部门和在职员工；
- 首期只同步内部用户标识所需的钉钉 userId、姓名、工号、主部门/兼任部门关系、岗位和在职状态；
- 不默认同步手机号、邮箱、头像等非必要个人信息；
- 钉钉部门、岗位或职级不得自动授予产品总监、经管会、经营监督人、系统管理员等关键业务角色，关键角色仍由 Meridian 按已批准名单人工配置并审计。

已确认采用“组织同步预建账号”模式：

- 身份同步任务在员工首次登录前创建或更新 Meridian 内部用户及有效 `IdentityBinding`；
- 身份唯一性以钉钉组织标识与钉钉 userId 的组合为准，工号只作为组织资料，不作为外部身份唯一键；
- 首次登录只认证已经存在且有效的绑定，不因 OAuth 成功即时创建内部用户；
- 未进入同步授权范围、绑定不存在或内部用户已停用时，登录默认拒绝。

已确认的停用传播要求：

- 员工在钉钉被标记为离职或停用后，Meridian 最迟在 15 分钟内禁止其继续登录和操作；
- 管理员可以触发一次立即组织同步，不必等待下一次计划任务；
- 同步确认停用后，内部用户进入停用状态并使对应身份绑定失效，但不得删除用户、历史业务记录、审计或既有责任履历；
- 已建立的会话在下一次请求时重新检查内部用户状态，不能一直有效到会话自然过期；
- 具体采用定时差异同步、全量对账或事件订阅，由阶段六实施计划结合官方接口能力确定，但必须用测试证明上述 15 分钟 SLA。

公开官方页面当前为动态页面，搜索快照未稳定暴露上述 API 在 2026-07-30 后台显示的**精确中文权限名和权限 code**。因此管理员不得按历史文档猜名称；应创建应用后逐个打开上表 API 页面，通过“权限要求/申请权限”跳入权限管理，并把最终权限清单截图交付开发侧。

明确不要申请：

- 创建、更新、删除部门或用户的通讯录写权限；
- `qyapi_manage_addresslist`（“通讯录数据管理权限”）。该权限属于敏感的通讯录管理能力，需全组织通讯录管理员主动授权；Meridian 的阶段六只读同步不需要它。  
  来源：[应用使用敏感权限](https://opensource.dingtalk.com/developerpedia/docs/develop/permission/high_grade_scope/)

## 4. 应用二：Meridian 业务通知应用

### 4.1 创建时需配置

- 应用名称：`Meridian 业务通知应用`
- 使用范围：仅本组织。
- 可见范围/消息接收范围：联调期至少覆盖所有测试收件人；生产范围待验收后确认。
- 若后台要求配置应用首页 URL，使用 Meridian 的 HTTPS 入口；通知内业务按钮使用 Meridian 生成的受控 HTTPS 深链接。

### 4.2 最小权限

仅申请官方“发送工作通知”接口所关联的应用权限：

- [异步发送企业会话消息（工作通知）](https://open.dingtalk.com/document/orgapp-server/asynchronous-sending-of-enterprise-session-messages)

已确认的阶段六通知范围（2026-07-30）：

- 只交付企业应用工作通知 `WORK_NOTICE` 的基础发送、失败记录、有限重试和系统深链接；
- 通知只用于提醒和引导用户回到 Meridian，不能在钉钉内确认、审批或迁移业务状态；
- 机器人单聊、群机器人、普通互动卡片、创建并投放卡片以及卡片内操作按钮均不属于阶段六，进入后续开发范围；
- 阶段六不为这些后续能力申请 robot-code、卡片模板或额外机器人/互动卡片权限。

已确认通知不做无差别外发：

- 站内通知仍是完整通知记录，钉钉只投递需要本人行动或及时关注的子集；
- 首期钉钉候选范围为需要本人处理的系统待办、到期/超期提醒和关键处理失败；
- 普通状态变化默认只保留站内，不自动投递钉钉；
- 每条通知必须携带稳定的通知类别、通知等级和模板版本；
- 是否投递钉钉、投递时机和重试策略由统一发布的通知策略按类别与等级决定，业务模块不得各自写死渠道规则；
- 阶段六先采用以下二维模型，后续调整必须通过受控配置版本演进，不混用类别与等级：
  - 通知类别：`ACTION_REQUIRED`（需要本人处理）、`DEADLINE`（即将到期或已经超期）、`BUSINESS_ALERT`（经营、质量或业务风险）、`PROCESS_RESULT`（关键决策或流程结果）、`SYSTEM_FAILURE`（集成、迁移或后台处理失败）、`INFORMATION`（普通信息和状态变化）；
  - 通知等级：`URGENT`（需要立即关注）、`IMPORTANT`（需要当日关注）、`NORMAL`（普通信息）；
  - `URGENT` 默认允许钉钉发送，`IMPORTANT` 按类别配置，`NORMAL` 默认仅站内；最终渠道矩阵仍需单独确认。
- 分类与等级必须配置化：
  - 版本化通知模板固定通知类别并提供默认等级；
  - 统一通知策略使用受控的确定性条件配置等级升级、渠道、投递时机和重试，不允许保存或执行任意 Python、SQL 或用户脚本；
  - 通知类别、通知等级及其排序作为受控配置目录维护；可以新增或停用代码，但已使用的代码不得改义或物理删除；
  - 已发布模板和策略不可覆盖，调整时发布新版本；历史通知保留当时的模板版本、策略版本、类别和等级；
  - 业务调用方只提交事件、对象、接收人及规则计算所需事实，不能临时任意指定类别、等级或钉钉渠道。
- 通知配置沿用现有平台配置治理：
  - 由系统管理员使用既有 `configuration.edit`、`configuration.validate` 和 `configuration.publish` 能力维护，不新增通知管理员角色；
  - 启用超级管理员双人复核时，通知模板、分类目录、等级目录和通知策略发布必须由另一名管理员复核，编辑人不得复核自己的变更；
  - 系统管理员可以维护结构、模板占位符和渠道规则，但不能借配置权限读取通知关联对象的敏感业务值；
  - 配置编辑、校验、复核、发布和停用均记录审计，发布失败保持上一已发布版本有效。

阶段六首个通知策略版本采用以下默认渠道矩阵：

| 通知类别 | `URGENT` | `IMPORTANT` | `NORMAL` |
| --- | --- | --- | --- |
| `ACTION_REQUIRED` | 站内 + 钉钉，立即投递 | 站内 + 钉钉，立即投递 | 仅站内 |
| `DEADLINE` | 站内 + 钉钉，立即投递 | 站内 + 钉钉，立即投递 | 仅站内 |
| `SYSTEM_FAILURE` | 站内 + 钉钉，立即投递 | 站内 + 钉钉，立即投递 | 仅站内 |
| `BUSINESS_ALERT` | 仅站内 | 仅站内 | 仅站内 |
| `PROCESS_RESULT` | 仅站内 | 仅站内 | 仅站内 |
| `INFORMATION` | 仅站内 | 仅站内 | 仅站内 |

该矩阵是可调整的初始配置，不是代码常量；后续启用其他类别的钉钉投递时必须发布新策略版本，不能改写历史版本。

阶段六钉钉通知采用最小披露：

- 消息只包含配置化标题、面向当前接收人的权限过滤后最小摘要、到期时间或发生时间，以及“查看详情”的受控 Meridian HTTPS 深链接；
- 不在钉钉消息中包含配方、经营指标值、文件名、文件内容、审批或决策正文等敏感业务详情；
- 摘要按接收人和发送时权限生成，不能复用其他接收人的正文；无法确认摘要安全时默认不投递钉钉；
- 钉钉历史消息可能在 Meridian 权限撤销后继续存在，因此敏感详情只能在 Meridian 内实时判权后展示；
- 点击深链接后重新执行身份认证和对象级权限校验；无权访问时不得泄露对象标题、摘要、文件名或其他存在性信息。

阶段六首个通知策略版本采用以下默认重试配置：

- 钉钉投递总计最多尝试 4 次：首次立即执行，失败后分别在 1 分钟、5 分钟和 30 分钟重试；
- 只对超时、连接错误、明确限流和服务端临时错误进行自动重试；
- 身份未绑定、权限拒绝、模板非法、配置缺失等永久错误不自动重试；
- 重试耗尽后保留已经成功创建的站内通知，将钉钉投递标记为失败，并在管理看板生成系统管理员可见告警；
- 每次重试复用原通知、投递记录和幂等键，不重复生成业务通知或待办；
- 尝试次数、间隔和可重试错误分类属于版本化通知策略配置，后续调整发布新版本。

不要申请：

- OAuth 登录或个人通讯录委托权限；
- 部门、人员等通讯录读取权限；
- 通讯录写权限；
- 自定义群机器人、互动卡片、钉钉待办或审批权限。

当前公开官方动态页面未稳定暴露该接口在开发者后台的精确中文权限名和 code。创建后必须从上述官方 API 页面进入“权限要求/申请权限”，完成授权，并把后台实际名称、code 和审批状态截图交付开发侧。

通知应用必须交付 `AgentId`，因为工作通知以具体企业应用身份发送。接收人的钉钉 `userId` 由身份应用同步并在 Meridian 内完成绑定；通知应用不通过额外通讯录权限临时查询收件人。

## 5. 凭据、标识与交付方式

官方说明：创建应用后，可在“凭证与基础信息”看到 `ClientID` 和 `ClientSecret`；`ClientSecret` 是必须保密的应用凭证。  
来源：

- [权限术语：ClientID/ClientSecret](https://opensource.dingtalk.com/developerpedia/docs/learn/permission/intro/permission-glossary/)
- [获取应用的 Access Token（新）](https://open-dingtalk.github.io/developerpedia/docs/develop/permission/single_to_multi/new_get_app_token/)

管理员需向 Meridian 开发侧交付：

| 信息 | 身份应用 | 通知应用 | 交付要求 |
| --- | --- | --- | --- |
| Client ID | 必须 | 必须 | 可进入受控配置；不要硬编码 |
| Client Secret | 必须 | 必须 | 只进入密钥管理或部署环境变量；不得写入仓库、普通文档、工单截图或聊天 |
| AgentId | 后台若生成则交付 | 必须 | 记录其所属应用，避免混用 |
| CorpId | 两应用共用组织信息 | 两应用共用组织信息 | 由组织管理员确认 |
| 回调 URL 清单 | 必须 | 通常不需要 OAuth 回调 | 区分联调与生产 |
| 权限清单截图 | 必须 | 必须 | 包含权限实际名称、code、审批状态、授权范围 |
| 应用可见范围截图 | 必须 | 必须 | 证明覆盖测试人员 |

历史文档常把凭据称为 `AppKey/AppSecret`，当前官方新权限文档使用 `ClientID/ClientSecret`。开发侧配置应以当前后台实际字段为准，并在交付表中记录旧名映射，不能再创建第三套凭据。

## 6. Access Token 与新旧 API 宿主边界

官方当前推荐的应用凭证模式为：

```http
POST https://api.dingtalk.com/v1.0/oauth2/{corpId}/token
Content-Type: application/json

{
  "client_id": "...",
  "client_secret": "...",
  "grant_type": "client_credentials"
}
```

响应含 `access_token` 和 `expires_in`，官方示例有效期为 7200 秒。  
来源：[获取应用的 Access Token（新）](https://open-dingtalk.github.io/developerpedia/docs/develop/permission/single_to_multi/new_get_app_token/)

同时，钉钉官方仍保留：

- [获取企业内部应用 accessToken（旧路线）](https://open.dingtalk.com/document/orgapp-server/obtain-orgapp-token)
- 多个组织目录和工作通知的 `oapi.dingtalk.com/topapi/...` 风格接口页。

因此阶段六不得做“把所有 `oapi.dingtalk.com` 全部替换成 `api.dingtalk.com`”的假设。实现前应按每个官方 API 页面/API Explorer 核对：

1. host；
2. HTTP 方法与路径；
3. token 位于 header 还是 query；
4. 对应权限；
5. 限流和批量上限；
6. 新 App-Only Token 是否可用于所选的 `topapi` 接口。

两套真实应用创建后分别做最小冒烟调用，再冻结 Meridian 的接口契约。

## 7. 阶段六联调测试资料

请管理员同时准备：

- 一个可操作两套应用的开发子管理员；
- 至少 2 级测试部门结构；
- 至少 3 个身份测试账号：
  - 普通在职员工；
  - 管理员或跨/多部门员工；
  - 可用于验证停用、离职或撤销绑定的测试账号；
- 至少 2 个处于通知应用可见范围内、可接收工作通知的测试用户；
- 一条由 Meridian 提供的 HTTPS 联调深链接；
- 身份应用联调回调 URL；
- 两套应用的凭据、AgentId、权限和可见范围交付表。

## 8. 创建应用后必须回填的待确认项

以下项目在创建前不能从公开官方页面可靠确认，必须用真实后台和真实调用结果回填，不能凭历史资料猜测：

- 组织目录各 API 和工作通知 API 在当前后台显示的精确权限中文名与 code；
- 每项权限的审批状态、通讯录授权范围、应用可见范围；
- 身份应用是否生成 AgentId，以及本项目登录模式下是否实际需要它；
- 新 App-Only Token 是否可直接调用最终选定的 `oapi/topapi` 接口；
- 工作通知单批收件人数、调用频率、限流错误码等实时配额；
- 测试环境与生产环境允许登记的回调 URL 数量和变更流程；
- 停用/离职数据能否通过当前只读授权稳定获得，还是需要额外事件订阅或补充接口。

## 9. 管理员完成标准

只有同时满足以下条件，才算“钉钉应用已准备好”，而不只是“后台已创建”：

- 两个名称正确、职责分离的单组织应用已创建；
- 两套 Client ID/Client Secret 和通知应用 AgentId 已通过安全方式交付；
- 身份应用 OAuth 回调已登记；
- 身份应用只读通讯录权限、通知应用工作通知权限均已实际授权；
- 权限和范围截图已交付；
- 测试用户均在对应授权/可见范围内；
- 开发侧能以两个应用分别取得 token；
- 至少一次登录身份获取、一次组织读取、一次工作通知发送冒烟调用成功。

最后三项是联调验收，需要开发侧配合；在真实应用、权限和测试账号未就绪前，阶段六不能判定 GO。
