# 测试说明

更新时间：2026-04-01

## 1. 测试原则

当前项目以 VS Code devcontainer / Docker 中运行的 ERPNext 环境作为开发与验收基准。

对 `myapp.api.gateway.*` 这类对外接口，优先使用 HTTP 方式测试，不以 WSL 宿主机直接导入 Frappe 服务层作为主验收方式。

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
- `myapp/tests/integration/`
  用于依赖真实站点上下文的服务链路回归验证

当前重点 HTTP 文件：

- [test_gateway_http.py](/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/tests/http/test_gateway_http.py)
  覆盖既有销售与采购主链路
- [test_gateway_v2_http.py](/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/tests/http/test_gateway_v2_http.py)
  覆盖商品工作台与销售状态聚合相关 v2 能力
- [test_purchase_quick_http.py](/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/tests/http/test_purchase_quick_http.py)
  覆盖采购快捷开单 / 快捷回退的真实 HTTP 回归

结果文件：

- [http-test-results.json](/home/rgc318/python-project/frappe_docker/apps/myapp/http-test-results.json)

环境变量示例：

- [.env.http-test.example](/home/rgc318/python-project/frappe_docker/apps/myapp/.env.http-test.example)

## 3. 环境准备

1. 确保 devcontainer / Docker 中的 ERPNext 正在运行。
2. 复制 `.env.http-test.example` 为 `.env.http-test`。
3. 配置以下内容：
   - 宿主机执行 HTTP 测试时：
     - `MYAPP_HTTP_BASE_URL=http://localhost:8080`
   - backend 容器内直接执行 HTTP 测试时：
     - `MYAPP_HTTP_BASE_URL=http://localhost:8000`
   - 测试账号密码或 API Token
4. 宿主机执行测试时使用 `python3`，不要默认使用 `python`。

补充说明：

- 宿主机侧当前约定使用 `http://localhost:8080`，不要随意改成 `127.0.0.1`
- backend 容器内若直接跑 HTTP 测试，应改用 `http://localhost:8000`
- 测试默认会打印响应，并写入 `http-test-results.json`
- 可通过 `MYAPP_HTTP_PRINT_RESPONSES` 和 `MYAPP_HTTP_SAVE_RESPONSES` 控制是否打印或保存

### 3.1 Docker 容器内运行 Python 测试的注意事项

如果需要在 `frappe_docker-backend-1` 这类 backend 容器里执行 `myapp/tests/unit/` 下的 Python 单元测试，请注意：

- 不要直接使用容器内的系统 Python，例如 `/usr/local/bin/python3`
- 优先使用 bench 虚拟环境中的 Python：
  - `/home/frappe/frappe-bench/env/bin/python`
- 原因：
  - 系统 Python 可能无法正确加载 bench 环境依赖
  - 这会表现为：
    - `ModuleNotFoundError: No module named 'frappe'`
    - 或误判为缺少某些依赖包

推荐检查方式：

```bash
docker exec frappe_docker-backend-1 bash -lc '
  cd /home/frappe/frappe-bench &&
  env/bin/python - << "PY"
import importlib.util
print("frappe:", importlib.util.find_spec("frappe"))
print("orjson:", importlib.util.find_spec("orjson"))
PY'
```

补充约定：

- 若只是跑 HTTP 测试，仍优先在宿主机通过 `python3 -m unittest ...http...` 访问 `http://localhost:8080`
- 若已进入 backend 容器并直接执行 HTTP 测试，请显式传入：
  - `MYAPP_HTTP_BASE_URL=http://localhost:8000`
- 若要跑服务层单元测试，优先在 bench 环境中执行，而不是在仓库根目录直接用宿主机 `python3` 导入 `frappe`
- 即使已经进入 backend 容器，也不代表“系统 Python = bench Python”，两者不要混用

## 4. 推荐执行方式

跑既有主链路：

```bash
python3 -m unittest apps.myapp.myapp.tests.http.test_gateway_http
```

跑 v2 商品与销售状态聚合：

```bash
python3 -m unittest apps.myapp.myapp.tests.http.test_gateway_v2_http
```

跑采购快捷链路回归：

```bash
python3 -m unittest apps.myapp.myapp.tests.http.test_purchase_quick_http
```

跑单个测试方法：

```bash
python3 -m unittest \
  apps.myapp.myapp.tests.http.test_gateway_v2_http.GatewayV2HttpTestCase.test_create_product_and_stock_idempotent_replay
```

跑销售单位换算与库存结算链路回归：

```bash
docker exec frappe_docker-backend-1 bash -lc '
  cd /home/frappe/frappe-bench &&
  env/bin/python -m unittest apps.myapp.myapp.tests.integration.test_sales_uom_stock_chain
'
```

推荐顺序：

1. 先跑单接口测试
2. 再跑幂等与并发测试
3. 最后跑链路 smoke test
4. 需要全量回归时再跑整份文件

### 4.1 容器内运行单元测试的建议

若要在 backend 容器中执行服务层单元测试，推荐优先按 bench 环境运行，例如：

```bash
docker exec frappe_docker-backend-1 bash -lc '
  cd /home/frappe/frappe-bench &&
  env/bin/python -m unittest apps.myapp.myapp.tests.unit.test_order_service
'
```

注意：

- 这里的关键不是“是否在容器内”，而是“是否使用了 bench 虚拟环境中的 Python”
- 若直接改用容器系统 Python，可能出现：
  - 找不到 `frappe`
  - 找不到 `orjson`
  - 或因为未进入正确 bench 上下文而得到误导性报错

当前新增了一组依赖真实站点上下文的销售链路回归：

- [test_sales_uom_stock_chain.py](/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/tests/integration/test_sales_uom_stock_chain.py)

这组测试的重点不是 HTTP 包装，而是确认真实业务单据在服务层执行后：

- 销售订单行的 `qty + uom` 会被正确换算成 `stock_qty`
- 发货时库存预检按库存口径拦截
- `Bin.actual_qty` 与 `Stock Ledger Entry.actual_qty` 和订单换算结果保持一致

当前覆盖 4 个场景：

- 批发单位建单并发货
- 零售单位建单并发货
- 建单后修改单位与数量，再发货
- 批发单位库存不足时发货被拦截，且库存不变

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

### 5.1.1 2026-04-01 采购快捷链路补充回归

本轮围绕采购快捷开单、快捷回退、付款边界与退货边界做了两层主验证：

- 采购服务层定向单测
- 采购真实 HTTP 链路回归

当前结果：

- backend 容器 bench 环境：
  - `env/bin/python -m unittest apps.myapp.myapp.tests.unit.test_purchase_service`
  - `Ran 32 tests`
  - `OK`
- 宿主机 HTTP 回归：
  - `python3 -m unittest apps.myapp.myapp.tests.http.test_purchase_quick_http`
  - `Ran 31 tests`
  - `OK`

本轮采购 HTTP 覆盖重点：

- `quick_create_purchase_order_v2`
- `quick_cancel_purchase_order_v2`
- 快捷回退后重新走分步 `收货 -> 开票 -> 付款`
- 快捷开单与快捷回退的幂等 replay
- 收货 / 开票 / 付款分步动作的幂等 replay
- 同一 `request_id` 下的并发付款竞争，仅生成一笔付款
- 付款步骤失败后的恢复
- 快捷回退中途失败后的恢复
- 多收货单 / 多发票 / 多付款保护分支
- 部分付款后追加付款
- 超额付款与非正数付款金额
- 收货退货 / 发票退货存在时的快捷回退边界
- 收货退货 / 发票退货存在时的分步回退边界
- 采购发票 `writeoff` 当前限制验证

当前已确认的采购付款 / 结算口径：

- `record_supplier_payment`：
  - `paid_amount <= 0` 会直接拒绝
  - 超额付款会直接拒绝，不会落成 unallocated amount
- `update_payment_status(reference_doctype="Purchase Invoice", settlement_mode="writeoff")`：
  - 当前对采购发票会返回 `当前无需执行差额核销。`
  - 即：销售发票支持的 `writeoff` 成功路径，采购发票当前尚未跑通
  - 失败后不会污染采购订单详情中的付款状态

当前阶段结论：

- 采购快捷链路已经具备可重复执行的 HTTP 回归文件，可作为后续改动的主验收入口
- 对本轮新增采购后端能力，主链路、失败恢复、付款边界、退货边界、幂等与竞争场景都已完成实测
- 目前剩余的测试更多是更深层的极端组合，而不是主链路空白

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

### 5.2.1 2026-04-01 采购快捷链路补充回归

本轮围绕采购快捷开单与快捷回退，新增了一份独立 HTTP 回归文件：

- [test_purchase_quick_http.py](/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/tests/http/test_purchase_quick_http.py)

本轮最新结果：

- `python3 -m unittest apps.myapp.myapp.tests.http.test_purchase_quick_http`
  - `Ran 17 tests in 15.295s`
  - `OK`

本轮覆盖重点：

- `quick_create_purchase_order_v2`
  - 快捷下单 -> 收货 -> 开票
  - 同一 `request_id` 幂等重放
- `quick_cancel_purchase_order_v2`
  - 部分付款后逆序回退
  - 同一 `request_id` 幂等重放
  - 回退后恢复到可编辑 `submitted` 状态
  - 无下游单据时空回退
- 分步与快捷交叉：
  - 先手动回退付款，再快捷回退剩余发票/收货单
  - 先手动回退发票，再快捷回退剩余收货单
  - 先手动回退收货单，再快捷回退空链路
- 安全拒绝边界：
  - 多张采购收货单
  - 多张采购发票
  - 多笔有效付款
  - 已付款但 `rollback_payment=false`
  - 收货退货单存在
  - 发票退货单存在

本轮新增结论：

- `quick_cancel_purchase_order_v2` 当前语义是“撤销下游单据并返回订单详情”，不再直接作废采购订单
- 当采购退货单存在时，当前明细聚合会把退货单一起计入引用列表：
  - 收货退货表现为“多张采购收货单”
  - 发票退货表现为“多张采购发票”
- 因此当前快捷回退在退货场景下会保守拒绝，要求改用分步回退

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

### 5.3 2026-03-25 最新回归结论

本轮在 backend 容器 bench 环境内重新执行了以下测试：

- `env/bin/python -m unittest apps.myapp.myapp.tests.unit.test_wholesale_service`
  - 定向结论：
    - 新增的“默认成交单位必须能换算到库存基准单位”规则已验证通过
    - 当前适合作为本轮结论依据的定向用例为 `6` 条，结果 `OK`
- `MYAPP_HTTP_BASE_URL=http://localhost:8000 env/bin/python -m unittest apps.myapp.myapp.tests.http.test_gateway_http`
  - 全量结果：
    - `Ran 49 tests in 33.298s`
    - `OK`
- `MYAPP_HTTP_BASE_URL=http://localhost:8000 env/bin/python -m unittest apps.myapp.myapp.tests.http.test_gateway_v2_http`
  - 全量结果：
    - `Ran 119 tests in 55.746s`
    - `OK`

本轮明确确认：

- 新增后端校验已生效：
  - `wholesale_default_uom`
  - `retail_default_uom`
  - 以上默认成交单位必须能通过 `uom_conversions` 换算到 `stock_uom`
- 经典销售主链路未受影响：
  - 下单
  - 发货
  - 开票
  - 收款
  - 退货
- v2 销售链路未受影响：
  - `create_order_v2`
  - `update_order_v2`
  - `update_order_items_v2`
  - `cancel_order_v2`
  - `get_sales_order_detail`
  - `get_sales_order_status_summary`

补充说明：

- `tests/integration/test_sales_uom_stock_chain.py` 本轮再次执行时，仍可能在当前环境触发 `tabSeries` 锁冲突
- 该问题表现为 `QueryDeadlockError`，属于当前站点命名序列竞争，不是业务断言失败
- 因此本轮“是否影响核心逻辑”的最终判断，优先依据上述 `49 OK` 与 `119 OK` 的 HTTP 全链路结果
- `update_payment_status` 多收并生成未分配金额成功路径
- `get_delivery_note_detail_v2` 成功路径
- `get_sales_invoice_detail_v2` 成功路径
- v2 轻链路 smoke test

### 5.4 2026-03-26 单位管理后端回归结论

本轮在 backend 容器 bench 环境内新增执行了以下测试：

- `env/bin/python -m unittest apps.myapp.myapp.tests.unit.test_uom_service apps.myapp.myapp.tests.unit.test_gateway_wrappers`
  - 全量结果：
    - `Ran 44 tests in 0.015s`
    - `OK`

另外还在真实站点中使用两组临时单位数据执行了完整 CRUD 验证：

- 创建单位
- 模糊搜索列表
- 查询详情
- 更新展示字段
- 停用 / 启用
- 删除未引用单位

本轮明确确认：

- `list_uoms_v2`
- `get_uom_detail_v2`
- `create_uom_v2`
- `update_uom_v2`
- `disable_uom_v2`
- `delete_uom_v2`

以上接口当前均已通过验证。

补充说明：

- 删除保护与“已被引用单位不可直接修改整数规则”的逻辑，当前以单元测试为主要验证方式
- 真实站点 CRUD 验证使用的是未被引用的临时单位，因此删除成功属于预期行为

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
- 新增的 5 个客户模块服务层用例：`OK`
- 新增的 5 个客户模块网关包装用例：`OK`
- 单接口复测结果：`Ran 1 test in 0.165s ... OK`
- 最新一次定向订单更新测试结果：`Ran 2 tests in 0.494s ... OK`
- 最新一次客户模块定向单测结果：`Ran 34 tests in 0.013s ... OK`
- 最新一次真实站点客户 CRUD 验证：2 组客户数据的创建 / 列表 / 详情 / 更新 / 停用 / 启用全部通过，并已自动清理测试数据
- 最新一次 `test_gateway_v2_http.py` 全量执行结果：`Ran 112 tests in 22.138s ... OK`

说明：

- 该全量结果包含 v2 文件直接定义的测试，以及测试模块中可被发现的既有 HTTP 测试类
- 其中商品工作台、销售状态聚合、订单更新相关新增能力已全部通过
- 本次重新复测后，8 个销售侧 v2 升级接口都已再次确认可用
- 当前本地联调站点还手工补齐了 3 个客户的主联系人与收货地址，便于验证 `get_customer_sales_context` 与移动端自动带入逻辑：
  - `Palmer Productions Ltd.`
  - `West View Software Ltd.`
  - `Grant Plastics Ltd.`

### 8.1 采购工作台搜索最新补充验证（2026-04-01）

本轮新增采购工作台真实检索接口：

- `myapp.api.gateway.search_purchase_orders_v2`

本地已完成并通过的验证：

- 后端单元测试
  - `search_purchase_orders_v2` 默认排除已作废
  - `search_key / status_filter / sort_by / company / start / limit` 参数透传
- 真实 HTTP 回归
  - 默认 `exclude_cancelled=true` 时，已作废订单不会进入 `items`
  - 显式切到 `status_filter=cancelled` 时，可以查到已作废订单
  - `status_filter=receiving` 可命中待收货订单
  - `status_filter=paying` 可命中已收货已开票但未付款订单
  - `search_key=完整订单号` 可稳定命中目标订单

本轮最新一次采购 HTTP 全量回归结果：

- `apps.myapp.myapp.tests.http.test_purchase_quick_http`
- `Ran 36 tests in 30.947s ... OK`

### 8.2 销售工作台搜索最新补充验证（2026-04-01）

本轮新增销售工作台真实检索接口：

- `myapp.api.gateway.search_sales_orders_v2`

本地已完成并通过的验证：

- 后端单元测试
  - `search_sales_orders_v2` 默认排除已作废
  - `search_key / customer / company / status_filter / sort_by / start / limit` 参数透传
- 真实 HTTP 回归
  - 默认 `exclude_cancelled=true` 时，已作废订单不会进入 `items`
  - 显式切到 `status_filter=cancelled` 时，可以查到已作废销售订单
  - `search_key=完整订单号` 可稳定命中目标订单

本轮最新一次销售 HTTP 定向回归结果：

- `myapp.tests.http.test_gateway_v2_http.GatewayV2HttpTestCase`
- `Ran 3 tests in 1.553s ... OK`

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
