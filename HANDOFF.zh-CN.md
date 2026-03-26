# 开发交接摘要

更新时间：2026-03-23

## 1. 当前已完成

### 1.1 销售侧网关

已实现并可用：

- `create_order`
- `submit_delivery`
- `create_sales_invoice`
- `search_product`
- `confirm_pending_document`
- `update_payment_status`
- `process_sales_return`

其中以下接口已支持 `request_id` 幂等：

- `create_order`
- `submit_delivery`
- `create_sales_invoice`
- `update_payment_status`
- `process_sales_return`

### 1.2 采购侧网关

已实现并完成主链路联调：

- `create_purchase_order`
- `receive_purchase_order`
- `create_purchase_invoice`
- `create_purchase_invoice_from_receipt`
- `record_supplier_payment`
- `process_purchase_return`

以上采购接口均已支持 `request_id` 幂等。

已实现并可用于采购前端的聚合 / 主数据 / 编辑能力：

- `get_purchase_order_detail_v2`
- `get_purchase_order_status_summary`
- `get_purchase_receipt_detail_v2`
- `get_purchase_invoice_detail_v2`
- `get_supplier_purchase_context`
- `list_suppliers_v2`
- `get_supplier_detail_v2`
- `update_purchase_order_v2`
- `update_purchase_order_items_v2`
- `cancel_purchase_order_v2`
- `cancel_purchase_receipt_v2`
- `cancel_purchase_invoice_v2`
- `cancel_supplier_payment`

## 2. 本轮已验证结果

在 devcontainer / ERPNext 运行环境中，已通过 Postman `v3` 集合完成以下验证：

- 采购订单创建成功
- 采购收货成功
- 采购发票创建成功
- 供应商付款成功
- 采购退货成功

幂等验证结论：

- 相同 `request_id` 重试时，返回第一次成功结果
- 修改新的 `request_id` 后，会按新业务请求执行
- 若原业务已被消费，则会触发真实业务校验错误，例如：
  - 无可收货明细
  - 无可开票明细
  - 物料已被退回

## 2.1 本次对话新增验证结果

本次对话中，已在宿主机通过 `python3 + HTTP` 方式，对 devcontainer 中运行的 ERPNext 服务进行了真实接口验证，而不是只做本地函数导入测试。

已完成的销售侧真实验证：

- `search_product`
- `create_order`
- `submit_delivery`
- `create_sales_invoice`
- `update_payment_status`
- `process_sales_return`

已完成的采购侧真实验证：

- `create_purchase_order`
- `receive_purchase_order`
- `create_purchase_invoice`
- `create_purchase_invoice_from_receipt`
- `record_supplier_payment`
- `process_purchase_return`

本次对话新增的采购侧代码调整：

- `receive_purchase_order` 支持按明细行改写实际收货数量与实际收货价格
- `receive_purchase_order` 支持在收货时移除未到货商品
- 新增 `create_purchase_invoice_from_receipt`，用于按收货单直接生成采购发票
- `create_purchase_invoice_from_receipt` 支持按收货明细改写开票数量与价格
- `process_purchase_return` 已补成按明细行优先、`item_code` 兜底处理
- 采购改价场景已增加 `maintain_same_rate` 主动设置校验，避免再次落成底层原生报错
- HTTP 结果文件改为合并写入，避免分步执行链路测试时覆盖前置返回值

本次对话新增的销售侧代码调整：

- `submit_delivery` 已支持按明细行优先改写数量与价格
- `create_sales_invoice` 已支持按明细行优先改写数量与价格
- `submit_delivery` 已支持 `force_delivery`
  - 正常路径仍先校验可用库存
  - 强制出货路径会跳过前置库存校验，并仅对本次发货涉及的物料临时打开 `allow_negative_stock`
- `process_sales_return` 已补成按明细行优先、`item_code` 兜底处理
- `get_sales_order_detail` 的 `items` 已补充返回 `image`，用于移动端订单详情直接展示商品图片，避免前端逐行补查 `Item`
- 商品已补正式昵称字段方案：`Item.custom_nickname`
- 新增 `get_product_detail_v2`，用于返回商品详情、图片、昵称、条码、库存、价格与换算单位
- 新增 `update_product_v2`，用于更新商品名称、昵称、描述、图片、启停状态与标准售价
- 新增 `list_products_v2`，用于返回商品工作台列表摘要、库存与多价格摘要
- `search_product_v2`、`list_products_v2`、`get_product_detail_v2` 现已补充：
  - 当前查询口径库存 `qty`
  - 总库存 `total_qty`
  - 分仓库存明细 `warehouse_stock_details`
- 商品详情编辑现已支持“调整当前仓库库存”
  - 前端传 `warehouse + warehouse_stock_qty`
  - 后端会先读取当前仓库存，再按差额创建正式库存调整单
  - 不直接覆写 `Bin.actual_qty`
- 新增 `create_product_v2`，用于标准商品建档，不自动创建入库单
- 新增 `disable_product_v2`，用于显式停用 / 启用商品
- 新增 `cancel_order_v2`，用于按 v2 语义作废销售订单，并统一屏蔽 ERPNext 原生取消动作细节
- 新增 `update_order_v2`，用于按 v2 模型更新销售订单头信息、联系人快照、收货快照与交货日期
- 新增 `update_order_items_v2`，用于按 v2 模型整体替换商品明细；对已提交且无下游单据的订单自动走 amendment 并返回新订单号
- `get_sales_order_detail` 的业务动作与履约聚合已修正：
  - `delivery.status` 不再固定返回 `unknown`
  - 已存在销售发票时，`actions.can_create_sales_invoice` 不再继续返回 `true`
  - 当前订单详情可直接返回下游业务单据引用：
    - `references.delivery_notes`
    - `references.sales_invoices`
- 销售订单备注已补正式字段方案：`Sales Order.custom_order_remark`
- `update_payment_status` 已扩展为完整结算分支：
  - 全额收款
  - 部分收款
  - 少收并结清（`settlement_mode = writeoff`）
  - 多收并保留未分配金额（`unallocated_amount`）
- `get_sales_order_detail` 的 `payment` 聚合已补齐：
  - `actual_paid_amount`
  - `total_writeoff_amount`
  - `latest_payment_entry`
  - `latest_payment_invoice`
  - `latest_unallocated_amount`
  - `latest_writeoff_amount`
  用于前端直接展示“实收金额 / 核销金额 / 额外收款”
- 新增发货单 / 发票详情聚合接口：
  - `get_delivery_note_detail_v2`
  - `get_sales_invoice_detail_v2`
  用于移动端直接展示来源订单、关联单据、商品明细与结算摘要
- 发货单 / 发票详情聚合已补齐“按来源订单兜底关联”：
  - 当销售发票不是直接基于 `Delivery Note` 生成，而是基于 `Sales Order` 生成时
  - 发货单详情仍可通过来源订单兜底找到对应销售发票
  - 发票详情也可通过来源订单兜底找到对应发货单
- 当前本地联调站点已手工补齐 3 个客户的主联系人与主收货地址，便于验证 `get_customer_sales_context`：
  - `Palmer Productions Ltd.`
  - `West View Software Ltd.`
  - `Grant Plastics Ltd.`

## 2026-03-26 客户模块后端补齐

本轮已补齐客户管理后端第一阶段接口：

- `list_customers_v2`
- `get_customer_detail_v2`
- `create_customer_v2`
- `update_customer_v2`
- `disable_customer_v2`

设计原则：

- 客户模块只维护客户主数据、默认联系人、默认地址
- 客户默认地址只作为开单默认建议值
- 订单地址仍然是订单自己的快照，后续发货单和发票继续继承订单快照

当前能力边界：

- 已支持客户列表、详情、新增、更新、停用
- 已支持通过同一接口同时维护默认联系人与默认地址
- 暂未扩展为 CRM 线索/跟进模块，当前定位仍是业务型主数据模块

本轮真实站点 CRUD 验证还额外修正了两个后端细节：

- `update_customer_v2` 在真实站点中会遇到 `TimestampMismatchError`，现已改成“先保存客户主数据，再更新联系人/地址，最后 reload 后回写主联系/主地址”的顺序
- `Contact` 的手机号 / 邮箱已改为通过 `phone_nos / email_ids` 子表写入，避免只写顶层字段导致详情回显为空

本次新增的幂等验证类型：

- 同一 `request_id` 顺序重放
- 同一 `request_id` 但不同请求数据
- 不同 `request_id` 且不同请求数据
- 并发条件下同一 `request_id`

当前结论：

- 销售侧主链路已跑通，且已覆盖顺序幂等、不同数据和并发幂等
- 销售侧部分发货、发货改价、部分开票、开票改价已跑通
- 销售侧按 `sales_invoice_item` 发起退货的真实 HTTP 验证已跑通
- 销售侧 `update_order_v2` 与 `update_order_items_v2` 已完成真实 HTTP 验证
- 销售侧 `cancel_order_v2` 已完成真实 HTTP 验证
- 采购侧新增聚合接口与供应商接口已完成定向单测验证
- 采购侧旧单测历史问题已收敛，当前 `test_purchase_service + test_gateway_wrappers` 已可全量通过
- 采购侧 HTTP 主链路已连续重跑两轮，当前未发现波动或幂等异常

## 2026-03-26 单位管理后端补齐

本轮已补齐单位管理后端第一阶段接口：

- `list_uoms_v2`
- `get_uom_detail_v2`
- `create_uom_v2`
- `update_uom_v2`
- `disable_uom_v2`
- `delete_uom_v2`

设计原则：

- 单位模块只维护 `UOM` 主数据本身
- 商品换算关系仍继续维护在 `Item.uoms / UOM Conversion Detail`
- 单位删除与关键规则修改必须带引用保护，不能当成无保护的普通 CRUD

当前能力边界：

- 已支持单位列表、详情、新增、更新、停用、删除
- 详情已返回 `usage_summary`，便于前端提示“该单位是否已被系统引用”
- 当前不支持直接改名；如需新名称，建议创建新单位
- 当前若单位已被引用，则不允许直接修改 `must_be_whole_number`
- 当前若单位已被引用，则不允许直接删除，建议改为停用

本轮真实站点 CRUD 验证已通过两组临时单位数据：

- 创建
- 列表查询（含模糊搜索）
- 详情查询
- 更新
- 停用 / 启用
- 删除

当前结论：

- 单位管理后端 CRUD 已完成并通过单测与真实站点验证
- 本轮还顺手修正了 `list_uoms_v2` 在真实站点里的模糊搜索问题
- 商品侧 `get_product_detail_v2` 与 `update_product_v2` 已完成真实 HTTP 验证
- 商品模块第一阶段后端能力已形成：
  - 列表
  - 标准建档
  - 详情
  - 更新
  - 停用
- 商品模块第二阶段基础模型已开始落地：
  - 商品详情 / 列表 / 搜索结果开始返回：
    - `wholesale_default_uom`
    - `retail_default_uom`
    - `sales_profiles`
  - 商品创建 / 更新已支持保存批发默认单位与零售默认单位
  - 新增 patch：
    - `myapp.patches.add_item_sales_mode_uom_fields`
    - 用于在 `Item` 上补齐商品模式默认单位字段
- 价格口径当前建议继续基于 ERPNext 原生：
  - `Price List`
  - `Item Price`
  - `valuation_rate`
- 当前约定：
  - 零售价：`Retail`
  - 批发价：`Wholesale`
  - 采购价：`Standard Buying`
  - 成本参考：`valuation_rate`
- 当前新增约定：
  - 订单头未来只保留默认销售模式入口
  - 真正成交口径应逐步收敛到订单行：
    - `sales_mode`
    - `uom`
    - `rate`
  - 商品主数据只提供模式默认值，不应强制锁死整张订单
- 该约定已进入真实后端模型，不再只是设计草案：
  - `Sales Order.custom_default_sales_mode`
  - `Sales Order Item.custom_sales_mode`
- 已完成真实链路验证：
  - 订单可同时包含批发行与零售行
  - 订单详情可正确返回：
    - `meta.default_sales_mode`
    - 行级 `sales_mode / uom / rate`
  - `Delivery Note` 与 `Sales Invoice` 不新增模式字段
  - 下游单据仅保留最终：
    - `uom`
    - `rate`
    - `qty`
- 多仓设计新增约定：
  - 商品搜索后续应逐步转向“商品优先、仓库内选”
  - 同商品不同仓库时，订单内部按 `商品 + 仓库` 分行
  - 数量和价格修改只作用于当前分仓行
  - 发货单继续按仓执行
  - 发票如需更简洁展示，优先做展示层聚合，不先合并底层分仓行
- 不建议将“商品默认优先仓库自动分配”作为主逻辑：
  - 可以有推荐仓库
  - 但最终分仓数量应允许人工决定
- 商品模块与订单模块的职责边界进一步明确：
  - 商品模块保持“商品为核心、仓库为展开维度”
  - 商品详情优先展示总库存、分仓库存、价格体系
  - 订单模块继续按 `商品 + 仓库` 分行执行
  - 若同商品在不同仓库最终成交价不同，先在订单行层面处理，不上升为商品主数据中的仓库级默认售价
- 当前商品详情里的库存修改能力，本质上是“单仓库存调整”：
  - 前端传 `warehouse + warehouse_stock_qty`
  - 后端按该仓库读取当前库存并生成正式库存调整单
  - 这不等于修改商品总库存
  - 若后续要给新仓分配库存，更推荐通过入库或调拨动作完成
- 2026-03-21 已完成真实站点验证：
  - 商品 CRUD、昵称、图片、多价格、停用 / 启用均通过
  - `search_product_v2 / list_products_v2 / get_product_detail_v2` 的 `total_qty / warehouse_stock_details` 返回通过
  - 同一商品拆成两个仓库订单行后，订单、发货单、发票单均保持两条分仓行，且允许不同仓库保留不同价格
- 销售订单详情聚合已按真实下游单据修正状态口径：
  - 已发货订单返回 `delivery.status = shipped`
  - 已开票订单不再暴露重复“开票”动作
- 销售结算链路已完成真实 HTTP 验证：
  - `test_update_payment_status_success`
  - `test_update_payment_status_idempotent_replay`
  - `test_update_payment_status_writeoff_success`
  - `test_update_payment_status_overpayment_success`
- 发货单 / 发票详情聚合已完成定向服务测试与 gateway wrapper 测试：
  - `test_get_delivery_note_detail_returns_references_and_items`
  - `test_get_sales_invoice_detail_returns_payment_and_references`
  - `test_get_delivery_note_detail_v2_passes_name_to_service`
  - `test_get_sales_invoice_detail_v2_passes_name_to_service`
- 强制出货已完成定向服务测试：
  - `test_submit_delivery_force_delivery_skips_stock_precheck`
- 单据互相关联兜底已完成定向服务测试：
  - `test_build_delivery_note_references_falls_back_to_sales_order_invoices`
  - `test_build_sales_invoice_references_falls_back_to_sales_order_delivery_notes`
- 采购侧主链路已跑通，且已覆盖顺序幂等、不同数据和并发幂等
- 采购部分收货、基于收货单的部分开票、基于收货单的部分退货已跑通
- 当前测试已经基本覆盖两条主链路在现阶段最关键的使用场景
- 更复杂的边界测试可放在后续迭代补充

## 2.2 2026-03-23 销售单位换算与库存链路补充

本轮新增背景：

- 在销售链路审查中，发现 `submit_delivery` 的库存预检存在单位口径风险
- 创建订单 / 修改订单商品明细时，后端已能把 `qty + uom` 换算成：
  - `conversion_factor`
  - `stock_qty`
  - `stock_uom`
- 但发货前预检如果仍直接按业务数量 `qty` 校验，就可能在批发单位场景下少算库存需求

本轮已完成的后端修正：

- `myapp/services/order_service.py`
  - `submit_delivery` 的库存预检已改为优先按库存口径校验
  - 当前规则：
    - 优先 `stock_qty`
    - 若缺失则回退 `qty * conversion_factor`
    - 最后才退回原始 `qty`

本轮新增的回归测试：

- `myapp/tests/unit/test_order_service.py`
  - 新增定向单元测试，确认发货预检在存在 `stock_qty` 时按库存口径校验
- `myapp/tests/integration/test_sales_uom_stock_chain.py`
  - 新增真实站点上下文回归测试，覆盖：
    - 批发单位建单并发货
    - 零售单位建单并发货
    - 修改订单单位 / 数量后再发货
    - 批发单位库存不足拦截

本轮真实链路验证结论：

- 批发单位 `2 Box` 建单后，订单行正确换算为 `24 Nos`
- 发货后：
  - `Bin.actual_qty`
  - `Stock Ledger Entry.actual_qty`
  均按 `24 Nos` 扣减
- 零售单位 `5 Nos` 建单后，发货按 `5 Nos` 扣减库存
- 订单从 `1 Box` 改成 `7 Nos` 后，发货按更新后的 `7 Nos` 扣减库存
- `11 Box` 对 `120 Nos` 库存发货时，会按 `132 Nos` 需求量被正确拦截，且库存不变

本轮确认的实现细节：

- `update_order_items_v2` 不是原单原地改行
- 对已提交订单，会先作废原单，再生成 amendment 新单
- 因此更新商品明细后，后续发货 / 开票 / 详情查询应使用返回的新订单号，而不是旧订单号

测试与运行注意事项：

- 在 backend 容器里跑 Python 测试时，不要误用系统 Python
- 应使用：
  - `/home/frappe/frappe-bench/env/bin/python`
- 真实站点上下文回归推荐命令：

```bash
docker exec frappe_docker-backend-1 bash -lc '
  cd /home/frappe/frappe-bench &&
  env/bin/python -m unittest apps.myapp.myapp.tests.integration.test_sales_uom_stock_chain
'
```

## 3. 已新增或更新的重要文件

### 3.1 代码

- `myapp/services/purchase_service.py`
- `myapp/api/purchase_api.py`
- `myapp/api/gateway.py`
- `myapp/api/api.py`
- `myapp/api/__init__.py`
- `myapp/services/__init__.py`

### 3.2 测试

- `myapp/tests/http/test_gateway_http.py`
- `myapp/tests/http/test_gateway_v2_http.py`
- `myapp/tests/unit/test_purchase_service.py`
- `myapp/tests/unit/test_gateway_wrappers.py`
- `myapp/tests/unit/test_idempotency.py`
- `myapp/tests/unit/test_order_service.py`
- `myapp/tests/unit/test_settlement_service.py`

### 3.3 文档

- `API_GATEWAY.zh-CN.md`
- `API_GATEWAY.md`
- `TESTING.zh-CN.md`
- `WHOLESALE_TECH_DESIGN.zh-CN.md`
- `PURCHASE_TECH_DESIGN.zh-CN.md`
- `README.zh-CN.md`
- `README.md`
- `.env.http-test.example`
- `http-test-results.json`

### 3.4 Postman

- `postman/myapp-gateway-v3.postman_collection.json`
- `postman/myapp-local-v3.postman_environment.json`

## 4. 近期关键提交

- `e33ebca` `fix: pass idempotency keys through API wrappers`
- `1c98f39` `feat: add idempotency to fulfillment and return flows`
- `a19170a` `docs: update idempotency coverage`
- `c87ca81` `feat: add purchase gateway flow`
- `af01407` `docs: link purchase design from wholesale baseline`
- `bce2cff` `docs: refine frontend and printing strategy`

## 5. 当前前端与打印方向

已达成的设计结论：

- 前端优先面向管理员、内勤、仓管人员
- 移动端 / 平板端优先，重点承载扫码、收货、入库、发货、确认、打印预览
- 桌面 Web 端保留，用于查询、追踪、补打、较大单据打印
- ERPNext 后台继续负责主数据、财务底层、系统配置和复杂管理
- 当前不计划做完整替代 ERPNext 的独立管理后台

打印策略结论：

- 单据以半 A4 到 A4 这类较大格式为主，不是小票为主
- 模板预先固定，移动端只需要预览确认，不让用户手动调缩放和页面尺寸
- 第一阶段优先兼容主流品牌打印机，不追求全品牌全协议覆盖
- 打印设备连接方式后续按实际设备收敛，不先做无限兼容

## 5.1 当前前端集成约定补充

为避免后续前后端各自演进后出现交互口径漂移，当前销售侧前端集成约定补充如下：

- 销售订单详情页不应直接静默执行 `submit_delivery` 或 `create_sales_invoice`
- 更推荐的交互方式是：
  - 订单详情页只负责跳转到独立确认页
  - 发货确认页负责调用 `submit_delivery`
  - 开票确认页负责调用 `create_sales_invoice`
- 这样做的主要原因是：
  - 下游单据属于正式业务事实单据
  - 用户通常需要先核对来源订单、客户快照、商品明细与金额
  - 直接从详情页右上角一步落单，容易让用户误以为只是“查看下一个页面”

当前移动端销售侧页面分工建议：

- `Sales Order` 详情页：
  - 以订单状态、履约状态、编辑入口和下游单据跳转为主
- `Delivery Note` 页面：
  - 在“未创建发货单”时优先作为发货确认页
  - 在“已存在发货单”时作为发货单详情页
- `Sales Invoice` 页面：
  - 优先朝“预览化单据页”建设
  - 用户进入后应尽快看到接近真实票据的版式，而不是只看到流程卡片

当前销售地址快照约定补充：

- 客户默认地址只作为创建订单时的初始建议值
- 一旦订单已创建，后续真实地址应以订单自己的地址快照为准
- 不应在订单详情、发货单详情、发票详情中再次回退客户默认地址
- `create_order_v2` / `update_order_v2` / `update_order_items_v2`
  - 现在都应保证订单地址快照可持续回读
- `submit_delivery` / `create_sales_invoice`
  - 现在都应从来源订单继承地址快照
  - 不应因为下游单据生成再次退回客户默认地址

当前收款入口兼容约定补充：

- 销售收款页当前兼容两组跳转参数：
  - `referenceName` + `defaultPaidAmount`
  - `salesInvoice` + `amount`
- 这是为了兼容订单页入口与发票页入口的历史差异
- 长期建议仍然是统一收敛到一套参数命名

当前销售回退链路补充：

- 已新增两个显式回退接口：
  - `cancel_sales_invoice`
  - `cancel_delivery_note`
- 当前建议的回退顺序：
  - 已开票时先作废销售发票
  - 发票回退完成后，再作废发货单
  - 发货单回退完成后，订单重新回到可继续编辑 / 发货状态
- 发货单详情聚合现在会返回：
  - `actions.can_cancel_delivery_note`
  - `actions.cancel_delivery_note_hint`
- 销售发票详情聚合现在会返回：
  - `actions.can_cancel_sales_invoice`
  - `actions.cancel_sales_invoice_hint`
- 前端不应再自己猜测“当前能否作废”，应按详情接口动作位直接渲染
- 当前环境下的真实验证结果：
  - 作废销售发票后，发货单会重新允许作废
  - 作废发货单后，订单 `delivery.status` 会回到 `pending`
  - 订单会重新暴露 `can_submit_delivery = true`
- 当前环境里，已收款销售发票也能成功作废：
  - 这表明站点当前允许作废发票时自动处理收款引用解绑
  - 但这属于环境配置行为，前端仍应保留风险提示，不应写死“已收款一定能作废”

当前快捷链路接口补充：

- 已新增两个独立聚合接口：
  - `quick_create_order_v2`
  - `quick_cancel_order_v2`
- `quick_create_order_v2` 的定位：
  - 面向前端“快速开单”按钮
  - 后端固定按快捷模式执行：
    - 创建订单
    - 自动发货
    - 自动开票
  - 当前已补充快捷链路的强制出货分支：
    - 默认仍先走普通库存校验
    - 若前端在快捷开单时收到库存不足错误，可再次调用并传 `force_delivery=1`
    - 后端会跳过创建阶段的普通库存前置拦截，并在自动发货阶段透传强制出货
  - 语义上独立于 `create_order_v2(immediate=1)`，避免前端继续直接依赖底层联动参数
- `quick_cancel_order_v2` 的定位：
  - 面向前端“快速作废 / 回退并修改”
  - 默认按安全顺序执行：
    - `cancel_payment_entry`
    - `cancel_sales_invoice`
    - `cancel_delivery_note`
  - 返回订单详情快照，便于回到订单继续修改
- 当前限制：
  - 先只支持标准快捷链路
  - 若检测到多张发票、多张发货单，或一笔收款关联多张发票：
    - 快捷回退会直接拦截
    - 要求改用分步回退流程

当前收款回退能力补充：

- 已新增显式接口：
  - `cancel_payment_entry`
- 该接口用于“作废收款单 / 回退收款登记”：
  - 适合在用户发现收款登记错误、需要重新结算时使用
- 当前真实验证结果：
  - `Payment Entry` 作废后，收款单 `docstatus` 会变成 `2`
  - 对应销售发票的 `outstanding_amount` 会恢复
- 当前边界也要明确：
  - 这仍是“收款回退”，不是完整的银行退款/出账凭证流程
  - 如果后续业务需要记录真实退款资金流，还应补“反向付款/退款凭证”能力

关于打印入口的当前约定：

- 打印入口优先落在销售发票详情页 / 发票预览页
- 移动端当前优先做：
  - 固定模板预览
  - 预览后确认打印
- 当前阶段还未承诺：
  - 真实系统打印已全量接通
  - PDF 导出 / 分享已完整可用
- 但页面结构应预留：
  - `打印预览`
  - `补打`
  - `分享/PDF`
  等后续扩展位

## 6. 当前未完成但已明确的方向

### 6.1 销售与商品侧

- 2026-03-22 商品模块前后端对齐结论
  - 当前移动端商品详情页已完成第二轮可用性优化：
    - 库存区收敛为“单一当前仓库 + 目标库存 + 预计变动”
    - 仓库切换改为独立选择面板，不再在正文中平铺全部仓库
    - 停用操作已移入危险区
    - 批发 / 零售默认单位已改为受控选择，不再依赖自由文本
    - 前端已复用统一单位展示映射，并开始展示后端已有的单位换算提示
    - 商品详情页与商品创建页现已补齐：
      - 商品分类
      - 品牌
      - 主条码
      的正式录入入口
  - 当前后端已经足够支持：
    - 商品列表
    - 商品详情
    - 商品标准建档
    - 商品基础信息更新
    - 商品分类 / 品牌 / 主条码读写
    - 库存基准单位写入
    - 商品单位换算写入与回读
    - 单仓库存调整
    - 批发 / 零售默认单位保存
    - 单位换算信息读取
    - 销售单 / 采购单按 `qty + uom` 录入后自动换算到库存基准单位
    - 商品建档入库 / 单仓库存调整按指定业务单位录入后自动换算到库存基准单位
  - 当前后端仍未支持：
    - 商品规格 / 变体能力的正式网关化
  - 当前结论：
    - 若仅做前端展示与规则解释，后端现有接口已基本够用
    - “单位与换算”写入能力已补到 `create_product_v2 / update_product_v2`
    - 交易侧已补“服务层统一换算”，前端不再需要自己决定最终库存口径
    - 下一步主要是前端把这套能力接到正式配置界面
    - 若要支持 500ml / 750ml / 1L 这类规格经营，建议优先走“独立 SKU / 变体”路线，不建议仅靠商品名硬编码

- 单位换算交易规则补强
- 批次与保质期管理
- 商品搜索增强（分仓库存、最近成交价、专属价等）

### 6.2 采购侧

- 采购部分收货 / 部分开票 / 部分退货的更完整测试
- 后续若进入质检、拒收、批次、效期场景，可能需要新增字段或 DocType

### 6.3 前端侧

- 需要确定移动端技术栈
- 需要确定打印机品牌 / 型号 / 连接方式范围
- 需要明确扫码方案与打印方案是系统打印、插件打印还是厂商能力

## 7. 下一步建议

如果继续后端：

1. 补采购边界场景测试
2. 补商品“单位与换算”写入接口设计
3. 开始批次 / 保质期规则设计
4. 评估按明细行标识而非纯 `item_code` 处理部分退货

如果转前端：

1. 补商品创建页与商品详情页的单位交互一致性
2. 补商品分类 / 品牌 / 条码等基础主数据编辑
3. 明确商品规格 / 变体第一版方案
4. 明确打印机设备范围后再做打印能力接入

## 8. 开发与测试环境提示

当前项目以 VS Code devcontainer / Docker 中的 ERPNext 环境作为开发基准，不以宿主机 WSL 直接导入 Frappe 应用运行结果作为唯一依据。

当前建议的接口测试方式：

- 宿主机使用 `python3`
- 通过 HTTP 访问 `http://localhost:8080`
- 优先测试 `myapp.api.gateway.*` 对外入口

已补充：

- HTTP 冒烟测试文件：`myapp/tests/http/test_gateway_http.py`
- 环境变量示例文件：`.env.http-test.example`

推荐使用方式：

1. 复制 `.env.http-test.example` 为 `.env.http-test`
2. 配置测试账号密码或 API Token
3. 在仓库根目录执行 `python3 apps/myapp/myapp/tests/http/test_gateway_http.py`

补充说明：

- 当前 HTTP 测试文件已经覆盖全部 `myapp.api.gateway.*` 接口的基础测试入口
- 可按单个测试方法执行，不必一次跑完整个文件
- 测试默认会打印并保存接口响应，便于多接口链路联调时复用返回值
- 已支持从结果文件中读取上一步接口返回值，供链路测试复用
- 当前返回值结果文件为 `apps/myapp/http-test-results.json`
- `myapp/tests/http/test_gateway_http.py` 已重构为“每个链路测试自行创建前置数据”，避免固定 `request_id`、历史结果文件和执行顺序互相污染
- `myapp/tests/http/test_gateway_v2_http.py` 已补充商品工作台与销售状态聚合相关 v2 测试
- 已重新验证单条接口、销售链路、采购链路、幂等/并发以及整份文件全量回归
- 当前整份 HTTP 测试文件全量结果为 `Ran 47 tests ... OK`
- 当前 v2 HTTP 测试文件全量结果为 `Ran 110 tests in 22.280s ... OK`

## 9. 当前测试覆盖说明

目前测试分为两层：

- `myapp/tests/http/`
  用于 HTTP 冒烟测试、销售链路、采购链路、幂等和并发验证
- `myapp/tests/unit/`
  用于服务层和工具函数的单元测试

当前已经完成的链路级测试重点：

- 销售主链路成功测试
- 销售幂等 replay 测试
- 销售不同数据测试
- 销售并发幂等测试
- v2 商品创建并入库成功测试
- v2 商品条码 / 昵称搜索测试
- v2 商品幂等 replay / 不同数据 / 并发幂等测试
- v2 商品负数数量与重复条码校验测试
- v2 销售订单详情聚合测试
- v2 销售订单状态摘要测试
- v2 商品到销售单的轻链路 smoke test
- 采购主链路成功测试
- 采购幂等 replay 测试
- 采购不同数据测试
- 采购并发幂等测试

## 10. 注意事项

- 宿主机执行 HTTP 测试时，应使用 `python3`，不要使用 `python`
- 宿主机侧测试目标地址按当前约定使用 `http://localhost:8080`
- backend 容器内直接执行 HTTP 测试时，应显式改用 `http://localhost:8000`
- 测试文件会直接打印接口返回值，同时将完整响应写入 `http-test-results.json`
- `http-test-results.json` 中保存的是完整响应体，后续链路测试会从该文件中读取上一步结果
- 日志中若出现 `422`，需要先区分这是预期校验失败还是主链路失败；例如探测不存在供应商时返回 `422` 属于正常现象
- 当前顺序幂等、不同数据和并发幂等都已做真实 HTTP 验证，采购侧的部分收货、部分开票、部分退货也已补到第一版
- 若采购业务要求在收货或开票时直接改价，需先在 ERPNext `Buying Settings` 中关闭 `maintain_same_rate`
- 当前环境的 `Selling Settings.maintain_same_sales_rate = 0`，因此销售侧允许在发货和开票阶段按实际成交情况改价
- 目前宿主机侧建议优先执行 HTTP 测试；`tests/unit` 中直接依赖 `frappe` 的单元测试仍应在 devcontainer / bench 环境内执行
- 2026-03-25 起，商品建档 / 更新时会额外校验：
  - `wholesale_default_uom`
  - `retail_default_uom`
  - 以上默认成交单位必须能通过 `uom_conversions` 换算到 `stock_uom`
  - 不再允许保存“默认成交单位已配置，但缺少到库存基准单位换算关系”的商品主数据
- 2026-03-25 本轮回归结论：
  - 新增规则定向测试已通过
  - 经典 HTTP 全链路结果：
    - `Ran 49 tests in 33.298s ... OK`
  - v2 HTTP 全链路结果：
    - `Ran 119 tests in 55.746s ... OK`
  - 当前没有证据表明本轮新增商品单位校验影响销售主链路
  - `tests/integration/test_sales_uom_stock_chain.py` 在当前环境下仍可能遭遇 `tabSeries` 锁冲突，该问题属于站点命名序列竞争，不作为本轮业务回归失败结论
