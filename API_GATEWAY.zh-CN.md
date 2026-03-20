## API 网关文档

推荐使用以下自定义接口入口：

- 销售与商品：
- `myapp.api.gateway.search_product`
- `myapp.api.gateway.search_product_v2`
- `myapp.api.gateway.create_product_and_stock`
- `myapp.api.gateway.get_product_detail_v2`
- `myapp.api.gateway.update_product_v2`
- `myapp.api.gateway.create_order`
- `myapp.api.gateway.create_order_v2`
- `myapp.api.gateway.cancel_order_v2`
- `myapp.api.gateway.get_customer_sales_context`
- `myapp.api.gateway.get_sales_order_detail`
- `myapp.api.gateway.get_sales_order_status_summary`
- `myapp.api.gateway.get_delivery_note_detail_v2`
- `myapp.api.gateway.get_sales_invoice_detail_v2`
- `myapp.api.gateway.submit_delivery`
- `myapp.api.gateway.create_sales_invoice`
- `myapp.api.gateway.update_payment_status`
- `myapp.api.gateway.process_sales_return`

- 采购与结算：
- `myapp.api.gateway.create_purchase_order`
- `myapp.api.gateway.receive_purchase_order`
- `myapp.api.gateway.create_purchase_invoice`
- `myapp.api.gateway.create_purchase_invoice_from_receipt`
- `myapp.api.gateway.record_supplier_payment`
- `myapp.api.gateway.process_purchase_return`

- 通用辅助：
- `myapp.api.gateway.confirm_pending_document`

本文档主结构按业务模块划分，而不是按“自定义接口 / 官方接口”二分。

原因：

- 调用方首先关心“销售要调哪些接口、采购要调哪些接口”
- 后续前端页面、测试用例和实施手册也更适合按模块对齐
- ERPNext / Frappe 原生接口更适合作为底层映射说明，而不是主阅读路径

本文档只覆盖本应用的自定义接口。ERPNext / Frappe 原生接口不作为主接口文档展开，仅在必要时说明底层映射关系。

### 模块导航

- 销售与商品：`search_product`、`search_product_v2`、`create_product_and_stock`、`get_product_detail_v2`、`update_product_v2`、`create_order`、`create_order_v2`、`get_customer_sales_context`、`get_sales_order_detail`、`get_sales_order_status_summary`、`get_delivery_note_detail_v2`、`get_sales_invoice_detail_v2`、`submit_delivery`、`create_sales_invoice`、`update_payment_status`、`process_sales_return`
- 采购与结算：`create_purchase_order`、`receive_purchase_order`、`create_purchase_invoice`、`create_purchase_invoice_from_receipt`、`record_supplier_payment`、`process_purchase_return`
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

- 创建并提交 `Sales Order`
- 保留旧 `create_order` 的仓库归属、库存和即时出单校验逻辑
- 支持在创建时显式传入客户联系人快照和收货信息快照
- 当前会把可映射字段写入订单标准联系人 / 地址展示字段
- 同时在响应中返回原始 `snapshot`，便于移动端直接继续使用
- 使用相同 `request_id` 重试时，直接返回第一次成功结果，不重复创建单据

适用场景：

- 移动端销售单 v2 创建
- 需要在订单上显式携带联系人、电话、收货地址文本
- 后续围绕订单详情页与状态聚合继续扩展

说明：

- 当前 ERPNext 标准 `Sales Order` 字段对“客户联系人”和“收货联系人”并没有完全分离的原生承载模型
- 因此 `create_order_v2` 第一版会优先保证地址文本快照和联系人展示信息可追溯
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

### create_product_and_stock

方法：

- `myapp.api.gateway.create_product_and_stock`

参数：

- `item_name: str`
- `warehouse: str | None`
- `default_warehouse: str | None`
- `opening_qty: float = 0`
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
- 返回更完整的商品摘要，包括 `description`、`creation`、`modified`
- 当前 `nickname` 优先读取 `Item.custom_nickname`
- 若站点尚未迁移出正式昵称字段，则仍会回退复用 `description` 作为兼容搜索口径

适用场景：

- 商品工作台
- 多条件搜索
- 排序与筛选
- 后续扫码、商品编辑、快速加单入口

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
- 返回正式昵称字段 `Item.custom_nickname`，未迁移站点回退到旧 `description` 兼容口径
- 返回当前价格、库存、主条码与换算单位信息

适用场景：

- 商品详情页
- 下单页回填旧草稿商品图片与摘要
- 商品编辑前预加载

### update_product_v2

方法：

- `myapp.api.gateway.update_product_v2`

参数：

- `item_code: str`
- `item_name: str | None`
- `nickname: str | None`
- `description: str | None`
- `image: str | None`
- `disabled: bool | int | None`
- `standard_rate: float | None`
- `price_list: str = "Standard Selling"`
- `currency: str | None = None`
- `warehouse: str | None = None`
- `company: str | None = None`
- `request_id: str | None`

行为：

- 更新商品基础信息
- `nickname` 优先写入 `Item.custom_nickname`
- `image` 写入标准字段 `Item.image`
- `standard_rate` 有值时同步更新标准售价
- 返回更新后的商品详情快照，便于前端直接回显

### get_sales_order_detail

方法：

- `myapp.api.gateway.get_sales_order_detail`

参数：

- `order_name: str`

行为：

- 返回销售单详情聚合数据
- 返回发货状态 `fulfillment`
- 返回收款状态 `payment`
- 返回完成状态 `completion`
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
- `limit: int = 20`

行为：

- 返回销售订单列表级摘要
- 复用销售详情聚合状态口径
- 适合首页待办、列表卡片和最近订单展示

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
