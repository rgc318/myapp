# 企业级用户与权限模块技术设计

## 1. 目标与边界

用户模块负责“谁可以进入系统、可以做什么、可以看到哪些数据、账号发生过什么变化”。模块不复制 Frappe 的身份与权限模型，而是在标准 `User`、`Role`、`Has Role`、`User Permission` 和 `Version` 之上提供适合 Web 管理端的领域服务、统一 API 与运营界面。

首期交付范围：

- 个人中心：身份信息、联系方式、语言时区、头像地址、简介、岗位与工作偏好。
- 个人安全：修改密码、查看最近登录和活跃信息。
- 安全中心：真实头像上传、Frappe/JWT 会话摘要、全设备注销、标准 Frappe 2FA 状态和 JWT OTP 挑战。
- 用户管理：分页查询、创建、编辑、启停、角色分配、用户详情和变更记录。
- 角色治理：角色目录、启停状态、用户数量和权限规则摘要。
- 数据范围：维护标准 Frappe `User Permission`，支持公司、仓库等任意合法 DocType 的数据授权。
- 权限边界：普通用户只维护本人资料；只有 `System Manager` 可以管理其他用户、角色和数据权限。

不重复实现 Frappe 已有的 DocPerm、OTP Secret 和 Session 数据模型。当前已经接入标准 Frappe 2FA 状态、JWT OTP 挑战、安全摘要、权限快照和全设备注销；OAuth/LDAP 配置、HR 员工档案及授权审批仍属于后续独立治理能力。

## 2. 领域模型

```text
User（身份与个人主档）
 ├─ Has Role -> Role（功能权限集合）
 ├─ User Permission（公司/仓库/客户等数据范围）
 ├─ DefaultValue（默认公司、默认仓库）
 ├─ Version（用户主档变更审计）
 └─ JWT / Session（认证会话）
```

核心原则：

- `User` 是账号唯一事实来源，邮箱账号不在 myapp 建影子表。
- `Role` 决定功能权限，页面不保存独立角色副本。
- `User Permission` 决定记录级数据范围，业务服务仍必须调用 Frappe 权限引擎。
- 前端 `access.ts` 只控制菜单和按钮可见性，不能替代后端鉴权。
- 用户停用后，JWT 鉴权钩子立即拒绝后续访问。

## 3. 服务与 API

个人接口：

- `get_current_user_profile_v1`
- `update_current_user_profile_v1`
- `change_current_user_password_v1`
- `upload_current_user_avatar_v1`
- `get_user_security_v1`
- `revoke_user_sessions_v1`

管理员接口：

- `list_users_v1`
- `get_user_management_overview_v1`
- `batch_set_users_enabled_v1`
- `get_user_detail_v1`
- `create_user_v1`
- `update_user_v1`
- `set_user_enabled_v1`
- `update_user_roles_v1`
- `list_roles_v1`
- `add_user_permission_v1`
- `delete_user_permission_v1`
- `get_user_permission_snapshot_v1`

所有管理员接口在服务层再次检查 `System Manager`，不能只依赖路由或按钮隐藏。创建与修改操作使用 Frappe Document API，从而保留标准校验、联系人同步、密码策略与版本记录。

## 4. 生命周期与保护规则

- 创建：邮箱唯一，默认 `System User`，角色必须存在、启用且不能包含自动角色。
- 启用：恢复登录资格，但不自动补角色或数据权限。
- 停用：禁止停用 `Administrator`、当前操作者和最后一个启用的 `System Manager`。
- 角色调整：禁止从最后一个启用的系统管理员移除 `System Manager`。
- 删除：首期不开放硬删除。账号属于审计主体，应通过停用退出生命周期。
- 批量启停：最多 100 个账号，先完成整批保护校验再写入，避免部分停用后才发现最后管理员被包含。
- 密码：本人修改必须提供旧密码并通过 Frappe 密码强度策略；成功后要求客户端重新登录。

## 5. Web 信息架构

```text
个人中心
 ├─ /account/center       身份、角色、数据范围和最近活动
 └─ /account/settings     个人资料、工作偏好和密码

系统管理（System Manager）
 └─ /administration
     ├─ /users            用户列表、创建和启停
     ├─ /users/:user      主档、角色、数据权限、审计
     └─ /roles            角色目录与使用情况
```

列表使用 `ProTable` 服务端分页；详情使用 `PageContainer + ProCard + Tabs + Descriptions`；角色与数据权限通过明确的保存动作提交，不在页面本地推断最终权限。

页面视觉遵循 Ant Design Pro 官方模式：

- 个人中心使用左侧身份卡、右侧指标和业务卡片，不把所有信息堆在一个描述列表中。
- 设置页使用独立导航和内容工作区，移动端自动切换为单列布局。
- 用户列表使用治理指标、服务端表格和批量操作栏。
- 用户详情使用状态头、指标卡和分域 Tabs。
- 角色目录展示角色使用量、权限规则和 DocType 覆盖摘要，但不在 Web 复制 DocPerm 编辑器。

## 6. 后续增强

- 当前会话中心已支持 Frappe Session / JWT refresh 会话摘要和全设备注销；后续可补单个 JWT refresh 会话的设备级吊销。
- 2FA 挑战已接入；可信设备、异常登录告警和安全事件报表尚未实现。
- 角色申请、审批、定期复核和临时授权到期。
- 组织架构、岗位、员工档案与代理授权。
- 当前权限快照覆盖核心 DocType 的角色权限；完整模拟器仍需合并菜单、DocPerm、User Permission 和指定记录判断。
- 高风险操作二次确认、双人复核和安全事件报表。
