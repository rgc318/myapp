## API 网关文档

推荐使用以下自定义接口入口：

- 销售与商品：
- `myapp.api.gateway.search_product`
- `myapp.api.gateway.search_product_v2`
- `myapp.api.gateway.create_product_and_stock`
- `myapp.api.gateway.create_product_v2`
- `myapp.api.gateway.get_product_detail_v2`
- `myapp.api.gateway.list_products_v2`
- `myapp.api.gateway.update_product_v2`
- `myapp.api.gateway.disable_product_v2`
- `myapp.api.gateway.create_order`
- `myapp.api.gateway.create_order_v2`
- `myapp.api.gateway.quick_create_order_v2`
- `myapp.api.gateway.quick_cancel_order_v2`
- `myapp.api.gateway.cancel_order_v2`
- `myapp.api.gateway.get_customer_sales_context`
- `myapp.api.gateway.list_customers_v2`
- `myapp.api.gateway.get_customer_detail_v2`
- `myapp.api.gateway.create_customer_v2`
- `myapp.api.gateway.update_customer_v2`
- `myapp.api.gateway.disable_customer_v2`
- `myapp.api.gateway.get_sales_order_detail`
- `myapp.api.gateway.get_sales_order_status_summary`
- `myapp.api.gateway.get_delivery_note_detail_v2`
- `myapp.api.gateway.get_sales_invoice_detail_v2`
- `myapp.api.gateway.submit_delivery`
- `myapp.api.gateway.cancel_delivery_note`
- `myapp.api.gateway.create_sales_invoice`
- `myapp.api.gateway.cancel_sales_invoice`
- `myapp.api.gateway.update_payment_status`
- `myapp.api.gateway.cancel_payment_entry`
- `myapp.api.gateway.process_sales_return`

- 采购与结算：
- `myapp.api.gateway.create_purchase_order`
- `myapp.api.gateway.quick_create_purchase_order_v2`（规划中）
- `myapp.api.gateway.receive_purchase_order`
- `myapp.api.gateway.create_purchase_invoice`
- `myapp.api.gateway.create_purchase_invoice_from_receipt`
- `myapp.api.gateway.record_supplier_payment`
- `myapp.api.gateway.process_purchase_return`
- `myapp.api.gateway.quick_cancel_purchase_order_v2`（规划中）
- `myapp.api.gateway.create_supplier_v2`
- `myapp.api.gateway.update_supplier_v2`
- `myapp.api.gateway.disable_supplier_v2`

- 通用辅助：
- `myapp.api.gateway.confirm_pending_document`

本文档主结构按业务模块划分，而不是按“自定义接口 / 官方接口”二分。

原因：

- 调用方首先关心“销售要调哪些接口、采购要调哪些接口”
- 后续前端页面、测试用例和实施手册也更适合按模块对齐
- ERPNext / Frappe 原生接口更适合作为底层映射说明，而不是主阅读路径

本文档只覆盖本应用的自定义接口。ERPNext / Frappe 原生接口不作为主接口文档展开，仅在必要时说明底层映射关系。

### 模块导航

- 销售与商品：`search_product`、`search_product_v2`、`create_product_and_stock`、`create_product_v2`、`list_products_v2`、`get_product_detail_v2`、`update_product_v2`、`disable_product_v2`、`get_customer_sales_context`、`list_customers_v2`、`get_customer_detail_v2`、`create_customer_v2`、`update_customer_v2`、`disable_customer_v2`、`create_order`、`create_order_v2`、`quick_create_order_v2`、`quick_cancel_order_v2`、`get_sales_order_detail`、`get_sales_order_status_summary`、`search_sales_orders_v2`、`get_delivery_note_detail_v2`、`get_sales_invoice_detail_v2`、`submit_delivery`、`cancel_delivery_note`、`create_sales_invoice`、`cancel_sales_invoice`、`update_payment_status`、`cancel_payment_entry`、`process_sales_return`
- 采购与结算：`create_purchase_order`、`receive_purchase_order`、`create_purchase_invoice`、`create_purchase_invoice_from_receipt`、`record_supplier_payment`、`process_purchase_return`
- 采购快捷链路（规划中）：`quick_create_purchase_order_v2`、`quick_cancel_purchase_order_v2`
- 采购聚合与供应商：`get_purchase_order_detail_v2`、`get_purchase_order_status_summary`、`search_purchase_orders_v2`、`get_purchase_receipt_detail_v2`、`get_purchase_invoice_detail_v2`、`get_supplier_purchase_context`、`list_suppliers_v2`、`get_supplier_detail_v2`、`create_supplier_v2`、`update_supplier_v2`、`disable_supplier_v2`
- 采购更新与作废：`update_purchase_order_v2`、`update_purchase_order_items_v2`、`cancel_purchase_order_v2`、`cancel_purchase_receipt_v2`、`cancel_purchase_invoice_v2`、`cancel_supplier_payment`
- 报表与分析：`get_business_report_v1`、`get_cashflow_report_v1`、`list_cashflow_entries_v1`
- 通用辅助：`confirm_pending_document`

### 统一成功响应格式

所有 `myapp.api.gateway.*` 方法成功时都返回同一包络：

```json
{
  "ok": true,
  "status": "success",
  "code": "ORDER_CREATED",
  "message": "业务提示信息",
  "data": {},
  "meta": {}
}
```

说明：

- `data`：主业务数据
- `meta`：辅助信息，例如筛选条件

### 统一错误响应格式

`myapp.api.gateway.*` 现在会针对常见业务错误返回统一错误包络：

```json
{
  "ok": false,
  "status": "error",
  "code": "VALIDATION_ERROR",
  "message": "具体错误信息",
  "data": {},
  "meta": {}
}
```

当前已映射错误码：

- `VALIDATION_ERROR`
- `PERMISSION_DENIED`
- `AUTHENTICATION_REQUIRED`
- `RESOURCE_NOT_FOUND`
- `DUPLICATE_ENTRY`
- `WORKFLOW_ACTION_INVALID`
- `INSUFFICIENT_STOCK`
- `INTERNAL_ERROR`

对这些自定义网关接口，HTTP 状态码也会尽量对齐：

- `401` 需要认证
- `403` 权限不足
- `404` 资源不存在
- `409` 重复、工作流冲突、库存不足
- `422` 参数或业务校验失败
- `500` 系统内部错误

### 报表与分析接口补充说明

当前报表域的一期正式化拆分包含：

- `get_business_report_v1`
  - 统一经营报表聚合接口
  - 保留总览、销售、采购、应收应付和资金趋势等整包数据
- `get_cashflow_report_v1`
  - 只返回资金总览和资金趋势
  - 适合移动端资金趋势图或资金模块首页
- `list_cashflow_entries_v1`
  - 只返回资金流水明细
  - 支持分页参数：
    - `page`
    - `page_size`
  - 返回分页信息：
    - `page`
    - `page_size`
    - `total_count`
    - `has_more`

当前资金口径：

- 基于 `Payment Entry`
- 日期字段使用 `posting_date`
- `payment_type = 'Receive'` 计入收入
- `payment_type = 'Pay'` 计入支出
- 其他类型当前归类为 `transfer`

更完整的拆分思路与正式化边界，请参见 `REPORTS_TECH_DESIGN.zh-CN.md`。

### 调用示例

Frappe Desk / 前端调用：

```javascript
frappe.call({
  method: "myapp.api.gateway.search_product",
  args: {
    search_key: "Camera",
    warehouse: "Stores - RD",
  },
}).then((r) => {
  console.log(r.message);
});
```

HTTP 调用示例：

```bash
curl -X POST https://your-site.example.com/api/method/myapp.api.gateway.search_product \
  -H "Authorization: token api_key:api_secret" \
  -H "Content-Type: application/json" \
  -d '{
    "search_key": "Camera",
    "warehouse": "Stores - RD"
  }'
```

错误响应示例：

```json
{
  "ok": false,
  "status": "error",
  "code": "INSUFFICIENT_STOCK",
  "message": "商品 SKU010 在仓库 成品 - R 没有库存记录，系统按可用库存 0 处理，本次需要 1.0。",
  "data": {},
  "meta": {}
}
```

### search_product

方法：

- `myapp.api.gateway.search_product`

参数：

- `search_key: str`
- `price_list: str = "Standard Selling"`
- `currency: str | None = None`
- `warehouse: str | None = None`
- `company: str | None = None`
- `limit: int = 20`

行为：

- 支持按条码、物料编码、物料名称搜索
- 传 `warehouse` 时返回该仓库库存
- 不传 `warehouse`、传 `company` 时汇总该公司下所有仓库库存
- 都不传时汇总全仓库存

示例：

```python
from myapp.api.gateway import search_product

search_product(
    search_key="Camera",
    warehouse="Stores - RD",
)
```

Frappe Desk / 前端调用：

```javascript
frappe.call({
  method: "myapp.api.gateway.search_product",
  args: {
    search_key: "Camera",
    company: "rgc (Demo)",
    price_list: "Standard Selling",
  },
}).then((r) => {
  const payload = r.message;
  console.log(payload.data, payload.meta.filters);
});
```

### create_order

方法：

- `myapp.api.gateway.create_order`

参数：

- `customer: str`
- `items: list[dict] | json-string`
- `immediate: bool = False`
- `request_id: str | None`
- `company: str | None`
- `delivery_date: str | None`
- `transaction_date: str | None`
- `default_warehouse: str | None`
- `currency: str | None`
- `selling_price_list: str | None`
- `po_no: str | None`
- `remarks: str | None`

明细字段：

- `item_code`
- `qty`
- `warehouse`
- `uom` 可选
- `price` 可选
- `delivery_date` 可选

### quick_create_purchase_order_v2

方法：

- `myapp.api.gateway.quick_create_purchase_order_v2`

行为：

- 一次调用完成采购主链路的快捷编排能力
- 与销售侧 `quick_create_order_v2` 保持同类语义
- 支持按参数决定是否继续执行：
  - 收货
  - 开票
  - 付款

参数：

- `supplier: str`
- `items: list[dict] | json-string`
- `request_id: str | None`
- `immediate_receive: bool = False`
- `immediate_invoice: bool = False`
- `immediate_payment: bool = False`
- `mode_of_payment: str | None`
- `reference_no: str | None`
- `reference_date: str | None`
- `include_detail: bool | None`

返回：

- `purchase_order`
- `purchase_receipt`（可为空）
- `purchase_invoice`（可为空）
- `payment_entry`（可为空）
- `completed_steps: list[str]`
- `detail`
- `detail_included`

说明：

- 默认返回精简结果，不主动附带完整 `detail`
- 若调用方明确传入 `include_detail=1`，才会额外返回完整采购订单详情
- 需要在成功响应后直接读取 `actions`、`references`、`document_status` 等详情字段的调用方，必须显式传入 `include_detail=1`

### quick_cancel_purchase_order_v2

方法：

- `myapp.api.gateway.quick_cancel_purchase_order_v2`

行为：

- 一次调用按安全逆序回退采购链路
- 与销售侧 `quick_cancel_order_v2` 保持同类语义

建议参数：

- `order_name: str`
- `rollback_payment: bool = True`
- `request_id: str | None`
- `include_detail: bool | None`

当前回退顺序：

1. `Payment Entry`
2. `Purchase Invoice`
3. `Purchase Receipt`
4. `Purchase Order`

- 返回：

- `order`
- `cancelled_payment_entries`
- `cancelled_purchase_invoice`
- `cancelled_purchase_receipt`
- `completed_steps: list[str]`
- `detail`
- `detail_included`

说明：

- 默认返回精简结果，不主动附带完整 `detail`
- 若调用方明确传入 `include_detail=1`，才会额外返回完整采购订单详情

单位处理说明：

- 明细仍按前端传入的 `qty + uom` 建模
- 后端会根据商品 `stock_uom + uom_conversions` 自动补齐：
  - `conversion_factor`
  - `stock_qty`
  - `stock_uom`
- 若 `uom` 为空，则默认按商品库存基准单位处理
- 若 `uom` 已传但商品未配置对应换算系数，接口会直接报错

行为：

- 创建并提交 `Sales Order`
- `immediate=True` 时继续创建并提交 `Delivery Note` 和 `Sales Invoice`
- 在服务层提前校验仓库与公司归属
- 在即时发货前提前校验库存
- 当 `immediate=True` 且使用相同 `request_id` 重试时，直接返回第一次成功结果，不重复创建单据

测试建议：

- 如果后续要单独调用 `submit_delivery` 和 `create_sales_invoice`，请把 `immediate` 设为 `0`
- 如果 `immediate=1`，同一个 `Sales Order` 除非仍有剩余可发货或可开票数量，否则不要再次调用这两个接口
- `request_id` 是请求幂等键，不是业务单据主键
- 只有在重试同一笔业务动作时，才应复用同一个 `request_id`

示例：

```python
from myapp.api.gateway import create_order

create_order(
    customer="Palmer Productions Ltd.",
    items=[{"item_code": "SKU010", "qty": 1, "warehouse": "Stores - RD"}],
    company="rgc (Demo)",
    immediate=True,
)
```

HTTP 调用示例：

```bash
curl -X POST https://your-site.example.com/api/method/myapp.api.gateway.create_order \
  -H "Authorization: token api_key:api_secret" \
  -H "Content-Type: application/json" \
  -d '{
    "customer": "Palmer Productions Ltd.",
    "items": [
      {
        "item_code": "SKU010",
        "qty": 1,
        "warehouse": "Stores - RD"
      }
    ],
  "company": "rgc (Demo)",
  "immediate": 1
  }'
```

### create_order_v2

方法：

- `myapp.api.gateway.create_order_v2`

参数：

- `customer: str`
- `items: list[dict] | json-string`
- `immediate: bool = False`
- `request_id: str | None`
- `company: str | None`
- `delivery_date: str | None`
- `transaction_date: str | None`
- `default_warehouse: str | None`
- `currency: str | None`
- `selling_price_list: str | None`
- `po_no: str | None`
- `remarks: str | None`
- `customer_info: dict | json-string | None`
- `shipping_info: dict | json-string | None`

明细字段：

- `item_code`
- `qty`
- `warehouse`
- `uom` 可选
- `price` 可选
- `delivery_date` 可选

`customer_info` 当前建议字段：

- `contact_person`
- `contact_display_name`
- `contact_phone`
- `contact_email`

`shipping_info` 当前建议字段：

- `receiver_name`
- `receiver_phone`
- `shipping_address_name`
- `shipping_address_text`

行为：

- `immediate=False` 时仅创建并提交 `Sales Order`
- `immediate=True` 时继续联动创建并提交 `Delivery Note` 与 `Sales Invoice`
- 适合作为“分步处理 / 联动处理”共用的底层下单接口

### quick_create_order_v2

方法：

- `myapp.api.gateway.quick_create_order_v2`

参数：

- 与 `create_order_v2` 基本一致
- 不需要显式传 `immediate`

行为：

- 后端固定按快捷模式执行：
  - 创建并提交 `Sales Order`
  - 自动创建并提交 `Delivery Note`
  - 自动创建并提交 `Sales Invoice`
- 支持可选参数：
  - `force_delivery: int | bool | None = 0`
- 当 `force_delivery=1` 时：
  - 快捷开单会跳过创建阶段的普通库存前置拦截
  - 自动发货阶段会透传 `force_delivery=1` 给 `submit_delivery`
  - 整体仍保持：
    - 创建订单
    - 自动发货
    - 自动开票
- 返回：
  - `order`
  - `delivery_note`
  - `sales_invoice`
  - `force_delivery`
  - `completed_steps`
  - `detail`
  - `detail_included`
- 默认返回精简结果，不主动附带完整 `detail`
- 若调用方明确传入 `include_detail=1`，才会额外返回完整订单详情
- 当前定位：
  - 这是面向前端“快速开单”按钮的独立聚合接口
  - 用来避免前端自己拼 `create_order_v2(immediate=1)` 的流程语义

测试建议：

- 快速开单前仍建议优先确认所选仓库具备可用库存
- 若前端在快捷开单时收到库存不足错误：
  - 应先把它当成业务决策点
  - 再由用户决定是否改为 `force_delivery=1`
- 建议前端在成功后直接落到发票详情页
- 若只想保留标准下单，不自动发货开票，请继续使用 `create_order_v2(immediate=0)`

### quick_cancel_order_v2

方法：

- `myapp.api.gateway.quick_cancel_order_v2`

参数：

- `order_name: str`
- `rollback_payment: bool = True`
- `request_id: str | None`

行为：

- 这是面向前端“快速作废 / 回退并修改”的独立聚合接口
- 默认按安全顺序回退：
  - 先作废 `Payment Entry`
  - 再作废 `Sales Invoice`
  - 再作废 `Delivery Note`
- 返回：
  - `cancelled_payment_entries`
  - `cancelled_sales_invoice`
  - `cancelled_delivery_note`
  - `completed_steps`
  - `detail`
  - `detail_included`
- 默认返回精简结果，不主动附带完整 `detail`
- 若调用方明确传入 `include_detail=1`，才会额外返回完整订单详情

当前限制：

- 先只支持标准快捷链路：
  - 单订单
  - 单发货单
  - 单发票
  - 单收款单
- 若发现多张发票、多张发货单或一笔收款关联多张发票：
  - 接口会明确拦截
  - 提示改用分步回退流程

- 创建并提交 `Sales Order`
- 保留旧 `create_order` 的仓库归属、库存和即时出单校验逻辑
- 支持在创建时显式传入客户联系人快照和收货信息快照
- 当前会把可映射字段写入订单标准联系人 / 地址展示字段
- 若仅传入 `shipping_address_text` 而未传 `shipping_address_name`
  - 接口会把该地址视为“订单独立地址快照”
  - 在订单提交后再次强制写回地址快照字段
  - 避免标准生命周期再回填客户默认地址后覆盖订单真实地址
- 同时在响应中返回原始 `snapshot`，便于移动端直接继续使用
- 使用相同 `request_id` 重试时，直接返回第一次成功结果，不重复创建单据

适用场景：

- 移动端销售单 v2 创建
- 需要在订单上显式携带联系人、电话、收货地址文本
- 后续围绕订单详情页与状态聚合继续扩展

说明：

- 当前 ERPNext 标准 `Sales Order` 字段对“客户联系人”和“收货联系人”并没有完全分离的原生承载模型
- 因此 `create_order_v2` 第一版会优先保证地址文本快照和联系人展示信息可追溯
- 当前约定下，移动端业务应优先把 `shipping_address_text` 理解为“订单地址快照主值”
- `shipping_address_name` 仅在确实要绑定标准地址 Link 时才传入
- 更细粒度的双联系人持久化，如果后续确认要做，建议配合自定义字段继续增强

示例：

```python
from myapp.api.gateway import create_order_v2

create_order_v2(
    customer="Palmer Productions Ltd.",
    items=[{"item_code": "SKU010", "qty": 1, "warehouse": "Stores - RD", "price": 900}],
    company="rgc (Demo)",
    customer_info={
        "contact_display_name": "张三",
        "contact_phone": "13800138000",
        "contact_email": "zhangsan@example.com",
    },
    shipping_info={
        "receiver_name": "李四",
        "receiver_phone": "13900139000",
        "shipping_address_text": "上海市浦东新区测试路 88 号 5 楼",
    },
    request_id="order-v2-idem-001",
)
```

### update_order_v2

方法：

- `myapp.api.gateway.update_order_v2`

参数：

- `order_name: str`
- `request_id: str | None`
- `delivery_date: str | None`
- `transaction_date: str | None`
- `remarks: str | None`
- `po_no: str | None`
- `customer_info: dict | json-string | None`
- `shipping_info: dict | json-string | None`

行为：

- 按 v2 口径更新销售订单头信息、联系人快照、收货快照
- 适用于已提交但尚未取消的销售订单
- 更新后返回新的 `snapshot`
- 使用相同 `request_id` 重试时，直接返回第一次成功结果
- 若本次更新仅传入 `shipping_address_text` 而不传 `shipping_address_name`
  - 更新后会继续保持该订单的独立地址快照
  - 不再自动退回客户默认地址

当前说明：

- `delivery_date`、联系人展示信息、收货地址文本快照已完成真实 HTTP 验证
- `remarks` 在当前标准 `Sales Order` 模型中仍属于弱承载字段
- 因此第一版 contract 允许传入 `remarks`，但前端当前应优先依赖已验证的联系人 / 地址 / 日期字段

示例：

```python
from myapp.api.gateway import update_order_v2

update_order_v2(
    order_name="SAL-ORD-2026-00254",
    delivery_date="2026-03-25",
    customer_info={
        "contact_display_name": "王五",
        "contact_phone": "13600136000",
    },
    shipping_info={
        "receiver_name": "赵六",
        "receiver_phone": "13700137000",
        "shipping_address_text": "北京市朝阳区移动端更新路 66 号",
    },
    request_id="order-v2-update-001",
)
```

### update_order_items_v2

方法：

- `myapp.api.gateway.update_order_items_v2`

参数：

- `order_name: str`
- `items: list[dict] | json-string`
- `request_id: str | None`
- `delivery_date: str | None`
- `default_warehouse: str | None`
- `company: str | None`

明细字段：

- `item_code`
- `qty`
- `warehouse`
- `uom` 可选
- `price` 可选
- `delivery_date` 可选

行为：

- 按 v2 口径整体替换销售订单商品明细
- 当前要求：
  - 原订单未取消
  - 原订单不存在发货 / 开票下游单据
- 若原订单为已提交状态，则接口会：
  - 自动取消原订单
  - 生成 amendment 单据
  - 在 amendment 上写入新商品明细并重新提交
- 响应中返回：
  - 新订单号 `order`
  - 原订单号 `source_order`
  - 更新后的 `items`
- 若因 amendment 生成了新订单
  - 新订单会继承原订单当前的联系人与地址快照
  - 包括独立的 `shipping_address_text`
  - 不应因生成新单而回退到客户默认地址

说明：

- 这是当前第一版最稳妥的做法，避免直接在已提交单据上强改商品事实
- 前端收到新单号后，应继续以后端返回的 `order` 作为后续详情/发货/开票的目标

示例：

```python
from myapp.api.gateway import update_order_items_v2

update_order_items_v2(
    order_name="SAL-ORD-2026-00257",
    items=[
        {
            "item_code": "SKU010",
            "qty": 2,
            "warehouse": "Stores - RD",
            "price": 300,
        }
    ],
    request_id="order-v2-items-001",
)
```

### cancel_order_v2

- `myapp.api.gateway.cancel_order_v2`
- 用途：按 v2 语义作废销售订单，不暴露 ERPNext 原生取消动作给前端

请求参数：

- `order_name`: 销售订单号
- `request_id`: 可选；用于幂等控制

返回字段：

- `order`: 被作废的订单号
- `document_status`: 固定返回 `cancelled`
- `references.delivery_notes`: 已关联发货单列表
- `references.sales_invoices`: 已关联销售发票列表
- `detail`: 作废后的订单详情快照，结构与 `get_sales_order_detail` 保持一致

行为说明：

- 仅允许对已提交且无下游发货 / 开票单据的销售订单执行作废
- 若订单已存在下游单据，接口会返回业务错误，不允许直接作废
- 若订单已处于取消状态，接口按幂等成功返回当前状态
- 当前接口语义是“作废/取消”，不是物理删除订单

示例：

```python
from myapp.api.gateway import cancel_order_v2

cancel_order_v2(
    order_name="SAL-ORD-2026-00246",
    request_id="cancel-order-v2-001",
)
```

### cancel_delivery_note

- `myapp.api.gateway.cancel_delivery_note`
- 用途：按销售回退链路显式作废已提交的发货单

请求参数：

- `delivery_note_name`: 发货单号
- `request_id`: 可选；用于幂等控制

返回字段：

- `delivery_note`: 被作废的发货单号
- `document_status`: 固定返回 `cancelled`
- `references.sales_orders`: 来源订单列表
- `references.sales_invoices`: 当前仍关联的销售发票列表
- `detail`: 作废后的发货单详情快照，结构与 `get_delivery_note_detail_v2` 保持一致

行为说明：

- 仅允许对已提交的发货单执行作废
- 若当前发货单仍关联已提交销售发票，接口会主动拦截：
  - 必须先作废销售发票，再回退发货单
- 作废成功后：
  - ERPNext 会自动回退库存
  - 订单履约状态会重新回到可继续发货

前端集成建议：

- 发货单详情页应优先读取 `get_delivery_note_detail_v2.data.actions.can_cancel_delivery_note`
- 若返回 `cancel_delivery_note_hint`，应直接按该文案提示用户当前回退顺序

### cancel_sales_invoice

- `myapp.api.gateway.cancel_sales_invoice`
- 用途：按销售回退链路显式作废已提交的销售发票

请求参数：

- `sales_invoice_name`: 销售发票号
- `request_id`: 可选；用于幂等控制

返回字段：

- `sales_invoice`: 被作废的销售发票号
- `document_status`: 固定返回 `cancelled`
- `references.sales_orders`: 来源订单列表
- `references.delivery_notes`: 来源发货单列表
- `detail`: 作废后的销售发票详情快照，结构与 `get_sales_invoice_detail_v2` 保持一致

行为说明：

- 仅允许对已提交的销售发票执行作废
- 若 ERPNext 当前环境不允许“作废发票时自动解绑收款引用”：
  - 已存在收款或其他关联单据时会返回业务错误
- 若当前环境允许自动解绑：
  - 已收款发票也可能被成功作废
  - 该行为依赖站点设置，不应由前端硬编码假设

前端集成建议：

- 销售发票详情页应优先读取 `get_sales_invoice_detail_v2.data.actions.can_cancel_sales_invoice`
- 若返回 `cancel_sales_invoice_hint`，应在按钮附近直接展示，提醒用户当前环境可能涉及收款解绑

### cancel_payment_entry

- `myapp.api.gateway.cancel_payment_entry`
- 用途：显式作废已提交的收款单，用于“收款回退 / 退款前置回退”场景

请求参数：

- `payment_entry_name`: 收款单号
- `request_id`: 可选；用于幂等控制

返回字段：

- `payment_entry`: 被作废的收款单号
- `document_status`: 固定返回 `cancelled`
- `references`: 本次收款原本关联的引用单据列表
  - `reference_doctype`
  - `reference_name`
  - `allocated_amount`

行为说明：

- 仅允许对已提交的 `Payment Entry` 执行作废
- 作废后：
  - 收款单 `docstatus` 会变为 `2`
  - 被引用的销售发票会恢复未收金额
- 若收款单已处于作废状态，接口按幂等成功返回当前状态

适用边界：

- 当前接口语义是“收款回退/作废收款单”，不是自动生成银行退款凭证
- 若业务要求记录真实退款出账，后续仍建议补专门的“退款凭证/反向付款”流程

### create_product_and_stock

方法：

- `myapp.api.gateway.create_product_and_stock`

参数：

- `item_name: str`
- `warehouse: str | None`
- `default_warehouse: str | None`
- `opening_qty: float = 0`
- `opening_uom: str | None`
- `stock_uom: str | None`
- `standard_rate: float | None`
- `barcode: str | None`
- `image: str | None`
- `description: str | None`
- `nickname: str | None`
- `item_group: str | None`
- `item_code: str | None`
- `request_id: str | None`

行为：

- 创建正式 `Item`
- `warehouse` 为空时优先使用 `default_warehouse`，再回退到当前用户默认仓库
- `opening_qty > 0` 时自动创建一张 `Material Receipt` 入库
- `opening_uom` 有值时，后端会先将 `opening_qty` 换算为商品库存基准单位后再入库
- `standard_rate` 有值时自动补一条 `Standard Selling` 价格
- `image` 写入标准字段 `Item.image`
- `nickname` 优先写入自定义字段 `Item.custom_nickname`；若站点尚未完成迁移，则回退为旧的 `description` 兼容口径
- 返回新商品基础信息，前端可直接加入当前订单草稿

部署说明：

- 正式启用 `custom_nickname` 前，应先执行 `bench migrate`
- 本应用已提供 patch：`myapp.patches.add_item_nickname_field`

适用场景：

- 商品搜索页找不到商品时，现场快速建档并立即加入销售单
- 需要先补基础库存，再继续开单

示例：

```python
from myapp.api.gateway import create_product_and_stock

create_product_and_stock(
    item_name="临时矿泉水",
    default_warehouse="Stores - RD",
    opening_qty=12,
    standard_rate=3.5,
)
```

### get_customer_sales_context

方法：

- `myapp.api.gateway.get_customer_sales_context`

参数：

- `customer: str`

行为：

- 返回销售开单前可直接使用的客户上下文
- 聚合客户基本信息、默认联系人、默认地址
- 返回最近销售订单中使用过的收货地址文本快照
- 返回当前用户建议公司与建议仓库，便于移动端预填
- `default_contact.phone` / `default_contact.email` 优先返回客户主联系人的主手机号与主邮箱
- `default_address` 可能只包含结构化地址字段，不保证一定带 `address_display`

返回重点字段：

- `customer`
- `default_contact`
- `default_address`
- `recent_addresses`
- `suggestions`

前端集成建议：

- 前端不要只依赖 `default_address.address_display`
- 若 `address_display` 为空，应使用 `address_line1/address_line2/city/state/country/pincode` 自行拼接展示文本

适用场景：

- 销售单 v2 创建前预加载客户信息
- 开单页面自动带出默认联系人、默认地址、建议仓库
- 辅助移动端减少对 `Customer`、`Contact`、`Address` 多接口拼装

示例：

```python
from myapp.api.gateway import get_customer_sales_context

get_customer_sales_context(customer="Palmer Productions Ltd.")
```

### list_customers_v2

方法：

- `myapp.api.gateway.list_customers_v2`

参数：

- `search_key: str | None`
- `customer_group: str | None`
- `disabled: int | None`
- `date_from: str | None`
- `date_to: str | None`
- `limit: int = 20`
- `start: int = 0`
- `sort_by: str = "modified"`
- `sort_order: str = "desc"`

行为：

- 返回客户主数据列表
- 聚合默认联系人与默认地址摘要，便于移动端直接展示
- 支持按客户名称 / 编码 / 手机 / 邮箱模糊搜索
- 支持按客户主数据创建时间 `creation` 做日期区间过滤
- 日期区间按整天处理：
  - `date_from` -> `00:00:00`
  - `date_to` -> `23:59:59`

返回重点字段：

- `name`
- `display_name`
- `customer_group`
- `default_price_list`
- `disabled`
- `default_contact`
- `default_address`

适用场景：

- 客户管理列表页
- 销售开单时选择客户并预览默认信息

### get_customer_detail_v2

方法：

- `myapp.api.gateway.get_customer_detail_v2`

参数：

- `customer: str`

行为：

- 返回单个客户完整详情
- 聚合默认联系人、默认地址、最近销售订单使用过的收货地址

### create_customer_v2

方法：

- `myapp.api.gateway.create_customer_v2`

参数：

- `customer_name: str`
- `customer_type: str | None`
- `customer_group: str | None`
- `territory: str | None`
- `default_currency: str | None`
- `default_price_list: str | None`
- `remarks: str | None`
- `default_contact: dict | json-string | None`
- `default_address: dict | json-string | None`
- `disabled: bool | int = False`

行为：

- 创建客户主数据
- 可同时创建并绑定默认联系人、默认地址
- 返回创建后的客户详情快照

### update_customer_v2

方法：

- `myapp.api.gateway.update_customer_v2`

参数：

- `customer: str`
- 其余字段同 `create_customer_v2`

行为：

- 更新客户主数据
- 可同时更新默认联系人、默认地址
- 不改订单地址快照，只影响后续开单默认建议值

### disable_customer_v2

方法：

- `myapp.api.gateway.disable_customer_v2`

参数：

- `customer: str`
- `disabled: bool = True`

### list_uoms_v2

方法：

- `myapp.api.gateway.list_uoms_v2`

参数：

- `search_key: str | None`
- `enabled: int | None`
- `must_be_whole_number: int | None`
- `date_from: str | None`
- `date_to: str | None`
- `limit: int = 20`
- `start: int = 0`
- `sort_by: str = "modified"`
- `sort_order: str = "desc"`

行为：

- 返回单位主数据列表
- 支持按单位名称 / 符号 / 描述模糊搜索
- 支持按启停状态、是否必须整数筛选
- 支持按单位主数据创建时间 `creation` 做日期区间过滤
- 日期区间按整天处理：
  - `date_from` -> `00:00:00`
  - `date_to` -> `23:59:59`

返回重点字段：

- `name`
- `uom_name`
- `symbol`
- `enabled`
- `must_be_whole_number`
- `description`

适用场景：

- 单位管理列表页
- 商品单位选择器的单位主数据来源

### get_uom_detail_v2

方法：

- `myapp.api.gateway.get_uom_detail_v2`

参数：

- `uom: str`

行为：

- 返回单个单位详情
- 附带当前引用摘要 `usage_summary`
- 便于前端判断该单位是否已经被商品、换算或单据引用

### create_uom_v2

方法：

- `myapp.api.gateway.create_uom_v2`

参数：

- `uom_name: str`
- `symbol: str | None`
- `description: str | None`
- `enabled: bool | int = True`
- `must_be_whole_number: bool | int = False`

行为：

- 创建单位主数据
- 当前不支持创建后立即改名；若需要新名称，请新建新单位

### update_uom_v2

方法：

- `myapp.api.gateway.update_uom_v2`

参数：

- `uom: str`
- `symbol: str | None`
- `description: str | None`
- `enabled: bool | int | None`
- `must_be_whole_number: bool | int | None`

行为：

- 更新单位展示属性与启停状态
- 当前不支持直接改名
- 若该单位已被系统引用，则不允许直接修改 `must_be_whole_number`

### disable_uom_v2

方法：

- `myapp.api.gateway.disable_uom_v2`

参数：

- `uom: str`
- `disabled: bool = True`

行为：

- 停用或重新启用单位
- 停用后可避免新业务继续选择该单位，但不会改写历史记录

### delete_uom_v2

方法：

- `myapp.api.gateway.delete_uom_v2`

参数：

- `uom: str`

行为：

- 删除未被引用的单位
- 若已被 `Item.stock_uom`、`Item.uoms`、单据或系统设置等 Link 字段引用，则会直接拦截
- 对已被引用的单位，建议走停用而不是删除

行为：

- 停用或重新启用客户
- 用于客户主数据维护，不回溯修改历史单据

### search_product_v2

方法：

- `myapp.api.gateway.search_product_v2`

参数：

- `search_key: str`
- `search_fields: list[str] | json-string | csv-string | None`
- `warehouse: str | None`
- `company: str | None`
- `in_stock_only: bool = False`
- `sort_by: str = "relevance"`
- `sort_order: str = "asc"`
- `price_list: str = "Standard Selling"`
- `currency: str | None`
- `limit: int = 20`

当前支持的搜索字段：

- `barcode`
- `item_code`
- `item_name`
- `nickname`

当前支持的排序字段：

- `relevance`
- `name`
- `created`
- `modified`
- `qty`
- `price`

行为：

- 支持多字段搜索
- 支持只看有库存商品
- 支持仓库 / 公司口径库存过滤
- `qty` 表示当前查询口径库存
- `total_qty` 表示总库存汇总
- `warehouse_stock_details` 返回各仓库存明细，便于前端按“商品优先 -> 查看库存详情 -> 按仓加入订单”继续演进
- 返回更完整的商品摘要，包括 `description`、`creation`、`modified`
- 当前 `nickname` 优先读取 `Item.custom_nickname`
- 若站点尚未迁移出正式昵称字段，则仍会回退复用 `description` 作为兼容搜索口径

适用场景：

- 商品工作台
- 多条件搜索
- 排序与筛选
- 后续扫码、商品编辑、快速加单入口

### list_products_v2

方法：

- `myapp.api.gateway.list_products_v2`

参数：

- `search_key: str | None`
- `warehouse: str | None`
- `company: str | None`
- `date_from: str | None`
- `date_to: str | None`
- `limit: int = 20`
- `start: int = 0`
- `item_group: str | None`
- `disabled: int | None`
- `price_list: str = "Standard Selling"`
- `currency: str | None`
- `selling_price_lists: list[str] | json-string | csv-string | None`
- `buying_price_lists: list[str] | json-string | csv-string | None`
- `sort_by: str = "modified"`
- `sort_order: str = "desc"`

行为：

- 返回商品列表工作台所需的基础摘要
- 支持按商品主数据创建时间 `creation` 做日期区间过滤
- 日期区间按整天处理：
  - `date_from` -> `00:00:00`
  - `date_to` -> `23:59:59`
- 当前返回重点包括：
  - 商品基础信息
  - 启停状态
  - 当前查询口径库存 `qty`
  - 总库存 `total_qty`
  - 分仓库存明细 `warehouse_stock_details`
  - 当前价格
  - 结构化价格摘要 `price_summary`
- `price_summary` 当前重点字段：
  - `current_rate`
  - `standard_selling_rate`
  - `wholesale_rate`
  - `retail_rate`
  - `standard_buying_rate`
  - `valuation_rate`
- 当前设计目标：
  - 保持旧的 `price` 单值口径兼容
  - 同时向商品工作台提供多价格体系摘要
- 当前还会返回：
  - `wholesale_default_uom`
  - `retail_default_uom`
  - `sales_profiles`
  - `all_uoms`
- 其中 `all_uoms` 当前不只是单位名列表
  - 后端会尽量返回：
    - `uom`
    - `conversion_factor`
  - 便于前端显示：
    - 库存基准单位
    - 批发 / 零售默认单位
    - 现有单位换算提示
- 其中：
  - 订单头后续只建议作为默认模式入口
  - 真正的默认单位与默认价格应继续按商品维度返回

适用场景：

- 商品列表页
- 商品工作台
- 商品启停管理
- 后续采购 / 销售统一价格展示

### get_product_detail_v2

方法：

- `myapp.api.gateway.get_product_detail_v2`

参数：

- `item_code: str`
- `warehouse: str | None = None`
- `company: str | None = None`
- `price_list: str = "Standard Selling"`
- `currency: str | None = None`

行为：

- 返回商品详情摘要
- 返回标准图片字段 `Item.image`
- 返回商品分类 `item_group` 与品牌 `brand`
- 返回正式昵称字段 `Item.custom_nickname`，未迁移站点回退到旧 `description` 兼容口径
- 返回当前价格、库存、主条码与换算单位信息
- 其中库存相关字段包括：
  - `qty`
  - `total_qty`
  - `warehouse_stock_details`
- 返回 `all_uoms`
  - 当前会尽量带出：
    - `uom`
    - `conversion_factor`
  - 用于前端展示：
    - 当前商品可用单位
    - `1 箱 = 12 件` 这类换算提示
- 返回结构化价格摘要 `price_summary`
  - 便于前端同时展示：
    - 零售价
    - 批发价
    - 采购价
    - 成本参考
- 返回当前商品的模式默认单位：
  - `wholesale_default_uom`
  - `retail_default_uom`
- 返回 `sales_profiles`
  - 用于表达：
    - `mode_code`
    - `price_list`
    - `default_uom`

适用场景：

- 商品详情页
- 下单页回填旧草稿商品图片与摘要
- 商品编辑前预加载
- 商品搜索结果中的“查看库存详情”

### update_product_v2

方法：

- `myapp.api.gateway.update_product_v2`

参数：

- `item_code: str`
- `item_name: str | None`
- `item_group: str | None`
- `brand: str | None`
- `barcode: str | None`
- `stock_uom: str | None`
- `uom_conversions: list[dict] | json-string | None`
- `nickname: str | None`
- `description: str | None`
- `image: str | None`
- `disabled: bool | int | None`
- `wholesale_default_uom: str | None`
- `retail_default_uom: str | None`
- `standard_rate: float | None`
- `price_list: str = "Standard Selling"`
- `currency: str | None = None`
- `selling_prices: list[dict] | json-string | None`
- `buying_prices: list[dict] | json-string | None`
- `warehouse: str | None = None`
- `warehouse_stock_qty: float | None = None`
- `warehouse_stock_uom: str | None = None`
- `company: str | None = None`
- `request_id: str | None`

行为：

- 更新商品基础信息
- `item_group` 当前支持更新商品分类
- `brand` 当前支持更新商品品牌
- `barcode` 当前支持更新商品主条码
- `stock_uom` 当前支持受控修改库存基准单位
- `uom_conversions` 当前支持维护商品 `Item.uoms` 子表中的换算行
  - 典型示例：
    - `{"uom": "Box", "conversion_factor": 12}`
  - 后端会自动保证库存基准单位行存在且系数为 `1`
- `nickname` 优先写入 `Item.custom_nickname`
- `image` 写入标准字段 `Item.image`
- `wholesale_default_uom` / `retail_default_uom` 当前用于保存商品在不同销售模式下的默认成交单位
  - 2026-03-25 起，后端会校验这些默认成交单位必须能通过 `uom_conversions` 换算到 `stock_uom`
- `standard_rate` 有值时同步更新标准售价
- `selling_prices` 支持补充 selling 类价格表
- `buying_prices` 支持补充 buying 类价格表
- `warehouse_stock_qty` 有值时，按当前 `warehouse` 计算库存差额并生成正式库存调整单据，使该仓商品库存调整到目标值
- `warehouse_stock_uom` 有值时，后端会先把目标库存换算到库存基准单位，再计算差额
- 返回更新后的商品详情快照，便于前端直接回显
- 当前仍不支持：
  - 一次请求批量修改多个仓库库存
- 当前更适合的前端交互是：
  - 单次切换一个仓库
  - 编辑该仓目标库存
  - 保存后刷新详情

### create_product_v2

方法：

- `myapp.api.gateway.create_product_v2`

参数：

- `item_name: str`
- `item_code: str | None`
- `stock_uom: str | None`
- `uom: str | None`
- `item_group: str | None`
- `brand: str | None`
- `barcode: str | None`
- `uom_conversions: list[dict] | json-string | None`
- `nickname: str | None`
- `description: str | None`
- `image: str | None`
- `is_stock_item: bool | int | None`
- `is_sales_item: bool | int | None`
- `is_purchase_item: bool | int | None`
- `disabled: bool | int | None`
- `wholesale_default_uom: str | None`
- `retail_default_uom: str | None`
- `standard_rate: float | None`
- `valuation_rate: float | None`
- `price_list: str | None`
- `currency: str | None`
- `selling_prices: list[dict] | json-string | None`
- `buying_prices: list[dict] | json-string | None`
- `warehouse: str | None`
- `company: str | None`
- `request_id: str | None`

行为：

- 创建标准商品主数据
- 不自动创建入库单
- 适合作为正式商品建档接口
- 当前也支持一并写入：
  - 分类 `item_group`
  - 品牌 `brand`
  - 主条码 `barcode`
  - 库存基准单位 `stock_uom`
  - 单位换算 `uom_conversions`
- 若同时传入：
  - `wholesale_default_uom`
  - `retail_default_uom`
  则会一并写入商品在批发 / 零售模式下的默认单位
  - 且这些默认单位必须能换算到库存基准单位 `stock_uom`
- 若同时传入：
  - `standard_rate`
  - `selling_prices`
  - `buying_prices`
  则会同步补齐对应 `Item Price`

与 `create_product_and_stock` 的区别：

- `create_product_v2`
  - 只建商品
- `create_product_and_stock`
  - 建商品并补初始库存

### disable_product_v2

方法：

- `myapp.api.gateway.disable_product_v2`

参数：

- `item_code: str`
- `disabled: bool | int = 1`
- `warehouse: str | None`
- `company: str | None`
- `price_list: str | None`
- `currency: str | None`
- `request_id: str | None`

行为：

- 用于显式停用或重新启用商品
- 当前移动端与业务端建议优先使用：
  - 停用商品
  - 启用商品
- 不建议把“物理删除商品”作为常规业务动作

### get_sales_order_detail

方法：

- 订单详情返回已扩展销售模式字段：
  - `meta.default_sales_mode`
  - `items[].sales_mode`
- 用途：
  - 为订单创建 / 编辑页提供“默认模式 + 行级模式”读取能力
  - 不要求下游 `Delivery Note` / `Sales Invoice` 复制该语义

说明：

- `Delivery Note`
  - 继续只关心最终 `uom / rate / qty`
- `Sales Invoice`
  - 继续只关心最终 `uom / rate / qty`
- 因此销售模式语义当前仅在订单层维护，不在发货和开票结果页重复维护

- `myapp.api.gateway.get_sales_order_detail`

参数：

- `order_name: str`

行为：

- 返回销售单详情聚合数据
- 返回发货状态 `fulfillment`
- 返回收款状态 `payment`
- 返回完成状态 `completion`
- 详情侧的付款汇总字段当前与销售发票详情复用同一组写回辅助逻辑
- `payment.latest_payment_*` 字段口径会在订单详情与销售发票详情之间保持一致
- 单票“最新收款结果”当前也会委托到工作台同源的批量付款摘要底座上计算
- 当存在发货单时，`delivery.status` 会按真实履约结果聚合为 `shipped`
- 当存在销售发票时，`actions.can_create_sales_invoice` 会自动变为 `false`
- 当存在未结清销售发票时，`actions.can_record_payment` 会按真实应收状态返回

适用场景：

- 销售单详情页
- 发货前确认
- 开票前确认
- 收款前查看整单状态

当前返回重点字段：

- `customer.contact_display_name`
- `customer.contact_phone`
- `customer.contact_email`
- `shipping.shipping_address_text`
- `shipping.address_line1`
- `shipping.city`
- `shipping.state`
- `shipping.country`
- `amounts.order_amount_estimate`
- `amounts.receivable_amount`
- `amounts.paid_amount`
- `amounts.outstanding_amount`
- `fulfillment.status`
- `delivery.status`
- `payment.status`
- `completion.status`
- `actions.can_submit_delivery`
- `actions.can_create_sales_invoice`
- `actions.can_record_payment`
- `actions.can_process_return`
- `items[].image`
- `references.delivery_notes`
- `references.sales_invoices`
- `meta.remarks`

补充说明：

- `items` 当前会返回适合移动端 / 详情页直接渲染的商品摘要字段
- 其中 `items[].image` 来自 `Item.image`，用于避免前端为订单详情逐行再次查询商品主数据
- `remarks` 当前优先读取正式自定义字段 `Sales Order.custom_order_remark`；若站点尚未迁移，则回退兼容旧字段口径

### get_sales_order_status_summary

方法：

- `myapp.api.gateway.get_sales_order_status_summary`

参数：

- `customer: str | None`
- `company: str | None`
- `date_from: str | None`
- `date_to: str | None`
- `limit: int = 20`

行为：

- 返回销售订单列表级摘要
- 复用销售详情聚合状态口径
- 适合首页待办、列表卡片和最近订单展示
- 该接口更适合“摘要卡片 / 状态概览”，不建议再把它当作销售工作台的真实搜索接口使用
- 若传入 `date_from/date_to`，会按 `Sales Order.transaction_date` 过滤摘要范围

当前返回重点字段：

- `order_name`
- `customer_name`
- `transaction_date`
- `document_status`
- `order_amount_estimate`
- `fulfillment.status`
- `payment.status`
- `completion.status`
- `outstanding_amount`
- `modified`

### search_sales_orders_v2

方法：

- `myapp.api.gateway.search_sales_orders_v2`

参数：

- `search_key: str | None`
- `customer: str | None`
- `company: str | None`
- `date_from: str | None`
- `date_to: str | None`
- `status_filter: str | None`
- `exclude_cancelled: bool | None`
- `sort_by: str | None`
- `limit: int | None = 20`
- `start: int | None = 0`

行为：

- 面向销售工作台的真实检索接口
- 支持关键词、客户、公司、日期区间、状态、排序、分页联动查询
- 支持默认排除已作废订单，避免未来销售工作台把历史作废单据混入有效订单列表
- 当前实现已改为批量聚合订单、订单明细、发票和付款引用数据
- 不再为工作台列表中的每一条订单逐条调用 `get_sales_order_detail`
- 仍然保留统一的服务端业务口径：
  - 发货状态基于订单明细汇总
  - 收款状态基于关联销售发票与付款引用汇总
  - 完成状态基于发货与收款共同判断
- 返回两层数据：
  - `items`：当前命中的销售订单摘要列表
  - `summary`：当前检索口径下的未完成 / 待发货 / 待收款 / 已完成 / 已作废计数
- 日期区间过滤作用于 `Sales Order.transaction_date`

### get_delivery_note_detail_v2

方法：

- `myapp.api.gateway.get_delivery_note_detail_v2`

参数：

- `delivery_note_name: str`

行为：

- 返回发货单详情聚合数据
- 适合移动端发货单详情页直接渲染
- 返回来源销售订单与关联销售发票引用
- 返回发货商品明细、客户快照与收货快照

当前返回重点字段：

- `delivery_note_name`
- `document_status`
- `customer.display_name`
- `shipping.shipping_address_text`
- `amounts.delivery_amount_estimate`
- `fulfillment.total_qty`
- `fulfillment.status`
- `references.sales_orders`
- `references.sales_invoices`
- `items[].item_code`
- `items[].item_name`
- `items[].warehouse`
- `items[].qty`
- `items[].rate`
- `items[].amount`
- `items[].image`
- `meta.company`
- `meta.currency`
- `meta.posting_date`
- `meta.posting_time`
- `meta.remarks`

### get_sales_invoice_detail_v2

方法：

- `myapp.api.gateway.get_sales_invoice_detail_v2`

参数：

- `sales_invoice_name: str`

行为：

- 返回销售发票详情聚合数据
- 适合移动端发票详情页直接渲染
- 返回来源销售订单与来源发货单引用
- 返回结算摘要、最新收款结果与商品明细
- 详情侧的付款汇总字段当前与销售订单详情复用同一组写回辅助逻辑
- 用于避免订单详情与发票详情分别重复装配 `latest_payment_*` 字段
- 单票“最新收款结果”当前也会委托到工作台同源的批量付款摘要底座上计算

当前返回重点字段：

- `sales_invoice_name`
- `document_status`
- `customer.display_name`
- `shipping.shipping_address_text`
- `amounts.invoice_amount_estimate`
- `amounts.receivable_amount`
- `amounts.paid_amount`
- `amounts.outstanding_amount`
- `payment.status`
- `payment.actual_paid_amount`
- `payment.total_writeoff_amount`
- `payment.latest_payment_entry`
- `payment.latest_payment_invoice`
- `payment.latest_unallocated_amount`
- `payment.latest_writeoff_amount`
- `references.sales_orders`
- `references.delivery_notes`
- `references.latest_payment_entry`
- `items[].item_code`
- `items[].qty`
- `items[].rate`
- `items[].amount`
- `items[].image`
- `meta.company`
- `meta.currency`
- `meta.posting_date`
- `meta.due_date`
- `meta.remarks`

Frappe Desk / 前端调用：

```javascript
frappe.call({
  method: "myapp.api.gateway.create_order",
  args: {
    customer: "Palmer Productions Ltd.",
    items: [
      {
        item_code: "SKU010",
        qty: 1,
        warehouse: "Stores - RD",
      },
    ],
    company: "rgc (Demo)",
    immediate: 1,
    request_id: "order-idem-001",
  },
}).then((r) => {
  console.log(r.message.data.order);
});
```

### create_purchase_order

方法：

- `myapp.api.gateway.create_purchase_order`

参数：

- `supplier: str`
- `items: list[dict] | json-string`
- `request_id: str | None`
- `company: str | None`
- `schedule_date: str | None`
- `transaction_date: str | None`
- `default_warehouse: str | None`
- `currency: str | None`
- `buying_price_list: str | None`
- `supplier_ref: str | None`
- `remarks: str | None`

明细字段：

- `item_code`
- `qty`
- `warehouse`
- `uom` 可选
- `price` 可选
- `schedule_date` 可选

单位处理说明：

- 明细仍按前端传入的 `qty + uom` 建模
- 后端会根据商品 `stock_uom + uom_conversions` 自动补齐：
  - `conversion_factor`
  - `stock_qty`
  - `stock_uom`
- 若 `uom` 为空，则默认按商品库存基准单位处理
- 若 `uom` 已传但商品未配置对应换算系数，接口会直接报错

行为：

- 创建并提交 `Purchase Order`
- 在服务层提前校验仓库与公司归属
- 当使用相同 `request_id` 重试时，直接返回第一次成功的 `purchase_order`

示例：

```python
from myapp.api.gateway import create_purchase_order

create_purchase_order(
    supplier="MA Inc.",
    items=[{"item_code": "SKU010", "qty": 5, "warehouse": "Stores - RD"}],
    company="rgc (Demo)",
    request_id="purchase-order-idem-001",
)
```

### submit_delivery

方法：

- `myapp.api.gateway.submit_delivery`

参数：

- `order_name: str`
- `delivery_items: list[dict] | json-string | None = None`
- `request_id: str | None`
- `posting_date: str | None`
- `posting_time: str | None`
- `set_posting_time: int | bool | None`
- `remarks: str | None`
- `force_delivery: int | bool | None = 0`

行为：

- 基于 `Sales Order` 创建并提交 `Delivery Note`
- 支持通过 `delivery_items` 做部分发货
- 支持在 `delivery_items` 中按 `sales_order_item` / `so_detail` 或 `item_code` 改写数量与价格
- 当使用相同 `request_id` 重试时，直接返回第一次成功的 `delivery_note`
- 当源 `Sales Order` 已无可发货明细时，返回明确的校验错误
- 默认会在提交前校验可用库存
- 当 `force_delivery=1` 时，会跳过前置可用库存校验，并仅对当前发货涉及的物料临时打开 `allow_negative_stock` 以完成强制出货；提交结束后会恢复原值

当前返回重点字段：

- `delivery_note`
- `force_delivery`

前端集成建议：

- 不建议把该接口直接绑定为订单详情页的“点一下立即落单”动作
- 更推荐的交互是：
  - 订单详情页 -> 发货确认页
  - 由发货确认页在用户核对商品、客户与风险提示后再调用本接口
- 当接口返回库存不足类错误时：
  - 前端应优先展示明确风险提示
  - 再由用户决定是否改为 `force_delivery=1`
  - 不建议默认自动回退为强制出货

### create_sales_invoice

方法：

- `myapp.api.gateway.create_sales_invoice`

参数：

- `source_name: str`
- `invoice_items: list[dict] | json-string | None = None`
- `request_id: str | None`
- `due_date: str | None`
- `remarks: str | None`
- `update_stock: int | bool | None`

行为：

- 基于 `Sales Order` 创建并提交 `Sales Invoice`
- 支持通过 `invoice_items` 做部分开票
- 支持在 `invoice_items` 中按 `sales_order_item` / `so_detail` 或 `item_code` 改写数量与价格
- 当使用相同 `request_id` 重试时，直接返回第一次成功的 `sales_invoice`
- 当源 `Sales Order` 已无可开票明细时，返回明确的校验错误

前端集成建议：

- 不建议把该接口作为订单详情页中的静默直接执行动作
- 更推荐：
  - 订单详情页 -> 开票确认页
  - 由确认页承接 `source_name`、`due_date`、`remarks` 等输入
  - 用户确认后再调用本接口
- 若销售发票详情页后续承接打印能力，建议：
  - 详情页优先朝“预览化单据页”建设
  - 打印预览入口优先放在发票详情页或发票预览页，而不是订单详情页

### receive_purchase_order

方法：

- `myapp.api.gateway.receive_purchase_order`

参数：

- `order_name: str`
- `receipt_items: list[dict] | json-string | None = None`
- `request_id: str | None`
- `posting_date: str | None`
- `posting_time: str | None`
- `set_posting_time: int | bool | None`
- `remarks: str | None`

行为：

- 基于 `Purchase Order` 创建并提交 `Purchase Receipt`
- 支持通过 `receipt_items` 做部分收货
- 支持在 `receipt_items` 中按 `purchase_order_item` / `po_detail` 或 `item_code` 改写数量与价格
- 当使用相同 `request_id` 重试时，直接返回第一次成功的 `purchase_receipt`
- 当源 `Purchase Order` 已无可收货明细时，返回明确的校验错误

### create_purchase_invoice

方法：

- `myapp.api.gateway.create_purchase_invoice`

参数：

- `source_name: str`
- `invoice_items: list[dict] | json-string | None = None`
- `request_id: str | None`
- `due_date: str | None`
- `remarks: str | None`
- `update_stock: int | bool | None`

行为：

- 基于 `Purchase Order` 创建并提交 `Purchase Invoice`
- 支持通过 `invoice_items` 做部分开票
- 支持在 `invoice_items` 中按 `purchase_order_item` / `po_detail` 或 `item_code` 改写数量与价格
- 当使用相同 `request_id` 重试时，直接返回第一次成功的 `purchase_invoice`
- 当源 `Purchase Order` 已无可开票明细时，返回明确的校验错误

### create_purchase_invoice_from_receipt

方法：

- `myapp.api.gateway.create_purchase_invoice_from_receipt`

参数：

- `receipt_name: str`
- `invoice_items: list[dict] | json-string | None = None`
- `request_id: str | None`
- `due_date: str | None`
- `remarks: str | None`
- `update_stock: int | bool | None`

行为：

- 基于 `Purchase Receipt` 创建并提交 `Purchase Invoice`
- 支持通过 `invoice_items` 做部分开票
- 支持在 `invoice_items` 中按 `purchase_receipt_item` / `pr_detail` 或 `item_code` 改写数量与价格
- 当使用相同 `request_id` 重试时，直接返回第一次成功的 `purchase_invoice`
- 当源 `Purchase Receipt` 已无可开票明细时，返回明确的校验错误

### confirm_pending_document

方法：

- `myapp.api.gateway.confirm_pending_document`

参数：

- `doctype: str`
- `docname: str`
- `action: str | None`
- `updates: dict | json-string | None`
- `submit_on_confirm: int | bool = 1`

行为：

- 传 `action` 时执行工作流动作
- 不传时默认提交草稿单据
- 不提交时退回到 `save()`

### update_payment_status

方法：

- `myapp.api.gateway.update_payment_status`

参数：

- `reference_doctype: str`
- `reference_name: str`
- `paid_amount: float`
- `request_id: str | None`
- `mode_of_payment: str | None`
- `reference_no: str | None`
- `reference_date: str | None`
- `settlement_mode: str | None = "partial"`
- `writeoff_reason: str | None`

行为：

- 基于引用单据创建并提交 `Payment Entry`
- 支持标准全额收款
- 支持部分收款，未收金额继续保留
- 支持 `settlement_mode = "writeoff"` 的少收并结清场景，差额会按 Write Off Account 核销
- 支持多收场景：当前发票按应收金额结清，超出部分作为 `unallocated_amount` 保留
- 当使用相同 `request_id` 重试时，直接返回第一次成功的 `payment_entry`

当前返回重点字段：

- `payment_entry`
- `settlement_mode`
- `writeoff_amount`
- `unallocated_amount`

HTTP 调用示例：

```bash
curl -X POST https://your-site.example.com/api/method/myapp.api.gateway.update_payment_status \
  -H "Authorization: token api_key:api_secret" \
  -H "Content-Type: application/json" \
  -d '{
    "reference_doctype": "Sales Invoice",
    "reference_name": "ACC-SINV-2026-00006",
    "paid_amount": 1,
    "request_id": "payment-idem-001"
  }'
```

Frappe Desk / 前端调用：

```javascript
frappe.call({
  method: "myapp.api.gateway.update_payment_status",
  args: {
    reference_doctype: "Sales Invoice",
    reference_name: "ACC-SINV-2026-00006",
    paid_amount: 1,
    request_id: "payment-idem-001",
  },
}).then((r) => {
  console.log(r.message.data.payment_entry);
});
```

补充说明：

- `settlement_mode = "partial"`：保留未收金额，适用于部分收款
- `settlement_mode = "writeoff"`：当 `paid_amount < outstanding_amount` 时，允许按差额核销后直接结清
- 当 `paid_amount > outstanding_amount` 时，ERPNext 标准 `Payment Entry` 会将超出部分保留为 `unallocated_amount`

订单详情聚合补充：

- `get_sales_order_detail` 的 `payment` 当前还会返回：
  - `actual_paid_amount`
  - `total_writeoff_amount`
  - `latest_payment_entry`
  - `latest_payment_invoice`
  - `latest_unallocated_amount`
  - `latest_writeoff_amount`
- 推荐前端优先直接读取这些语义化金额字段，而不是长期自行推导“实收金额 / 核销金额 / 额外收款”

### process_sales_return

方法：

- `myapp.api.gateway.process_sales_return`

参数：

- `source_doctype: str`
- `source_name: str`
- `return_items: list[dict] | json-string | None = None`
- `request_id: str | None`
- `posting_date: str | None`
- `posting_time: str | None`
- `set_posting_time: int | bool | None`
- `remarks: str | None`

行为：

- 支持从 `Sales Invoice` 和 `Delivery Note` 创建退货
- 支持在 `return_items` 中按 `sales_invoice_item` / `si_detail`、`delivery_note_item` / `dn_detail` 或 `item_code` 指定退货数量
- 创建并提交映射后的退货单据
- 当使用相同 `request_id` 重试时，直接返回第一次成功的退货结果
- 当前接口应明确理解为：
  - “来源单据依据版销售退货”
  - 面向单一来源单据的标准逆向冲销
  - 不用于覆盖多订单混合退货、多批次混合退货或现场自由退货

当前返回重点字段：

- `return_document`
- `return_doctype`
- `document_status`
- `source_doctype`
- `source_name`
- `business_type`
- `summary`
  - `item_count`
  - `total_qty`
  - `return_amount_estimate`
  - `is_partial_return`
- `references`
- `next_actions`
  - `can_view_return_document`
  - `can_back_to_source`
  - `suggested_next_action`

当前建议动作口径：

- 对已收款销售发票执行退货后，当前会建议前端进入：
  - `review_refund`
- 这表示“退货单已创建”，但当前并不会自动生成独立退款闭环凭证

### get_return_source_context_v2

方法：

- `myapp.api.gateway.get_return_source_context_v2`

参数：

- `source_doctype: str`
- `source_name: str`

行为：

- 按来源单据统一返回退货页可直接消费的上下文
- 当前支持来源：
  - `Delivery Note`
  - `Sales Invoice`
  - `Purchase Receipt`
  - `Purchase Invoice`
- 返回统一字段：
  - `business_type`
  - `source_doctype`
  - `source_name`
  - `source_label`
  - `document_status`
  - `party`
  - `amounts`
  - `actions`
  - `references`
  - `meta`
  - `items`

说明：

- 该接口定位是“通用退货页面上下文接口”
- 第一阶段建议前端优先使用它来渲染退货页，而不是分别拼接销售/采购详情接口
- 当前接口范围补充：
  - 它属于“来源单据依据版退货上下文”
  - 输入必须绑定单一来源单据
  - 适用于严格可追溯的标准退货路径
  - 不等同于现场混合退货中心的通用来源解析接口

### record_supplier_payment

方法：

- `myapp.api.gateway.record_supplier_payment`

参数：

- `reference_name: str`
- `paid_amount: float`
- `request_id: str | None`
- `mode_of_payment: str | None`
- `reference_no: str | None`
- `reference_date: str | None`

行为：

- 基于 `Purchase Invoice` 创建并提交 `Payment Entry`
- 当使用相同 `request_id` 重试时，直接返回第一次成功的 `payment_entry`

### process_purchase_return

方法：

- `myapp.api.gateway.process_purchase_return`

参数：

- `source_doctype: str`
- `source_name: str`
- `return_items: list[dict] | json-string | None = None`
- `request_id: str | None`
- `posting_date: str | None`
- `posting_time: str | None`
- `set_posting_time: int | bool | None`
- `remarks: str | None`

行为：

- 支持从 `Purchase Receipt` 和 `Purchase Invoice` 创建采购退货
- 支持在 `return_items` 中按明细行优先、`item_code` 兜底指定退货数量
- 创建并提交映射后的采购退货单据
- 当使用相同 `request_id` 重试时，直接返回第一次成功的退货结果
- 当前接口应明确理解为：
  - “来源单据依据版采购退货”
  - 面向单一来源单据的标准逆向冲销
  - 不用于覆盖多订单混合退货、多批次混合退货或现场自由退货

当前返回重点字段：

- `return_document`
- `return_doctype`
- `document_status`
- `source_doctype`
- `source_name`
- `business_type`
- `summary`
  - `item_count`
  - `total_qty`
  - `return_amount_estimate`
  - `is_partial_return`
- `references`
- `next_actions`
  - `can_view_return_document`
  - `can_back_to_source`
  - `suggested_next_action`

当前建议动作口径：

- 对已付款采购发票执行退货后，当前会建议前端进入：
  - `review_supplier_refund`
- 这表示“采购退货单已创建”，但当前并不会自动生成供应商退款 / 应付冲减闭环

### get_purchase_order_detail_v2

方法：

- `myapp.api.gateway.get_purchase_order_detail_v2`

参数：

- `order_name: str`

行为：

- 返回采购订单详情聚合数据，供移动端详情页直接渲染
- 返回供应商快照、金额摘要、收货状态、付款状态、商品明细与下游单据引用
- 返回当前订单是否还能继续收货、开票、编辑或作废的动作标记
- 详情侧的付款汇总字段当前与采购发票详情复用同一组写回辅助逻辑
- `payment.latest_payment_*` 字段口径会在订单详情与采购发票详情之间保持一致
- 单票“最新付款结果”当前也会委托到工作台同源的批量付款摘要底座上计算

当前返回重点字段：

- `purchase_order_name`
- `document_status`
- `supplier.display_name`
- `amounts.grand_total`
- `amounts.received_amount_estimate`
- `amounts.invoiced_amount_estimate`
- `receiving.status`
- `payment.status`
- `actions.can_receive`
- `actions.can_create_invoice`
- `actions.can_update`
- `actions.can_cancel`
- `references.purchase_receipts`
- `references.purchase_invoices`
- `items[].item_code`
- `items[].qty`
- `items[].received_qty`
- `items[].rate`
- `items[].amount`
- `meta.company`
- `meta.currency`
- `meta.transaction_date`
- `meta.schedule_date`

### get_purchase_order_status_summary

方法：

- `myapp.api.gateway.get_purchase_order_status_summary`

参数：

- `supplier: str | None`
- `company: str | None`
- `date_from: str | None`
- `date_to: str | None`
- `limit: int | None = 20`

行为：

- 返回采购订单列表页可直接使用的状态摘要
- 每条记录都基于详情聚合口径构造，避免前端自己推导“已收货 / 已开票 / 已付款 / 是否完成”
- 该接口更适合“摘要卡片 / 状态概览”，不建议再把它当作采购工作台的真实搜索接口使用
- 若传入 `date_from/date_to`，会按 `Purchase Order.transaction_date` 过滤摘要范围

### search_purchase_orders_v2

方法：

- `myapp.api.gateway.search_purchase_orders_v2`

参数：

- `search_key: str | None`
- `supplier: str | None`
- `company: str | None`
- `date_from: str | None`
- `date_to: str | None`
- `status_filter: str | None`
- `exclude_cancelled: bool | None`
- `sort_by: str | None`
- `limit: int | None = 20`
- `start: int | None = 0`

行为：

- 面向采购工作台的真实检索接口
- 支持关键词、公司、日期区间、状态、排序、分页联动查询
- 支持默认排除已作废订单，避免有效订单列表被历史作废单据淹没
- 当前实现已改为批量聚合订单、订单明细、发票和付款引用数据
- 不再为工作台列表中的每一条采购订单逐条调用 `get_purchase_order_detail_v2`
- 仍然保留统一的服务端业务口径：
  - 收货状态基于采购订单明细汇总
  - 付款状态基于关联采购发票与付款引用汇总
  - 完成状态基于收货与付款共同判断
- 返回两层数据：
  - `items`：当前命中的采购订单摘要列表
  - `summary`：当前检索口径下的未完成 / 待收货 / 待付款 / 已完成 / 已作废计数
- 日期区间过滤作用于 `Purchase Order.transaction_date`

### get_purchase_receipt_detail_v2

方法：

- `myapp.api.gateway.get_purchase_receipt_detail_v2`

参数：

- `receipt_name: str`

行为：

- 返回采购收货单详情聚合数据
- 返回来源采购单、关联采购发票、供应商快照、地址快照和商品明细
- 适合收货详情页、退货确认页直接渲染

### get_purchase_invoice_detail_v2

方法：

- `myapp.api.gateway.get_purchase_invoice_detail_v2`

参数：

- `invoice_name: str`

行为：

- 返回采购发票详情聚合数据
- 返回来源采购单 / 收货单引用、付款摘要、最新付款结果与商品明细
- 适合发票详情页、付款确认页直接渲染
- 详情侧的付款汇总字段当前与采购订单详情复用同一组写回辅助逻辑
- 用于避免订单详情与发票详情分别重复装配 `latest_payment_*` 字段
- 单票“最新付款结果”当前也会委托到工作台同源的批量付款摘要底座上计算

### get_supplier_purchase_context

方法：

- `myapp.api.gateway.get_supplier_purchase_context`

参数：

- `supplier: str`

行为：

- 返回采购建单所需的供应商默认上下文
- 包含供应商摘要、默认联系人、默认地址、最近使用地址及建议默认仓库
- 用于移动端创建采购单时预填信息

### list_suppliers_v2

方法：

- `myapp.api.gateway.list_suppliers_v2`

参数：

- `search_key: str | None`
- `supplier_group: str | None`
- `disabled: int | bool | None`
- `date_from: str | None`
- `date_to: str | None`
- `limit: int | None = 20`
- `start: int | None = 0`
- `sort_by: str | None = "modified"`
- `sort_order: str | None = "desc"`

行为：

- 返回供应商列表摘要
- 支持模糊搜索、分组筛选、启停状态筛选和分页
- 支持按供应商主数据创建时间 `creation` 做日期区间过滤
- 日期区间按整天处理：
  - `date_from` -> `00:00:00`
  - `date_to` -> `23:59:59`
- 每条记录包含默认联系人、默认地址和最近采购摘要

### get_supplier_detail_v2

方法：

- `myapp.api.gateway.get_supplier_detail_v2`

参数：

- `supplier: str`

行为：

- 返回供应商详情聚合数据
- 包含默认联系人、默认地址、最近采购地址和基础主数据摘要

### create_supplier_v2

方法：

- `myapp.api.gateway.create_supplier_v2`

参数：

- `supplier_name: str`
- `supplier_type: str | None`
- `supplier_group: str | None`
- `default_currency: str | None`
- `remarks: str | None`
- `mobile_no: str | None`
- `email_id: str | None`
- `default_contact: dict | json-string | None`
- `default_address: dict | json-string | None`
- `disabled: bool | int = False`

行为：

- 创建供应商主数据
- 可同时创建并绑定默认联系人、默认地址
- 返回创建后的供应商详情快照

### update_supplier_v2

方法：

- `myapp.api.gateway.update_supplier_v2`

参数：

- `supplier: str`
- 其余字段同 `create_supplier_v2`

行为：

- 更新供应商主数据
- 可同时更新默认联系人、默认地址
- 不影响历史采购单上的地址 / 联系人快照，只影响后续默认建议值

### disable_supplier_v2

方法：

- `myapp.api.gateway.disable_supplier_v2`

参数：

- `supplier: str`
- `disabled: bool = True`

### update_purchase_order_v2

方法：

- `myapp.api.gateway.update_purchase_order_v2`

参数：

- `order_name: str`
- 其余更新字段通过顶层参数传入，例如：
  - `schedule_date`
  - `remarks`
  - `supplier_ref`
  - `request_id`

行为：

- 按 v2 语义更新采购订单头信息
- 适用于采购订单编辑页保存头部字段
- 当使用相同 `request_id` 重试时，直接返回第一次成功结果

### update_purchase_order_items_v2

方法：

- `myapp.api.gateway.update_purchase_order_items_v2`

参数：

- `order_name: str`
- `items: list[dict] | json-string`
- `request_id: str | None`

行为：

- 按 v2 语义整体替换采购订单商品明细
- 适用于采购订单编辑页保存商品区
- 当使用相同 `request_id` 重试时，直接返回第一次成功结果

### cancel_purchase_order_v2

方法：

- `myapp.api.gateway.cancel_purchase_order_v2`

参数：

- `order_name: str`
- `request_id: str | None`

行为：

- 统一封装采购订单作废动作
- 返回统一成功码与作废后的单据状态

### cancel_purchase_receipt_v2

方法：

- `myapp.api.gateway.cancel_purchase_receipt_v2`

参数：

- `receipt_name: str`
- `request_id: str | None`

行为：

- 统一封装采购收货单作废动作
- 返回统一成功码与作废后的单据状态

### cancel_purchase_invoice_v2

方法：

- `myapp.api.gateway.cancel_purchase_invoice_v2`

参数：

- `invoice_name: str`
- `request_id: str | None`

行为：

- 统一封装采购发票作废动作
- 返回统一成功码与作废后的单据状态

### cancel_supplier_payment

方法：

- `myapp.api.gateway.cancel_supplier_payment`

参数：

- `payment_entry_name: str`
- `request_id: str | None`

行为：

- 统一封装供应商付款单作废动作
- 与销售结算侧保持一致的错误包装与返回结构

### 已验证样例数据

- `customer="Palmer Productions Ltd."`
- `item_code="SKU010"`
- `warehouse="Stores - RD"`
- `company="rgc (Demo)"`

### 已确认业务约束

- 仓库必须属于与订单相同的公司
- `immediate=True` 需要目标仓库存在可用库存
- 如果某个 `item_code + warehouse` 组合没有 `Bin` 记录，即时发货会被拦截
- 采购侧若要在收货或开票阶段直接改价，需要关闭 ERPNext `Buying Settings.maintain_same_rate`
- 采购侧若请求中包含 `price` 改写且 `maintain_same_rate` 重新启用，网关会主动返回明确业务错误
- 当前环境的 `Selling Settings.maintain_same_sales_rate = 0`，销售侧允许在发货和开票阶段按实际成交结果改价
- 采购列表页、详情页、收货详情页和发票详情页优先使用采购聚合接口，不建议前端自行拼装 `Purchase Order / Purchase Receipt / Purchase Invoice / Payment Entry` 状态

### 附录：联调中实际会用到的官方接口

以下官方接口不是本应用的主业务入口，但在测试、前端查询、调试和对账时会实际用到。

原则：

- 写操作优先走 `myapp.api.gateway.*`
- 读操作可按需要使用官方资源接口
- 不建议直接通过官方接口自行创建或提交销售/采购主单据，避免绕过幂等、统一错误码和业务封装

#### 1. 登录接口

用于宿主机 HTTP 测试或前端联调时获取会话。

路径：

- `POST /api/method/login`

示例：

```bash
curl -X POST http://localhost:8080/api/method/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d 'usr=Administrator&pwd=your-password'
```

#### 2. 资源详情查询

用于读取单据完整字段和明细行，例如读取 `Sales Order` / `Purchase Receipt` / `Sales Invoice` / `Purchase Invoice` 的 `items`，以便后续接口按明细行继续处理。

路径：

- `GET /api/resource/<DocType>/<name>`

常见用法：

- 读取 `Sales Order` 明细，获取 `sales_order_item`
- 读取 `Purchase Order` 明细，获取 `purchase_order_item`
- 读取 `Purchase Receipt` 明细，获取 `purchase_receipt_item`
- 读取 `Delivery Note` / `Sales Invoice` / `Purchase Invoice` 结果详情

示例：

```bash
curl -X GET \
  "http://localhost:8080/api/resource/Purchase%20Receipt/MAT-PRE-2026-00011" \
  -H "Authorization: token api_key:api_secret"
```

#### 3. 资源列表查询

用于按过滤条件查询资源，例如查询某张收货单对应的库存分录。

路径：

- `GET /api/resource/<DocType>?filters=...&fields=...`

常见用法：

- 查询 `Stock Ledger Entry`
- 查询特定条件下的 `Payment Entry`
- 查询指定单据的列表结果

示例：

```bash
curl -X GET \
  "http://localhost:8080/api/resource/Stock%20Ledger%20Entry?filters=%5B%5B%22Stock%20Ledger%20Entry%22%2C%22voucher_no%22%2C%22%3D%22%2C%22MAT-PRE-2026-00011%22%5D%5D&fields=%5B%22name%22%2C%22voucher_no%22%2C%22actual_qty%22%2C%22incoming_rate%22%2C%22stock_value_difference%22%5D" \
  -H "Authorization: token api_key:api_secret"
```

#### 4. 当前联调中已实际使用的官方 DocType

- `Sales Order`
- `Delivery Note`
- `Sales Invoice`
- `Purchase Order`
- `Purchase Receipt`
- `Purchase Invoice`
- `Payment Entry`
- `Stock Ledger Entry`
- `Selling Settings`
- `Buying Settings`

#### 5. 建议直接走自定义网关的业务动作

- 创建销售订单
- 创建采购订单
- 发货
- 收货
- 销售开票
- 采购开票
- 收款
- 供应商付款
- 销售退货
- 采购退货
- 草稿确认与工作流动作
