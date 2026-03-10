## API Gateway

Recommended custom API entry points:

- `myapp.api.gateway.search_product`
- `myapp.api.gateway.create_order`
- `myapp.api.gateway.submit_delivery`
- `myapp.api.gateway.create_sales_invoice`
- `myapp.api.gateway.confirm_pending_document`
- `myapp.api.gateway.update_payment_status`
- `myapp.api.gateway.process_sales_return`

These methods are custom APIs for this app. ERPNext / Frappe native APIs are not wrapped by this document.

### Unified Success Response

All `myapp.api.gateway.*` methods return the same success envelope:

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

Notes:

- `data` contains the main business payload.
- `meta` contains auxiliary data such as filters.

### Unified Error Response

All `myapp.api.gateway.*` methods now return a unified error envelope for common application errors:

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

Current mapped error codes:

- `VALIDATION_ERROR`
- `PERMISSION_DENIED`
- `AUTHENTICATION_REQUIRED`
- `RESOURCE_NOT_FOUND`
- `DUPLICATE_ENTRY`
- `WORKFLOW_ACTION_INVALID`
- `INSUFFICIENT_STOCK`
- `INTERNAL_ERROR`

For these custom gateway APIs, HTTP status code is also aligned where possible:

- `401` authentication required
- `403` permission denied
- `404` resource not found
- `409` duplicate, workflow conflict, insufficient stock
- `422` validation error
- `500` internal error

### Client Call Examples

Frappe Desk / frontend:

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

HTTP example:

```bash
curl -X POST https://your-site.example.com/api/method/myapp.api.gateway.search_product \
  -H "Authorization: token api_key:api_secret" \
  -H "Content-Type: application/json" \
  -d '{
    "search_key": "Camera",
    "warehouse": "Stores - RD"
  }'
```

Error example:

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

Method:

- `myapp.api.gateway.search_product`

Arguments:

- `search_key: str`
- `price_list: str = "Standard Selling"`
- `currency: str | None = None`
- `warehouse: str | None = None`
- `company: str | None = None`
- `limit: int = 20`

Behavior:

- Searches by barcode, item code, or item name.
- Returns warehouse-specific stock when `warehouse` is provided.
- Returns company-wide aggregated stock when only `company` is provided.
- Returns all-warehouse aggregated stock when neither `warehouse` nor `company` is provided.

Example:

```python
from myapp.api.gateway import search_product

search_product(
    search_key="Camera",
    warehouse="Stores - RD",
)
```

Example response:

```json
{
  "ok": true,
  "status": "success",
  "code": "PRODUCTS_FETCHED",
  "message": "",
  "data": [
    {
      "item_code": "SKU010",
      "item_name": "Camera",
      "uom": "Nos",
      "all_uoms": [{"uom": "Nos", "conversion_factor": 1.0}],
      "qty": 28.0,
      "price": 900.0,
      "image": "..."
    }
  ],
  "meta": {
    "filters": {
      "price_list": "Standard Selling",
      "currency": "CNY",
      "warehouse": "Stores - RD",
      "company": null,
      "limit": 20
    }
  }
}
```

Frappe Desk / frontend:

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

Method:

- `myapp.api.gateway.create_order`

Arguments:

- `customer: str`
- `items: list[dict] | json-string`
- `immediate: bool = False`
- `company: str | None`
- `delivery_date: str | None`
- `transaction_date: str | None`
- `default_warehouse: str | None`
- `currency: str | None`
- `selling_price_list: str | None`
- `po_no: str | None`
- `remarks: str | None`

Item fields:

- `item_code`
- `qty`
- `warehouse`
- `uom` optional
- `price` optional
- `delivery_date` optional

Behavior:

- Creates and submits `Sales Order`.
- When `immediate=True`, also creates and submits `Delivery Note` and `Sales Invoice`.
- Validates warehouse-company consistency before document insert.
- Validates stock availability before immediate delivery.

Testing note:

- Use `immediate=0` when you plan to call `submit_delivery` and `create_sales_invoice` separately.
- If `immediate=1`, do not call those two APIs again for the same `Sales Order` unless there are remaining deliverable or billable quantities.

Example:

```python
from myapp.api.gateway import create_order

create_order(
    customer="Palmer Productions Ltd.",
    items=[{"item_code": "SKU010", "qty": 1, "warehouse": "Stores - RD"}],
    company="rgc (Demo)",
    immediate=True,
)
```

Example response:

```json
{
  "ok": true,
  "status": "success",
  "code": "ORDER_CREATED",
  "message": "订单 SAL-ORD-2026-00006 已完成下单、发货和开票。",
  "data": {
    "order": "SAL-ORD-2026-00006",
    "delivery_note": "MAT-DN-2026-00001",
    "sales_invoice": "ACC-SINV-2026-00006"
  },
  "meta": {}
}
```

HTTP example:

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

Frappe Desk / frontend:

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
  },
}).then((r) => {
  console.log(r.message.data.order);
});
```

### submit_delivery

Method:

- `myapp.api.gateway.submit_delivery`

Arguments:

- `order_name: str`
- `delivery_items: list[dict] | json-string | None = None`
- `kwargs: dict | json-string | None = None`

Behavior:

- Creates and submits a `Delivery Note` from a `Sales Order`.
- Supports partial delivery through `delivery_items`.
- Returns a clear validation error when the source `Sales Order` has no deliverable items left.

### create_sales_invoice

Method:

- `myapp.api.gateway.create_sales_invoice`

Arguments:

- `source_name: str`
- `invoice_items: list[dict] | json-string | None = None`
- `kwargs: dict | json-string | None = None`

Behavior:

- Creates and submits a `Sales Invoice` from a `Sales Order`.
- Supports partial invoicing through `invoice_items`.
- Returns a clear validation error when the source `Sales Order` has no billable items left.

### confirm_pending_document

Method:

- `myapp.api.gateway.confirm_pending_document`

Arguments:

- `doctype: str`
- `docname: str`
- `action: str | None`
- `updates: dict | json-string | None`
- `submit_on_confirm: int | bool = 1`

Behavior:

- Executes workflow action when `action` is provided.
- Otherwise submits draft documents by default.
- Falls back to `save()` when submission is not requested.

### update_payment_status

Method:

- `myapp.api.gateway.update_payment_status`

Arguments:

- `reference_doctype: str`
- `reference_name: str`
- `paid_amount: float`
- `mode_of_payment: str | None`
- `reference_no: str | None`
- `reference_date: str | None`

Behavior:

- Creates and submits `Payment Entry` from the reference document.

Example:

```python
from myapp.api.gateway import update_payment_status

update_payment_status(
    reference_doctype="Sales Invoice",
    reference_name="ACC-SINV-2026-00006",
    paid_amount=1,
)
```

HTTP example:

```bash
curl -X POST https://your-site.example.com/api/method/myapp.api.gateway.update_payment_status \
  -H "Authorization: token api_key:api_secret" \
  -H "Content-Type: application/json" \
  -d '{
    "reference_doctype": "Sales Invoice",
    "reference_name": "ACC-SINV-2026-00006",
    "paid_amount": 1
  }'
```

Frappe Desk / frontend:

```javascript
frappe.call({
  method: "myapp.api.gateway.update_payment_status",
  args: {
    reference_doctype: "Sales Invoice",
    reference_name: "ACC-SINV-2026-00006",
    paid_amount: 1,
  },
}).then((r) => {
  console.log(r.message.data.payment_entry);
});
```

### process_sales_return

Method:

- `myapp.api.gateway.process_sales_return`

Arguments:

- `source_doctype: str`
- `source_name: str`
- `return_items: list[dict] | json-string | None = None`
- `posting_date: str | None`
- `posting_time: str | None`
- `set_posting_time: int | bool | None`
- `remarks: str | None`

Behavior:

- Supports return creation from `Sales Invoice` and `Delivery Note`.
- Creates and submits the mapped return document.

Example:

```python
from myapp.api.gateway import process_sales_return

process_sales_return(
    source_doctype="Sales Invoice",
    source_name="ACC-SINV-2026-00006",
)
```

### Verified Sample Data

- `customer="Palmer Productions Ltd."`
- `item_code="SKU010"`
- `warehouse="Stores - RD"`
- `company="rgc (Demo)"`

### Known Business Constraints

- Warehouse must belong to the same company as the order.
- `immediate=True` requires available stock in the selected warehouse.
- If no `Bin` exists for an `item_code + warehouse` pair, immediate delivery is blocked.
