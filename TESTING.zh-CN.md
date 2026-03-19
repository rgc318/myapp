# 测试说明

更新时间：2026-03-17

## 1. 测试原则

当前项目以 VS Code devcontainer / Docker 中运行的 ERPNext 环境作为开发与验收基准。

对 `myapp.api.gateway.*` 这类对外接口，优先使用宿主机通过 HTTP 访问 `http://localhost:8080` 的方式测试，不以 WSL 宿主机直接导入 Frappe 服务层作为主验收方式。

推荐原因：

- 更贴近前端与实际集成调用路径
- 能覆盖鉴权、权限、路由、包装器和响应结构
- 更容易发现 devcontainer 环境、站点权限、真实主数据导致的问题

## 2. 测试文件划分

当前测试主要分为两层：

- `myapp/tests/http/`
  用于 HTTP 冒烟、链路、幂等、并发和接口结构验证
- `myapp/tests/unit/`
  用于服务层和工具函数单元测试

当前重点 HTTP 文件：

- [test_gateway_http.py](/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/tests/http/test_gateway_http.py)
  覆盖既有销售与采购主链路
- [test_gateway_v2_http.py](/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/tests/http/test_gateway_v2_http.py)
  覆盖商品工作台与销售状态聚合相关 v2 能力

结果文件：

- [http-test-results.json](/home/rgc318/python-project/frappe_docker/apps/myapp/http-test-results.json)

环境变量示例：

- [.env.http-test.example](/home/rgc318/python-project/frappe_docker/apps/myapp/.env.http-test.example)

## 3. 环境准备

1. 确保 devcontainer / Docker 中的 ERPNext 正在运行。
2. 复制 `.env.http-test.example` 为 `.env.http-test`。
3. 配置以下内容：
   - `MYAPP_HTTP_BASE_URL=http://localhost:8080`
   - 测试账号密码或 API Token
4. 宿主机执行测试时使用 `python3`，不要默认使用 `python`。

补充说明：

- 当前约定使用 `http://localhost:8080`，不要随意改成 `127.0.0.1`
- 测试默认会打印响应，并写入 `http-test-results.json`
- 可通过 `MYAPP_HTTP_PRINT_RESPONSES` 和 `MYAPP_HTTP_SAVE_RESPONSES` 控制是否打印或保存

## 4. 推荐执行方式

跑既有主链路：

```bash
python3 -m unittest apps.myapp.myapp.tests.http.test_gateway_http
```

跑 v2 商品与销售状态聚合：

```bash
python3 -m unittest apps.myapp.myapp.tests.http.test_gateway_v2_http
```

跑单个测试方法：

```bash
python3 -m unittest \
  apps.myapp.myapp.tests.http.test_gateway_v2_http.GatewayV2HttpTestCase.test_create_product_and_stock_idempotent_replay
```

推荐顺序：

1. 先跑单接口测试
2. 再跑幂等与并发测试
3. 最后跑链路 smoke test
4. 需要全量回归时再跑整份文件

## 5. 当前已验证结果

### 5.1 既有销售与采购 HTTP 测试

已完成：

- 销售主链路成功测试
- 销售顺序幂等
- 销售不同数据测试
- 销售并发幂等
- 采购主链路成功测试
- 采购顺序幂等
- 采购不同数据测试
- 采购并发幂等
- 部分发货
- 部分开票
- 部分收货
- 基于收货单的部分开票
- 基于收货单的部分退货

### 5.2 本轮 v2 HTTP 测试

本轮新增并完成真实 HTTP 验证的接口：

- `search_product_v2`
- `create_product_and_stock`
- `get_product_detail_v2`
- `update_product_v2`
- `create_order_v2`
- `cancel_order_v2`
- `update_order_v2`
- `update_order_items_v2`
- `get_customer_sales_context`
- `get_sales_order_detail`
- `get_sales_order_status_summary`
- `get_delivery_note_detail_v2`
- `get_sales_invoice_detail_v2`

本轮已按“逐接口复测 -> 全量回归”重新执行一遍：

- 单接口复测：
  - `search_product_v2`
  - `create_product_and_stock`
  - `get_product_detail_v2`
  - `update_product_v2`
  - `create_order_v2`
  - `cancel_order_v2`
  - `update_order_v2`
  - `update_order_items_v2`
  - `get_customer_sales_context`
  - `get_sales_order_detail`
  - `get_sales_order_status_summary`
- 全量复测：
  - `python3 -m unittest apps.myapp.myapp.tests.http.test_gateway_v2_http`

本轮已完成的 v2 测试类型：

- 单接口成功路径
- 商品创建后可被 `search_product_v2` 搜到
- 条码搜索
- 昵称搜索
- 商品详情读取
- 商品基础信息更新
- 多条件搜索与排序的基础验证
- `create_product_and_stock` 顺序幂等 replay
- 相同 `request_id` 但不同请求数据，返回第一次结果
- 相同 `request_id` 并发请求，仅创建一份商品和一张入库单
- 负数初始入库数量校验
- 重复条码校验
- `create_order_v2` 成功路径
- `create_order_v2` 顺序幂等 replay
- `create_order_v2` 创建后详情接口可回读地址文本快照
- `cancel_order_v2` 成功路径
- `update_order_v2` 成功路径
- `update_order_v2` 更新后详情接口可回读联系人 / 地址 / 交货日期 / 备注
- `update_order_items_v2` 成功路径
- `update_order_items_v2` 在提交态订单上自动 amendment 并返回新订单号
- `update_payment_status` 全额收款成功路径
- `update_payment_status` 少收并结清（writeoff）成功路径
- `update_payment_status` 多收并生成未分配金额成功路径
- `get_delivery_note_detail_v2` 成功路径
- `get_sales_invoice_detail_v2` 成功路径
- v2 轻链路 smoke test

v2 轻链路内容：

- 建商品并入库
- `search_product_v2` 搜索新商品
- `create_order` 创建销售单
- `get_sales_order_detail` 查询详情
- `get_sales_order_status_summary` 查询列表摘要

## 6. 本轮关键测试结论

### 6.1 接口状态

以下接口已通过真实 HTTP 测试：

- `myapp.api.gateway.search_product_v2`
- `myapp.api.gateway.create_product_and_stock`
- `myapp.api.gateway.get_product_detail_v2`
- `myapp.api.gateway.update_product_v2`
- `myapp.api.gateway.create_order_v2`
- `myapp.api.gateway.cancel_order_v2`
- `myapp.api.gateway.update_order_v2`
- `myapp.api.gateway.update_order_items_v2`
- `myapp.api.gateway.get_customer_sales_context`
- `myapp.api.gateway.get_sales_order_detail`
- `myapp.api.gateway.get_sales_order_status_summary`
- `myapp.api.gateway.get_delivery_note_detail_v2`
- `myapp.api.gateway.get_sales_invoice_detail_v2`
- `myapp.api.gateway.update_payment_status`

当前补充说明：

- `cancel_order_v2` 的真实 HTTP 用例已加入测试文件
- 最新复测结果：`test_cancel_order_v2_success` 已通过真实 HTTP 验证
- `update_payment_status` 本轮新增两条真实 HTTP 用例：
  - `test_update_payment_status_writeoff_success`
  - `test_update_payment_status_overpayment_success`
- 本轮新增了发货单 / 发票详情聚合的定向服务测试与 gateway wrapper 测试：
  - `test_get_delivery_note_detail_returns_references_and_items`
  - `test_get_sales_invoice_detail_returns_payment_and_references`
  - `test_get_delivery_note_detail_v2_passes_name_to_service`
  - `test_get_sales_invoice_detail_v2_passes_name_to_service`
- 本轮新增了强制出货的定向服务测试：
  - `test_submit_delivery_force_delivery_skips_stock_precheck`
- 本轮新增了订单兜底关联测试：
  - `test_build_delivery_note_references_falls_back_to_sales_order_invoices`
  - `test_build_sales_invoice_references_falls_back_to_sales_order_delivery_notes`
- 当前已确认：
  - 全额收款：`test_update_payment_status_success` 通过
  - 幂等 replay：`test_update_payment_status_idempotent_replay` 通过
  - 少收并结清：`writeoff_amount` 返回正确，发票 `outstanding_amount = 0`
  - 多收：`unallocated_amount` 返回正确，发票 `outstanding_amount = 0`
  - 发货单详情聚合：来源订单 / 关联发票 / 商品明细映射正确
  - 发票详情聚合：来源订单 / 来源发货单 / 最新收款摘要映射正确
  - 在“发票基于订单生成”的链路下，发货单与发票详情仍能通过来源订单互相兜底关联

### 6.2 幂等结论

`create_product_and_stock` 当前已经支持 `request_id` 幂等，且已通过真实 HTTP 测试验证：

- 相同 `request_id` 顺序重试不会重复创建商品
- 相同 `request_id` 且请求体不同，仍返回第一次成功结果
- 相同 `request_id` 并发请求不会重复创建商品或入库单

### 6.3 权限结论

本轮还确认了一个真实环境问题：

- 测试账号初始缺少 `Item` 创建权限
- 补充 `物料主数据管理员`、`仓管员`、`仓库经理` 后，`create_product_and_stock` 才能通过

这说明：

- 商品工作台相关 HTTP 测试依赖真实站点权限
- 不能只看接口代码是否正确，也要同时检查 ERPNext 角色配置

## 7. 当前推荐的测试账号权限

若需要验证 `create_product_and_stock`，建议测试账号至少具备：

- `物料主数据管理员` (`Item Manager`)
- `仓管员` (`Stock User`)
- `仓库经理` (`Stock Manager`)

若缺少这些角色，可能出现：

- 能搜索商品
- 但不能创建商品
- 或不能完成入库

## 8. 本轮执行结果摘要

本轮最新一次真实执行结果：

- 新增的 6 个 v2 商品增强用例：`OK`
- 新增的 2 个商品详情 / 更新 v2 用例：`OK`
- 新增的 3 个 `create_order_v2` 用例：`OK`
- 新增的 2 个订单更新 v2 用例：`OK`
- 新增的 1 个 `get_customer_sales_context` 用例：`OK`
- 单接口复测结果：`Ran 1 test in 0.165s ... OK`
- 最新一次定向订单更新测试结果：`Ran 2 tests in 0.494s ... OK`
- 最新一次 `test_gateway_v2_http.py` 全量执行结果：`Ran 112 tests in 22.138s ... OK`

说明：

- 该全量结果包含 v2 文件直接定义的测试，以及测试模块中可被发现的既有 HTTP 测试类
- 其中商品工作台、销售状态聚合、订单更新相关新增能力已全部通过
- 本次重新复测后，8 个销售侧 v2 升级接口都已再次确认可用
- 当前本地联调站点还手工补齐了 3 个客户的主联系人与收货地址，便于验证 `get_customer_sales_context` 与移动端自动带入逻辑：
  - `Palmer Productions Ltd.`
  - `West View Software Ltd.`
  - `Grant Plastics Ltd.`

## 9. 当前仍建议后续补充的测试

虽然当前 v2 核心能力已可用，但以下场景仍建议后续补：

- 不同用户角色下的权限差异测试
- 更高并发量压测
- 非法筛选组合与异常排序参数
- 默认仓库回退场景的更多环境验证
- 商品编辑能力落地后的回归测试
- `create_order_v2` 落地后的新业务模型链路测试
- 客户联系人缺主电话、地址无 `address_display` 但有结构化地址字段等主数据变体测试

## 10. 测试文档维护建议

后续每新增一类对外接口，建议同步更新四处：

- 代码实现
- HTTP 测试
- API 文档
- 本测试文档

建议优先记录：

- 测了哪些接口
- 用什么方式测
- 测过哪些成功路径、幂等、并发、边界条件
- 当前已知未覆盖项
