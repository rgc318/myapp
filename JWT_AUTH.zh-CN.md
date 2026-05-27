# JWT Token 认证接入说明

本文档说明 `myapp` 如何在不破坏 Frappe 原有 Cookie / Session 与 API Key 认证的前提下，增加适合移动端和前后端分离 Web 的 JWT Bearer Token 认证。

## 设计原则

- 不逐个修改业务接口，统一接入 Frappe 全局 `auth_hooks`
- 请求没有 `Authorization: Bearer ...` 时，不干扰原有 Session、Cookie、API Key 认证
- 请求带 Bearer JWT 时，验证通过后执行 `frappe.set_user(payload.subject)`
- Bearer JWT 无效、过期、已注销或类型错误时，直接返回认证失败，不降级为 Guest
- JWT 的签发、解码、刷新、注销复用独立包 `rgc-backend-kit`
- Refresh Token 与已注销 Access Token 通过 Frappe cache / Redis 保存，支持多进程共享状态

## 运行依赖

当前 JWT 能力依赖已经抽出的后端公共包：

```text
rgc-backend-kit>=0.1.1,<0.2.0
```

该依赖已经声明在 `apps/myapp/pyproject.toml`。`PyJWT` 的具体版本由 Frappe 当前环境约束管理，`myapp` 不单独固定小版本；`rgc-backend-kit` 只声明较宽的 PyJWT 兼容范围，因此可以跟随不同 Frappe 16 版本使用 `PyJWT 2.10.x` 或 `2.12.x`。

本地 Docker Compose 启动时会执行 `pip install -e apps/myapp` 自动安装；staging 镜像构建时也会在镜像内执行同样的 app 安装步骤。因此正常开发、重启 compose、构建 staging 镜像都不需要再手动安装 `rgc-backend-kit`。

不要再依赖 `/tmp/rgc-backend-kit` 或宿主机临时路径；如果发现容器里 `rgc_backend_kit.__file__` 指向 `/tmp/rgc-backend-kit`，说明当前环境仍残留旧的 editable 安装，需要重新执行 `pip install -e apps/myapp` 或重建 bench env。

## Frappe 配置

至少需要配置 JWT 密钥：

```bash
bench --site <site> set-config myapp_jwt_secret "<long-random-secret>"
```

可选配置：

```bash
bench --site <site> set-config myapp_jwt_issuer "myapp"
bench --site <site> set-config myapp_jwt_audience "mobile"
bench --site <site> set-config myapp_jwt_access_token_minutes 60
bench --site <site> set-config myapp_jwt_refresh_token_days 7
bench --site <site> set-config myapp_jwt_remember_me_days 14
bench --site <site> set-config myapp_jwt_leeway_seconds 0
```

默认缓存 key 前缀：

- Refresh Token：`myapp:jwt:refresh:<user>:<jti>`
- 已注销 Access Token：`myapp:jwt:revoked:<jti>`

## 已接入的全局鉴权

`myapp/hooks.py` 已启用：

```python
auth_hooks = [
    "myapp.auth.jwt_auth.validate",
]
```

Frappe 请求鉴权顺序仍保持原机制：OAuth / API Key 先处理，然后执行 `auth_hooks`。因此原有 Cookie / Session 与 `Authorization: token api_key:api_secret` 继续可用。

### 本轮修复的问题

本轮企业级验收前发现两个 JWT 集成边界问题：

- Bearer Token 鉴权通过后会调用 `frappe.set_user(payload.subject)`。在 Frappe 请求生命周期中，该调用会重建部分本地上下文，导致 `frappe.local.form_dict` 中的 JSON 请求参数丢失。表现为使用 Bearer Token 调业务接口时，服务端已经识别用户，但业务方法收到的参数为空或缺少必填参数。
- `refresh_v1` 遇到 refresh token 复用、已删除或无效时，底层 `rgc-backend-kit` 会抛出 `InvalidTokenError` / `RefreshTokenReuseError`。如果不在 `myapp` 集成层映射，该异常会被 HTTP 层表现为 `500`，不符合认证失败语义。

已完成的修复：

- `myapp.auth.jwt_auth.validate` 在调用 `frappe.set_user` 前保存 `frappe.local.form_dict`，调用后恢复，确保 Bearer Token 与 Session / API Key 一样不会破坏业务接口参数。
- `myapp.auth.token_api.refresh_v1` 将底层无效 token 异常统一映射为 `frappe.AuthenticationError`，HTTP 层返回 `401`，避免把客户端 token 复用或过期问题暴露为服务端错误。

修复后的安全语义：

- 有效 Bearer Token：正常设置 `frappe.session.user`，业务接口可读取原始请求参数。
- 无效、过期、已注销 Access Token：返回认证失败，不降级为 Guest。
- refresh token 轮换后旧 token 再次使用：返回认证失败。
- logout 删除 refresh token 后再次刷新：返回认证失败。
- 普通 Session 登录不会隐式下发 JWT Cookie；JWT 只通过显式 Token API 签发。

## Token API

### 登录签发 Token

接口：

```text
POST /api/method/myapp.auth.token_api.login_v1
```

请求：

```json
{
  "username": "user@example.com",
  "password": "password",
  "remember_me": 0
}
```

也兼容 Frappe 登录字段：

```json
{
  "usr": "user@example.com",
  "pwd": "password"
}
```

用户名解析遵循 Frappe 当前登录策略：默认支持 `User.name` / 邮箱；如果需要用 `User.username` 登录，需要在系统设置中启用用户名登录。

响应核心字段：

```json
{
  "ok": true,
  "code": "JWT_TOKEN_ISSUED",
  "data": {
    "access_token": "...",
    "refresh_token": "...",
    "token_type": "bearer",
    "expires_in": 3600,
    "refresh_expires_in": 604800,
    "user": {
      "user": "user@example.com",
      "roles": ["System Manager"],
      "full_name": "User Name"
    }
  }
}
```

### 携带 Access Token 调业务接口

```bash
curl -X POST "http://localhost:8080/api/method/myapp.api.gateway.search_products_v1" \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"query": "SKU"}'
```

业务服务中继续通过 `frappe.session.user` 获取当前用户，不需要修改每个接口。

### 刷新 Token

接口：

```text
POST /api/method/myapp.auth.token_api.refresh_v1
```

请求：

```json
{
  "refresh_token": "<refresh_token>"
}
```

刷新采用轮换策略：新的 refresh token 签发后，旧 refresh token 会从 Redis/cache 删除，旧 token 再次使用会失败。

### 注销 Token

接口：

```text
POST /api/method/myapp.auth.token_api.logout_v1
```

请求头：

```text
Authorization: Bearer <access_token>
```

可选请求体：

```json
{
  "refresh_token": "<refresh_token>"
}
```

注销会把 access token 的 `jti` 加入 Redis/cache 黑名单直到原本过期时间，并删除传入的 refresh token。

### 获取当前用户

接口：

```text
GET/POST /api/method/myapp.auth.token_api.me_v1
```

需要携带 Session、API Key 或 Bearer Token 中任意一种有效认证。

## HTTP 测试

`.env.http-test` 支持直接使用 JWT：

```env
MYAPP_HTTP_BASE_URL=http://localhost:8080
MYAPP_HTTP_BEARER_TOKEN=<access_token>
```

然后运行：

```bash
python3 apps/myapp/myapp/tests/http/test_gateway_http.py
```

JWT 生命周期回归测试：

```bash
MYAPP_HTTP_ENV_FILE=apps/myapp/.env.http-test \
python3 -m unittest apps.myapp.myapp.tests.http.test_jwt_token_http
```

HTTP 测试鉴权优先级：

1. `MYAPP_HTTP_BEARER_TOKEN`
2. `MYAPP_HTTP_API_KEY` + `MYAPP_HTTP_API_SECRET`
3. `MYAPP_HTTP_USERNAME` + `MYAPP_HTTP_PASSWORD`

## 当前验证结果

已在 backend 容器和本地真实 HTTP 站点中完成：

- `myapp.auth.jwt_auth` 和 `myapp.auth.token_api` 单元测试通过
- 使用真实 `rgc-backend-kit` 包完成 access / refresh 签发
- access token 解码通过
- refresh token 解码通过
- refresh token 轮换后旧 refresh token 被拒绝
- access token 注销后再次解码被拒绝
- Bearer Token 调 `myapp.api.gateway.search_product_v2` 时请求参数不丢失
- `login_v1 -> me_v1 -> refresh_v1 -> logout_v1` 生命周期 HTTP 回归通过
- 旧 refresh token 复用返回 `401 AuthenticationError`，不再返回 `500`
- logout 后 access token 被拒绝
- logout 删除 refresh token 后再次刷新被拒绝
- 无效 Bearer Token 被拒绝
- 普通 Frappe Session 登录不会生成 JWT Cookie

本轮执行过的关键验证命令：

```bash
docker exec frappe_docker-backend-1 bash -lc '
  cd /home/frappe/frappe-bench &&
  ./env/bin/python -m unittest \
    myapp.tests.unit.test_token_api \
    myapp.tests.unit.test_jwt_auth \
    myapp.tests.unit.test_idempotency
'

MYAPP_HTTP_ENV_FILE=apps/myapp/.env.http-test \
MYAPP_HTTP_TIMEOUT=60 \
python3 -m unittest apps.myapp.myapp.tests.http.test_jwt_token_http
```

最近一次验证结果：

- JWT / token / idempotency 相关单元测试：`Ran 17 tests ... OK`
- JWT 生命周期 HTTP 测试：`Ran 3 tests ... OK`
- JWT 生命周期 HTTP 测试 + 3 个核心并发幂等场景综合回归：`Ran 6 tests ... OK`

已使用 `apps/myapp/.env.http-test` 中配置的测试账号完成真实站点上下文验证。为避免泄露凭据，文档不记录明文密码。
