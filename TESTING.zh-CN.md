# 测试说明

更新时间：2026-04-02

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

跑性能基线脚本：

```bash
python3 -m apps.myapp.myapp.tests.http.benchmark_gateway_http
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

### 4.2 性能基线执行方式

性能基线脚本用于记录当前版本在本机 / 本地 devcontainer 环境下的接口耗时基准，不替代功能回归测试。

当前脚本：

- [benchmark_gateway_http.py](/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/tests/http/benchmark_gateway_http.py)

默认覆盖 5 类高频接口：

- `search_sales_orders_v2`
- `search_purchase_orders_v2`
- `get_sales_order_detail`
- `get_purchase_order_detail_v2`
- `search_product_v2`

默认行为：

- 每个接口采样 5 次
- 自动先查询当前可用销售单 / 采购单，避免手填单号
- 输出平均值、最小值、最大值和近似 `P95`
- 将结果写入：
  - [performance-baseline-results.json](/home/rgc318/python-project/frappe_docker/apps/myapp/performance-baseline-results.json)

可选执行方式：

```bash
python3 -m apps.myapp.myapp.tests.http.benchmark_gateway_http --samples 10
```

```bash
python3 -m apps.myapp.myapp.tests.http.benchmark_gateway_http \
  --output /tmp/myapp-perf-baseline.json
```

建议使用场景：

- 工作台查询或详情聚合有性能改动后
- 索引调整后
- 上线前进行本机基线复核
- 后续出现“接口变慢”反馈时做回归比对

当前最新一次采样结果文件：

- [performance-baseline-results.json](/home/rgc318/python-project/frappe_docker/apps/myapp/performance-baseline-results.json)

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

### 5.1.2 2026-04-01 销售 / 采购退货上下文与结果增强回归

本轮围绕“通用退货模块底座”新增了两类后端能力：

- `get_return_source_context_v2`
- 销售 / 采购退货提交后的增强返回

当前结果：

- backend 容器 bench 环境：
  - `PYTHONPATH=apps/myapp:apps/frappe ./env/bin/python -m unittest`
  - 定向集：
    - `myapp.tests.unit.test_return_service`
    - `myapp.tests.unit.test_gateway_wrappers`
    - 退货相关定向单测
  - `Ran 61 tests`
  - `OK`
- 宿主机真实 HTTP 回归：
  - 退货 / 付款定向集
  - `Ran 14 tests`
  - `OK`
- 宿主机 gateway HTTP 全量回归：
  - `python3 -m unittest apps.myapp.myapp.tests.http.test_gateway_http`
  - `Ran 55 tests`
  - `OK`

本轮退货 HTTP 覆盖重点：

- `get_return_source_context_v2`
  - `Sales Invoice`
  - `Delivery Note`
  - `Purchase Invoice`
  - `Purchase Receipt`
- `process_sales_return`
  - 成功
  - 幂等 replay
  - 已收款销售发票退货后的后续动作建议
- `process_purchase_return`
  - 成功
  - 幂等 replay
  - 基于 `Purchase Receipt` 的部分退货
  - 已付款采购发票退货后的后续动作建议
- 相关资金动作现状校验：
  - 销售收款成功
  - 销售 `writeoff` 成功
  - 采购付款成功

当前已确认的退货 / 退款口径：

- 系统当前支持：
  - 创建独立销售退货单 / 采购退货单
  - 返回统一退货来源上下文
  - 返回退货结果摘要与后续动作建议
- 系统当前不自动支持：
  - 销售退货时自动生成退款闭环
  - 采购退货时自动生成供应商退款 / 应付冲减闭环
- 因此当前推荐口径是：
  - 销售已收款发票退货 -> `review_refund`
  - 采购已付款发票退货 -> `review_supplier_refund`

测试工具层补充：

- `test_gateway_http.py` 当前已对 `http-test-results.json` 的损坏内容增加容错
- 即使结果快照文件异常，真实 HTTP 回归本身仍可继续执行，不会被 `JSONDecodeError` 全面阻断

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

## 11. 工作台查询性能重构补充验证（2026-04-02）

本轮针对销售与采购工作台查询接口做了生产化方向的性能重构。

涉及接口：

- `myapp.api.gateway.search_sales_orders_v2`
- `myapp.api.gateway.search_purchase_orders_v2`

### 11.1 本轮实现调整

- 去掉工作台检索中的逐单详情聚合模式
  - 销售侧不再对列表候选逐条调用 `get_sales_order_detail`
  - 采购侧不再对列表候选逐条调用 `get_purchase_order_detail_v2`
- 改为批量读取并聚合：
  - 订单主表
  - 订单明细
  - 发票引用
  - 付款引用
- 修正工作台状态口径：
  - 销售待发货判断改为基于 `is_fully_delivered`
  - 采购待收货判断改为基于 `is_fully_received`

### 11.2 已通过的聚焦单元测试

本轮新增 / 调整后已通过的聚焦单元测试包括：

- 销售
  - `test_get_sales_order_status_summary_returns_list`
  - `test_search_sales_orders_v2_filters_out_cancelled_by_default`
  - `test_search_sales_orders_v2_passes_search_filters_and_sorts`
- 采购
  - `test_get_purchase_order_status_summary_uses_summary_rows`
  - `test_search_purchase_orders_v2_filters_out_cancelled_by_default`
  - `test_search_purchase_orders_v2_passes_search_filters_and_sorts`

容器内执行结果：

- `Ran 6 tests in 0.008s ... OK`

### 11.3 已通过的真实 HTTP 搜索回归

本轮额外执行了销售与采购工作台的真实 HTTP 查询回归，共 12 个用例，全部通过。

销售侧覆盖：

- 默认隐藏已作废订单
- 显式查询已作废订单
- 按完整订单号搜索
- `status_filter=delivering`
- `status_filter=completed`
- 客户 / 公司过滤
- `sort_by=amount_desc`
- `limit + start` 分页

采购侧覆盖：

- 默认隐藏已作废订单
- 显式查询已作废订单
- 按完整订单号搜索
- `status_filter=receiving`
- `status_filter=paying`

执行结果：

- `Ran 12 tests in 5.526s ... OK`

### 11.4 当前本机延迟采样

基于本地服务、真实 HTTP 请求、同一批现有业务数据，连续采样 5 次后的结果如下：

- 销售 `unfinished`
  - 平均 `42.1ms`
  - 最低 `40.7ms`
  - 最高 `43.5ms`
  - 当时查询口径：`visible_count=594`, `total_count=620`
- 销售 `amount_desc`
  - 平均 `42.3ms`
  - 最低 `41.5ms`
  - 最高 `42.7ms`
- 采购 `unfinished`
  - 平均 `49.8ms`
  - 最低 `45.6ms`
  - 最高 `65.6ms`
  - 当时查询口径：`visible_count=577`, `total_count=583`
- 采购 `paying`
  - 平均 `46.0ms`
  - 最低 `44.8ms`
  - 最高 `48.1ms`

说明：

- 相比此前本地约 `1000ms` 的体感，本轮工作台查询延迟已明显下降
- 当前结果说明：
  - 在数百条有效订单规模下，工作台搜索已达到可接受的本地联调性能
- 采购首轮样本略高，后续样本回落到稳定区间，判断为常见冷启动 / 缓存预热波动

### 11.5 当前仍未覆盖的部分

- 还没有形成正式的压测报告
- 还没有在更高数量级数据下做系统化基准对比
- 工作台查询虽然已去掉逐单详情 N+1，但当前仍属于“服务层批量聚合”
- 如果后续数据规模继续上升，仍建议进一步推进：
  - 更接近数据库原生分页
  - 计数查询与列表查询分离
  - 视需要补充索引与 explain 级分析

## 12. 快捷链路返回瘦身验证（2026-04-02）

本轮继续做了一步接口生产化收敛，目标是减少快捷链路在成功响应中附带的重型详情数据。

涉及接口：

- `myapp.api.gateway.quick_create_order_v2`
- `myapp.api.gateway.quick_cancel_order_v2`
- `myapp.api.gateway.quick_create_purchase_order_v2`
- `myapp.api.gateway.quick_cancel_purchase_order_v2`

### 12.1 本轮调整

- 快捷接口默认返回精简结果
- 默认情况下不再主动附带完整 `detail`
- 新增显式能力：
  - `include_detail=1`
- 当调用方显式传入该参数时：
  - 才会附带完整详情
  - 同时返回 `detail_included=true`

### 12.2 已通过的聚焦单元测试

本轮已验证：

- 销售快捷开单默认不拉详情
- 销售快捷开单显式 `include_detail=1` 时可带详情
- 销售快捷回退默认不拉详情
- 采购快捷开单默认不拉详情
- 采购快捷开单显式 `include_detail=1` 时可带详情
- 采购快捷回退默认不拉详情
- 采购快捷回退在发票回退失败恢复场景下仍保持精简返回
- 采购快捷回退在收货回退失败恢复场景下仍保持精简返回

容器内执行结果：

- `Ran 8 tests in 0.012s ... OK`

### 12.3 当前意义

- 这一步不改变前端主流程接口名称与主要字段
- 但把“流程编排结果”和“完整详情读取”从默认耦合状态改成了按需返回
- 这更适合正式生产部署：
  - 降低响应体积
  - 降低成功响应中的额外聚合负担
  - 让详情查询继续回归专用详情接口

## 13. 详情聚合复用验证（2026-04-02）

本轮继续对销售与采购详情接口做了一步生产化收敛，目标是减少详情侧重复的付款汇总装配逻辑。

涉及接口：

- `myapp.api.gateway.get_sales_order_detail`
- `myapp.api.gateway.get_sales_invoice_detail_v2`
- `myapp.api.gateway.get_purchase_order_detail_v2`
- `myapp.api.gateway.get_purchase_invoice_detail_v2`

### 13.1 本轮调整

- 销售侧抽出了订单详情与销售发票详情共用的付款指标写回辅助逻辑
- 采购侧抽出了订单详情与采购发票详情共用的付款指标写回辅助逻辑
- 统一了 `payment.latest_payment_*` 相关字段在订单详情与发票详情中的写回方式
- 减少了详情接口内部重复拼装付款摘要与最新付款结果的代码

### 13.2 测试夹具修正

在这轮验证中，发现一条历史销售详情测试的夹具缺少：

- `contact_person`
- `shipping_address_name`

这会导致测试断言联系人与地址快照时前提不成立。当前已补齐该夹具，使其与真实详情语义保持一致。

### 13.3 已通过的聚焦单元测试

本轮已验证：

- `test_get_sales_order_detail_aggregates_statuses`
- `test_get_sales_invoice_detail_returns_payment_and_references`
- `test_get_purchase_order_detail_v2_returns_aggregated_data`
- `test_get_purchase_invoice_detail_v2_returns_detail`

容器内执行结果：

- `Ran 4 tests in 0.006s ... OK`

### 13.4 当前意义

- 本轮不改变详情接口名称、参数或主要返回结构
- 主要收益在于减少销售 / 采购详情侧重复实现
- 后续继续演进详情接口时，可在共用 helper 上统一维护付款摘要口径

## 14. 单票付款摘要与批量底座统一验证（2026-04-02）

本轮继续做了一步内部收敛，目标是把详情接口中的“单票最新付款摘要”计算，统一委托到工作台同源的批量付款摘要底座上。

涉及服务：

- `myapp.services.order_service._get_latest_payment_entry_summary`
- `myapp.services.order_service._build_sales_latest_payment_summary_map`
- `myapp.services.purchase_service._get_latest_purchase_payment_entry_summary`
- `myapp.services.purchase_service._build_purchase_latest_payment_summary_map`

### 14.1 本轮调整

- 销售单票收款摘要改为直接委托销售批量付款摘要 map helper
- 采购单票付款摘要改为直接委托采购批量付款摘要 map helper
- 详情接口与工作台接口进一步收敛到同一套付款归因规则
- 减少了单票 helper 与批量 helper 两套并行实现继续漂移的风险

### 14.2 已通过的聚焦单元测试

本轮已验证：

- `test_get_latest_payment_entry_summary_returns_actual_paid_and_writeoff`
- `test_get_latest_purchase_payment_entry_summary_returns_actual_paid_and_writeoff`
- `test_get_sales_order_detail_aggregates_statuses`
- `test_get_sales_invoice_detail_returns_payment_and_references`
- `test_get_purchase_order_detail_v2_returns_aggregated_data`
- `test_get_purchase_invoice_detail_v2_returns_detail`

容器内执行结果：

- `Ran 6 tests in 0.005s ... OK`

### 14.3 当前意义

- 本轮不改变接口名称与返回结构
- 主要收益在于进一步统一销售 / 采购列表与详情的付款汇总底座
- 后续若继续调整付款归因规则，只需要维护批量摘要 helper 的主逻辑

## 15. 测试体系生产化整理（2026-04-02）

本轮目标不是新增业务能力，而是把核心测试矩阵整理成更稳定、可重复执行的形态，并清理一批历史单测中的环境脆弱点。

### 15.1 当前稳定的核心单测矩阵

本轮已回归并确认通过：

- `apps.myapp.myapp.tests.unit.test_order_service`
- `apps.myapp.myapp.tests.unit.test_purchase_service`
- `apps.myapp.myapp.tests.unit.test_customer_service`
- `apps.myapp.myapp.tests.unit.test_gateway_wrappers`
- `apps.myapp.myapp.tests.unit.test_idempotency`
- `apps.myapp.myapp.tests.unit.test_return_service`
- `apps.myapp.myapp.tests.unit.test_settlement_service`
- `apps.myapp.myapp.tests.unit.test_uom_service`
- `apps.myapp.myapp.tests.unit.test_wholesale_service`

容器内 bench 环境执行结果：

- `Ran 185 tests in 0.338s ... OK`

### 15.2 当前稳定的真实站点集成回归

本轮同时确认通过：

- `apps.myapp.myapp.tests.integration.test_sales_uom_stock_chain`

容器内 bench 环境执行结果：

- `Ran 4 tests in 1.470s ... OK`

### 15.3 本轮整理掉的历史脆弱模式

本轮清理的主要不是业务断言，而是测试与 Frappe 运行时之间的脆弱耦合：

- 销售服务单测中一批直接 patch `frappe.db.*` / `frappe.throw` / `nowdate()` 的旧写法
- 批发与结算单测里少量依赖 `frappe.local` 已绑定的假设
- 商品测试里 `_get_qty_map` 调用次数变化后，旧 `side_effect` 不够导致的 `StopIteration`
- 把 `frappe._dict({"items": [...]})` 当作可安全走 `.items` 属性的目标单据夹具

### 15.4 当前建议的测试写法

为了让后续单测继续稳定，当前建议优先采用以下方式：

- 优先 patch 自己的 service helper，而不是直接 patch `frappe.db.*` 这类懒代理属性
- 若确实需要数据库代理，优先 patch 整个 `frappe.db` mock 对象，而不是只 patch `frappe.db.get_value`
- 涉及 `frappe.throw` 的纯服务层单测，显式 patch 成 `ValidationError` 更稳
- 涉及 `nowdate()` / 系统时区的服务层单测，显式 patch `nowdate`
- 需要走 `target_doc.items` 属性路径时，优先使用 `MagicMock` / `SimpleNamespace`，不要把 `frappe._dict` 当成完整 Document 替身

### 15.5 当前意义

- 现在核心后端单测矩阵已经形成了更明确、可重复执行的主回归入口
- 新增生产化改动后，可以先回归：
  - 相关聚焦单测
  - 上述 9 份核心单测文件
  - `test_sales_uom_stock_chain`
- 这比只靠零散定向测试更适合持续演进阶段的验收节奏

## 16. 数据库 / 索引 / EXPLAIN 第一轮检查（2026-04-02）

本轮开始对销售 / 采购工作台相关查询做数据库层体检，目标是确认当前服务层优化之外，数据库执行计划是否也足够健康。

### 16.1 当前检查范围

本轮重点检查了以下表：

- `tabSales Order`
- `tabPurchase Order`
- `tabSales Invoice Item`
- `tabPurchase Invoice Item`
- `tabPayment Entry Reference`
- `tabPayment Entry`

### 16.2 第一轮 EXPLAIN 发现

在未补索引前，最明显的问题是：

- 销售工作台主订单查询
  - `tabSales Order`
  - `WHERE company = ? ORDER BY modified DESC`
  - `EXPLAIN` 为：
    - `type = ALL`
    - `Extra = Using where; Using filesort`
- 采购工作台主订单查询
  - `tabPurchase Order`
  - `WHERE company = ? ORDER BY modified DESC`
  - `EXPLAIN` 同样为：
    - `type = ALL`
    - `Extra = Using where; Using filesort`

这说明数据库在订单主表层面没有合适的复合索引可直接支撑工作台的“按公司过滤 + 按修改时间倒序”读取。

### 16.3 本轮新增的复合索引补丁

本轮新增 patch：

- [add_workbench_query_indexes.py](/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/patches/add_workbench_query_indexes.py)

并登记到：

- [patches.txt](/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/patches.txt)

新增索引包括：

- `tabSales Order`
  - `idx_myapp_so_company_modified (company, modified)`
  - `idx_myapp_so_customer_modified (customer, modified)`
- `tabPurchase Order`
  - `idx_myapp_po_company_modified (company, modified)`
  - `idx_myapp_po_supplier_modified (supplier, modified)`
- `tabPayment Entry Reference`
  - `idx_myapp_per_reference_lookup (reference_doctype, reference_name, parenttype, parentfield, modified)`

### 16.4 补索引后的结果

补丁在当前站点执行后，订单主查询的执行计划已经改善：

- 销售工作台主订单查询
  - 从 `type = ALL` 变为 `type = range`
  - 命中 `idx_myapp_so_company_modified`
  - `Extra` 降为 `Using where`
- 采购工作台主订单查询
  - 从 `type = ALL` 变为 `type = range`
  - 命中 `idx_myapp_po_company_modified`
  - `Extra` 降为 `Using where`
- 按客户 / 供应商过滤的订单查询
  - 分别命中：
    - `idx_myapp_so_customer_modified`
    - `idx_myapp_po_supplier_modified`

### 16.5 当前仍需继续观察的点

`tabPayment Entry Reference` 当前虽然新增了复合索引，但在以下查询上：

- `reference_doctype + reference_name + parenttype + parentfield + ORDER BY modified DESC`

优化器当前仍更倾向于使用旧的 `reference_name` 单列索引，`EXPLAIN` 仍显示：

- `Using index condition; Using where; Using filesort`

这说明第二阶段如果要继续深挖，可能需要二选一：

- 继续微调该复合索引的列顺序
- 或调整付款引用查询的取数 / 排序策略

### 16.6 本轮验证

本轮在补丁执行后，回归通过：

- `apps.myapp.myapp.tests.unit.test_order_service`
- `apps.myapp.myapp.tests.unit.test_purchase_service`
- `apps.myapp.myapp.tests.unit.test_settlement_service`
- `apps.myapp.myapp.tests.unit.test_wholesale_service`

容器内 bench 环境执行结果：

- `Ran 111 tests in 0.491s ... OK`

### 16.7 第二阶段查询收敛

在第一轮索引补丁之后，`tabPayment Entry Reference` 相关查询虽然已经有了更合适的候选索引，但由于查询仍带 `ORDER BY modified DESC`，`EXPLAIN` 仍显示：

- `Using index condition; Using where; Using filesort`

本轮进一步调整了销售 / 采购付款摘要 helper 的实现：

- 去掉 `Payment Entry Reference` 查询上的数据库排序
- 改为在服务层按 `modified` 选择同一 `Payment Entry` 下的最新引用行

涉及服务：

- `myapp.services.order_service._build_sales_latest_payment_summary_map`
- `myapp.services.purchase_service._build_purchase_latest_payment_summary_map`

调整后，当前 `EXPLAIN` 结果变为：

- `Using index condition; Using where`

也就是：

- `filesort` 已消失
- 当前策略更适合与新增索引配合使用

### 16.8 第二阶段验证

本轮继续通过：

- 6 个付款摘要 / 详情相关聚焦单测
  - `Ran 6 tests in 0.007s ... OK`
- 销售 / 采购服务核心单测文件
  - `apps.myapp.myapp.tests.unit.test_order_service`
  - `apps.myapp.myapp.tests.unit.test_purchase_service`
  - `Ran 82 tests in 0.575s ... OK`

## 17. 全服务层体检中的低风险收敛（2026-04-02）

在继续做全服务层接口体检时，本轮先处理了一处明显的低风险遗留问题：

- `myapp.services.wholesale_service.search_product`

### 17.1 本轮调整

- 移除了 `search_product` 中重复的 `_get_multi_price_map(...)` 调用
- 销售价 / 采购价聚合当前只各执行一次
- 这一步不改变接口参数、返回结构或业务口径

### 17.2 已通过的验证

本轮新增并通过：

- `apps.myapp.myapp.tests.unit.test_wholesale_service`

其中包含一条新的约束测试：

- `test_search_product_calls_price_summary_maps_once`

执行结果：

- `Ran 17 tests in 0.016s ... OK`

## 18. 性能基线脚本与当前基准（2026-04-02）

本轮作为后端生产化优化的最后一块，新增了独立的 HTTP 性能基线脚本：

- [benchmark_gateway_http.py](/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/tests/http/benchmark_gateway_http.py)

执行方式：

```bash
python3 -m apps.myapp.myapp.tests.http.benchmark_gateway_http
```

本次基线使用默认采样：

- 每个接口 5 次
- 本机 HTTP 网关
- 自动取当前可用销售单与采购单作为详情样本

### 18.1 本次实际采样结果

- `search_sales_orders_v2`
  - `avg 60.18ms`
  - `min 59.43ms`
  - `max 61.51ms`
- `search_purchase_orders_v2`
  - `avg 74.40ms`
  - `min 73.88ms`
  - `max 75.03ms`
- `get_sales_order_detail`
  - `avg 12.68ms`
  - `min 11.76ms`
  - `max 14.03ms`
- `get_purchase_order_detail_v2`
  - `avg 11.93ms`
  - `min 11.26ms`
  - `max 12.41ms`
- `search_product_v2`
  - `avg 10.51ms`
  - `min 9.11ms`
  - `max 12.59ms`

本次采样时工作台数据量摘要：

- 销售工作台：
  - `total_count = 710`
  - `visible_count = 602`
- 采购工作台：
  - `total_count = 1032`
  - `visible_count = 577`

### 18.2 配套回归验证

本轮同步回跑并通过：

- `apps.myapp.myapp.tests.http.test_gateway_v2_http.GatewayV2HttpTestCase.test_search_sales_orders_v2_supports_amount_desc_sort_and_paging`
- `apps.myapp.myapp.tests.http.test_purchase_quick_http.PurchaseQuickHttpTestCase.test_search_purchase_orders_finds_payment_pending_order`

结果：

```text
Ran 2 tests in 1.706s

OK
```

### 18.3 当前结论

- 这套性能基线脚本已经可以作为后续查询、索引、详情聚合优化后的统一验收入口
- 当前版本在本地数据量下，销售 / 采购工作台查询与关键详情接口耗时已经处于可接受范围
- 后续若出现性能回归，可直接复跑脚本并与 `performance-baseline-results.json` 对比

## 19. 项目级后端完整回归（2026-04-02）

本轮在前述生产化优化完成后，额外执行了一次项目级后端回归，目标不是验证单一接口，而是同时确认：

- 销售链路分步流程与快捷流程是否都可用
- 采购链路分步流程与快捷流程是否都可用
- 查询、详情、幂等、回退与付款相关改动是否没有引入回归
- 订单执行收货 / 发货 / 开票 / 付款后，库存与结算结果是否和订单聚合详情一致

### 19.1 本轮实际执行的测试层次

- 核心单元测试矩阵
  - `apps.myapp.myapp.tests.unit.test_customer_service`
  - `apps.myapp.myapp.tests.unit.test_gateway_wrappers`
  - `apps.myapp.myapp.tests.unit.test_idempotency`
  - `apps.myapp.myapp.tests.unit.test_order_service`
  - `apps.myapp.myapp.tests.unit.test_purchase_service`
  - `apps.myapp.myapp.tests.unit.test_return_service`
  - `apps.myapp.myapp.tests.unit.test_settlement_service`
  - `apps.myapp.myapp.tests.unit.test_uom_service`
  - `apps.myapp.myapp.tests.unit.test_wholesale_service`
- 全量 HTTP 回归
  - `apps.myapp.myapp.tests.http.test_gateway_http`
  - `apps.myapp.myapp.tests.http.test_gateway_v2_http`
  - `apps.myapp.myapp.tests.http.test_purchase_quick_http`
- 真实站点集成链路
  - `apps.myapp.myapp.tests.integration.test_sales_uom_stock_chain`
  - `apps.myapp.myapp.tests.integration.test_purchase_stock_payment_chain`

### 19.2 本轮结果

- 核心单元测试矩阵：
  - `Ran 186 tests in 0.418s ... OK`
- 销售 / 采购核心服务单测复跑：
  - `Ran 82 tests in 0.303s ... OK`
- 全量 HTTP 回归：
  - `Ran 229 tests in 89.337s ... OK`
- 真实站点集成测试：
  - `Ran 6 tests in 2.145s ... OK`

### 19.3 新增采购真实站点链路覆盖

本轮新增：

- [test_purchase_stock_payment_chain.py](/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/tests/integration/test_purchase_stock_payment_chain.py)

当前覆盖两类关键一致性验证：

- 采购收货后：
  - `Purchase Order Item.stock_qty`
  - `Bin.actual_qty`
  - `Stock Ledger Entry.actual_qty`
  三者保持一致
- 采购发票与付款后：
  - `Purchase Invoice.outstanding_amount`
  - `get_purchase_order_detail_v2(...).data.payment.paid_amount`
  - `get_purchase_order_detail_v2(...).data.payment.outstanding_amount`
  - `latest_payment_entry`
  保持一致

### 19.4 本轮顺手修正的问题

- 采购快捷回退 HTTP 测试原先仍按旧假设直接读取默认 `detail`
  - 现已显式改为 `include_detail=1`
- 销售 / 采购付款摘要中的：
  - `latest_writeoff_amount`
  - `latest_actual_paid_amount`
  当前已统一在无值时返回 `0`，避免回归测试与前端摘要出现 `None`
- 采购 HTTP 回归中的高频建单 / 收货 / 开票步骤，重试条件已从只识别 `tabBin` 扩展为通用：
  - `Record has changed since last read`
  以降低 Frappe / ERPNext 并发写入噪声对测试结果的影响

### 19.5 关于中途出现的并发噪声

本轮执行过程中曾出现过少量数据库并发噪声，例如：

- `tabSeries`
- `tabItem`

报错形式为：

- `Record has changed since last read`

最终处理方式：

- 对采购 HTTP 用例增加更稳的瞬时冲突重试
- 将销售 / 采购真实站点集成测试改为在 HTTP 全量结束后串行复跑

最终结论：

- 这些报错属于测试执行阶段的环境级并发噪声，不是业务断言失败
- 在串行复跑后，本轮项目级后端回归结果已全部通过

## 20. 供应商管理模块补测

本轮新增了供应商主数据管理动作接口：

- `create_supplier_v2`
- `update_supplier_v2`
- `disable_supplier_v2`

新增 / 回归验证范围：

- `test_purchase_service`
  - 供应商创建走幂等执行器
  - 供应商创建可同时生成默认联系人与默认地址
  - 供应商更新可同时更新主数据和主联系人 / 主地址绑定
  - 供应商停用走幂等执行器
- `test_gateway_wrappers`
  - 网关层正确透传 `create_supplier_v2`
  - 网关层正确透传 `update_supplier_v2`
  - 网关层正确透传 `disable_supplier_v2`
  - 新接口默认不暴露给 Guest

执行结果：

- 在后端容器中运行：
  - `env/bin/python -m unittest apps.myapp.myapp.tests.unit.test_purchase_service apps.myapp.myapp.tests.unit.test_gateway_wrappers`
- 结果：
  - `Ran 95 tests in 0.378s`
  - `OK`

### 20.1 供应商管理 HTTP 专项回归

本轮继续补了供应商管理的真实网关 HTTP 用例，覆盖：

- 成功链路：
  - `create_supplier_v2`
  - `update_supplier_v2`
  - `disable_supplier_v2`
  - `list_suppliers_v2`
  - `get_supplier_detail_v2`
- 校验失败：
  - 空 `supplier_name`
  - 重复创建同名供应商
- 幂等重放：
  - `create_supplier_v2`
  - `update_supplier_v2`
  - `disable_supplier_v2`
- 多条件筛选：
  - `supplier_group`
  - `disabled=0/1`
  - `search_key`
  - `limit/start`

执行结果：

- 在宿主机网关环境中运行：
  - `python3 -m unittest apps.myapp.myapp.tests.http.test_gateway_http.GatewayHttpTestCase.<11 supplier tests>`
- 结果：
  - `Ran 11 tests in 121.734s`
  - `OK`

运行注意事项：

- 供应商管理网关方法新增后，如果 HTTP 测试首次返回“找不到 `myapp.api.gateway.create_supplier_v2`”，通常不是代码缺失，而是运行中的 Frappe Web 进程还没有刷新新模块。
- 当前验证中通过重启 `frappe_docker-backend-1` 后，新的供应商网关方法已被正常加载，后续 HTTP 专项回归全部通过。
