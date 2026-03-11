## API 网关文档

推荐使用以下自定义接口入口：

- `myapp.api.gateway.search_product`
- `myapp.api.gateway.create_order`
- `myapp.api.gateway.create_purchase_order`
- `myapp.api.gateway.submit_delivery`
- `myapp.api.gateway.receive_purchase_order`
- `myapp.api.gateway.create_sales_invoice`
- `myapp.api.gateway.create_purchase_invoice`
- `myapp.api.gateway.confirm_pending_document`
- `myapp.api.gateway.update_payment_status`
- `myapp.api.gateway.record_supplier_payment`
- `myapp.api.gateway.process_sales_return`
- `myapp.api.gateway.process_purchase_return`

本文档只覆盖本应用的自定义接口，不封装 ERPNext / Frappe 原生接口。

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
    supplier="Test Supplier 1",
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

行为：

- 基于 `Sales Order` 创建并提交 `Delivery Note`
- 支持通过 `delivery_items` 做部分发货
- 当使用相同 `request_id` 重试时，直接返回第一次成功的 `delivery_note`
- 当源 `Sales Order` 已无可发货明细时，返回明确的校验错误

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
- 当使用相同 `request_id` 重试时，直接返回第一次成功的 `sales_invoice`
- 当源 `Sales Order` 已无可开票明细时，返回明确的校验错误

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
- 当使用相同 `request_id` 重试时，直接返回第一次成功的 `purchase_invoice`
- 当源 `Purchase Order` 已无可开票明细时，返回明确的校验错误

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

行为：

- 基于引用单据创建并提交 `Payment Entry`
- 当使用相同 `request_id` 重试时，直接返回第一次成功的 `payment_entry`

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
