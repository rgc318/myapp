## API Gateway

Recommended custom API entry points:

- Sales and product:
- `myapp.api.gateway.search_product`
- `myapp.api.gateway.create_order`
- `myapp.api.gateway.submit_delivery`
- `myapp.api.gateway.create_sales_invoice`
- `myapp.api.gateway.update_payment_status`
- `myapp.api.gateway.process_sales_return`

- Purchase and settlement:
- `myapp.api.gateway.create_purchase_order`
- `myapp.api.gateway.receive_purchase_order`
- `myapp.api.gateway.create_purchase_invoice`
- `myapp.api.gateway.create_purchase_invoice_from_receipt`
- `myapp.api.gateway.record_supplier_payment`
- `myapp.api.gateway.process_purchase_return`
- `myapp.api.gateway.get_purchase_order_detail_v2`
- `myapp.api.gateway.get_purchase_order_status_summary`
- `myapp.api.gateway.get_purchase_receipt_detail_v2`
- `myapp.api.gateway.get_purchase_invoice_detail_v2`
- `myapp.api.gateway.get_supplier_purchase_context`
- `myapp.api.gateway.list_suppliers_v2`
- `myapp.api.gateway.get_supplier_detail_v2`
- `myapp.api.gateway.create_supplier_v2`
- `myapp.api.gateway.update_supplier_v2`
- `myapp.api.gateway.disable_supplier_v2`
- `myapp.api.gateway.update_purchase_order_v2`
- `myapp.api.gateway.update_purchase_order_items_v2`
- `myapp.api.gateway.cancel_purchase_order_v2`
- `myapp.api.gateway.cancel_purchase_receipt_v2`
- `myapp.api.gateway.cancel_purchase_invoice_v2`
- `myapp.api.gateway.cancel_supplier_payment`

- Shared utilities:
- `myapp.api.gateway.confirm_pending_document`

This document is primarily organized by business module, not by a binary split between custom APIs and official APIs.

Why:

- Callers usually think in terms of sales flow vs purchase flow.
- Frontend pages, tests, and implementation guides are easier to align by module.
- ERPNext / Frappe native APIs are better documented as underlying mappings, not as the main reading path.

This document only covers custom APIs from this app. ERPNext / Frappe native APIs are referenced only when the underlying mapping matters.

### Module Navigation

- Sales and product: `search_product`, `create_order`, `submit_delivery`, `create_sales_invoice`, `update_payment_status`, `process_sales_return`
- Purchase and settlement: `create_purchase_order`, `receive_purchase_order`, `create_purchase_invoice`, `create_purchase_invoice_from_receipt`, `record_supplier_payment`, `process_purchase_return`, `get_purchase_order_detail_v2`, `get_purchase_order_status_summary`, `get_purchase_receipt_detail_v2`, `get_purchase_invoice_detail_v2`, `get_supplier_purchase_context`, `list_suppliers_v2`, `get_supplier_detail_v2`, `create_supplier_v2`, `update_supplier_v2`, `disable_supplier_v2`, `update_purchase_order_v2`, `update_purchase_order_items_v2`, `cancel_purchase_order_v2`, `cancel_purchase_receipt_v2`, `cancel_purchase_invoice_v2`, `cancel_supplier_payment`
- Shared utilities: `confirm_pending_document`

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
- `request_id: str | None`
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
- When `immediate=True` and the same `request_id` is retried, returns the first successful result instead of creating new documents.

Testing note:

- Use `immediate=0` when you plan to call `submit_delivery` and `create_sales_invoice` separately.
- If `immediate=1`, do not call those two APIs again for the same `Sales Order` unless there are remaining deliverable or billable quantities.
- `request_id` is an idempotency key for the request, not a document primary key.
- Reuse the same `request_id` only when retrying the same business action.

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
    request_id: "order-idem-001",
  },
}).then((r) => {
  console.log(r.message.data.order);
});
```

### create_purchase_order

Method:

- `myapp.api.gateway.create_purchase_order`

Arguments:

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

Item fields:

- `item_code`
- `qty`
- `warehouse`
- `uom` optional
- `price` optional
- `schedule_date` optional

Behavior:

- Creates and submits `Purchase Order`.
- Validates warehouse-company consistency before document insert.
- When the same `request_id` is retried, returns the first successful `purchase_order`.

Example:

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

Method:

- `myapp.api.gateway.submit_delivery`

Arguments:

- `order_name: str`
- `delivery_items: list[dict] | json-string | None = None`
- `request_id: str | None`
- `posting_date: str | None`
- `posting_time: str | None`
- `set_posting_time: int | bool | None`
- `remarks: str | None`

Behavior:

- Creates and submits a `Delivery Note` from a `Sales Order`.
- Supports partial delivery through `delivery_items`.
- Supports overriding quantity and price in `delivery_items` by `sales_order_item` / `so_detail`, with `item_code` as fallback.
- When the same `request_id` is retried, returns the first successful `delivery_note`.
- Returns a clear validation error when the source `Sales Order` has no deliverable items left.

### create_sales_invoice

Method:

- `myapp.api.gateway.create_sales_invoice`

Arguments:

- `source_name: str`
- `invoice_items: list[dict] | json-string | None = None`
- `request_id: str | None`
- `due_date: str | None`
- `remarks: str | None`
- `update_stock: int | bool | None`

Behavior:

- Creates and submits a `Sales Invoice` from a `Sales Order`.
- Supports partial invoicing through `invoice_items`.
- Supports overriding quantity and price in `invoice_items` by `sales_order_item` / `so_detail`, with `item_code` as fallback.
- When the same `request_id` is retried, returns the first successful `sales_invoice`.
- Returns a clear validation error when the source `Sales Order` has no billable items left.

### receive_purchase_order

Method:

- `myapp.api.gateway.receive_purchase_order`

Arguments:

- `order_name: str`
- `receipt_items: list[dict] | json-string | None = None`
- `request_id: str | None`
- `posting_date: str | None`
- `posting_time: str | None`
- `set_posting_time: int | bool | None`
- `remarks: str | None`

Behavior:

- Creates and submits `Purchase Receipt` from a `Purchase Order`.
- Supports partial receipt through `receipt_items`.
- Supports overriding quantity and price in `receipt_items` by `purchase_order_item` / `po_detail`, with `item_code` as fallback.
- When the same `request_id` is retried, returns the first successful `purchase_receipt`.
- Returns a clear validation error when the source `Purchase Order` has no receivable items left.

### create_purchase_invoice

Method:

- `myapp.api.gateway.create_purchase_invoice`

Arguments:

- `source_name: str`
- `invoice_items: list[dict] | json-string | None = None`
- `request_id: str | None`
- `due_date: str | None`
- `remarks: str | None`
- `update_stock: int | bool | None`

Behavior:

- Creates and submits a `Purchase Invoice` from a `Purchase Order`.
- Supports partial invoicing through `invoice_items`.
- Supports overriding quantity and price in `invoice_items` by `purchase_order_item` / `po_detail`, with `item_code` as fallback.
- When the same `request_id` is retried, returns the first successful `purchase_invoice`.
- Returns a clear validation error when the source `Purchase Order` has no billable items left.

### create_purchase_invoice_from_receipt

Method:

- `myapp.api.gateway.create_purchase_invoice_from_receipt`

Arguments:

- `receipt_name: str`
- `invoice_items: list[dict] | json-string | None = None`
- `request_id: str | None`
- `due_date: str | None`
- `remarks: str | None`
- `update_stock: int | bool | None`

Behavior:

- Creates and submits a `Purchase Invoice` from a `Purchase Receipt`.
- Supports partial invoicing through `invoice_items`.
- Supports overriding quantity and price in `invoice_items` by `purchase_receipt_item` / `pr_detail`, with `item_code` as fallback.
- When the same `request_id` is retried, returns the first successful `purchase_invoice`.
- Returns a clear validation error when the source `Purchase Receipt` has no billable items left.

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
- `request_id: str | None`
- `mode_of_payment: str | None`
- `reference_no: str | None`
- `reference_date: str | None`

Behavior:

- Creates and submits `Payment Entry` from the reference document.
- When the same `request_id` is retried, returns the first successful `payment_entry`.

Example:

```python
from myapp.api.gateway import update_payment_status

update_payment_status(
    reference_doctype="Sales Invoice",
    reference_name="ACC-SINV-2026-00006",
    paid_amount=1,
    request_id="payment-idem-001",
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
    "paid_amount": 1,
    "request_id": "payment-idem-001"
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
    request_id: "payment-idem-001",
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
- `request_id: str | None`
- `posting_date: str | None`
- `posting_time: str | None`
- `set_posting_time: int | bool | None`
- `remarks: str | None`

Behavior:

- Supports return creation from `Sales Invoice` and `Delivery Note`.
- Creates and submits the mapped return document.
- When the same `request_id` is retried, returns the first successful return result.

### record_supplier_payment

Method:

- `myapp.api.gateway.record_supplier_payment`

Arguments:

- `reference_name: str`
- `paid_amount: float`
- `request_id: str | None`
- `mode_of_payment: str | None`
- `reference_no: str | None`
- `reference_date: str | None`

Behavior:

- Creates and submits `Payment Entry` from `Purchase Invoice`.
- When the same `request_id` is retried, returns the first successful `payment_entry`.

### process_purchase_return

Method:

- `myapp.api.gateway.process_purchase_return`

Arguments:

- `source_doctype: str`
- `source_name: str`
- `return_items: list[dict] | json-string | None = None`
- `request_id: str | None`
- `posting_date: str | None`
- `posting_time: str | None`
- `set_posting_time: int | bool | None`
- `remarks: str | None`

Behavior:

- Supports return creation from `Purchase Receipt` and `Purchase Invoice`.
- Supports specifying return quantity by detail line first, with `item_code` as fallback.
- Creates and submits the mapped purchase return document.
- When the same `request_id` is retried, returns the first successful return result.

### get_purchase_order_detail_v2

Method:

- `myapp.api.gateway.get_purchase_order_detail_v2`

Arguments:

- `order_name: str`

Behavior:

- Returns aggregated purchase order detail data for mobile detail pages.
- Returns supplier snapshot, amount summary, receiving status, payment status, line items, and downstream references.
- Returns action flags indicating whether the order can still be received, invoiced, updated, or cancelled.

Current key response fields:

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

Method:

- `myapp.api.gateway.get_purchase_order_status_summary`

Arguments:

- `supplier: str | None`
- `company: str | None`
- `limit: int | None = 20`

Behavior:

- Returns list-friendly purchase order status summaries.
- Each record is derived from the same aggregated detail semantics so the frontend does not need to infer received / invoiced / paid / completed states by itself.

### get_purchase_receipt_detail_v2

Method:

- `myapp.api.gateway.get_purchase_receipt_detail_v2`

Arguments:

- `receipt_name: str`

Behavior:

- Returns aggregated purchase receipt detail data.
- Returns source purchase orders, related purchase invoices, supplier snapshot, address snapshot, and item rows.
- Suitable for receipt detail pages and return confirmation pages.

### get_purchase_invoice_detail_v2

Method:

- `myapp.api.gateway.get_purchase_invoice_detail_v2`

Arguments:

- `invoice_name: str`

Behavior:

- Returns aggregated purchase invoice detail data.
- Returns source purchase order / receipt references, payment summary, latest payment result, and item rows.
- Suitable for invoice detail pages and supplier payment confirmation pages.

### get_supplier_purchase_context

Method:

- `myapp.api.gateway.get_supplier_purchase_context`

Arguments:

- `supplier: str`

Behavior:

- Returns supplier defaults and purchase context for order creation.
- Includes supplier summary, default contact, default address, recently used addresses, and suggested default warehouse.

### list_suppliers_v2

Method:

- `myapp.api.gateway.list_suppliers_v2`

Arguments:

- `search_key: str | None`
- `supplier_group: str | None`
- `disabled: int | bool | None`
- `limit: int | None = 20`
- `start: int | None = 0`
- `sort_by: str | None = "modified"`
- `sort_order: str | None = "desc"`

Behavior:

- Returns supplier list summaries.
- Supports fuzzy search, supplier group filtering, enabled / disabled filtering, and pagination.
- Each row includes default contact, default address, and recent purchase summary.

### get_supplier_detail_v2

Method:

- `myapp.api.gateway.get_supplier_detail_v2`

Arguments:

- `supplier: str`

Behavior:

- Returns aggregated supplier detail data.
- Includes default contact, default address, recent purchase addresses, and core master-data summary.

### create_supplier_v2

Method:

- `myapp.api.gateway.create_supplier_v2`

Arguments:

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

Behavior:

- Creates supplier master data.
- Can create and link a default contact and default address in the same call.
- Returns the created supplier detail snapshot.

### update_supplier_v2

Method:

- `myapp.api.gateway.update_supplier_v2`

Arguments:

- `supplier: str`
- Remaining fields are the same as `create_supplier_v2`

Behavior:

- Updates supplier master data.
- Can update the default contact and default address in the same call.
- Does not rewrite historical purchase-document snapshots.

### disable_supplier_v2

Method:

- `myapp.api.gateway.disable_supplier_v2`

Arguments:

- `supplier: str`
- `disabled: bool = True`

### update_purchase_order_v2

Method:

- `myapp.api.gateway.update_purchase_order_v2`

Arguments:

- `order_name: str`
- Additional update fields are passed as top-level args, for example:
  - `schedule_date`
  - `remarks`
  - `supplier_ref`
  - `request_id`

Behavior:

- Updates purchase order header fields using the v2 semantics.
- Intended for purchase order edit pages.
- When the same `request_id` is retried, returns the first successful result.

### update_purchase_order_items_v2

Method:

- `myapp.api.gateway.update_purchase_order_items_v2`

Arguments:

- `order_name: str`
- `items: list[dict] | json-string`
- `request_id: str | None`

Behavior:

- Replaces purchase order line items using the v2 semantics.
- Intended for editing the item section of a purchase order.
- When the same `request_id` is retried, returns the first successful result.

### cancel_purchase_order_v2

Method:

- `myapp.api.gateway.cancel_purchase_order_v2`

Arguments:

- `order_name: str`
- `request_id: str | None`

Behavior:

- Wraps purchase order cancellation with unified success codes and status output.

### cancel_purchase_receipt_v2

Method:

- `myapp.api.gateway.cancel_purchase_receipt_v2`

Arguments:

- `receipt_name: str`
- `request_id: str | None`

Behavior:

- Wraps purchase receipt cancellation with unified success codes and status output.

### cancel_purchase_invoice_v2

Method:

- `myapp.api.gateway.cancel_purchase_invoice_v2`

Arguments:

- `invoice_name: str`
- `request_id: str | None`

Behavior:

- Wraps purchase invoice cancellation with unified success codes and status output.

### cancel_supplier_payment

Method:

- `myapp.api.gateway.cancel_supplier_payment`

Arguments:

- `payment_entry_name: str`
- `request_id: str | None`

Behavior:

- Wraps supplier payment cancellation using the same response and error conventions as the settlement gateway.

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
- Purchase-side direct price overrides during receipt or invoicing require ERPNext `Buying Settings.maintain_same_rate` to be disabled.
- In the current environment, `Selling Settings.maintain_same_sales_rate = 0`, so sales price overrides during delivery and invoicing are allowed.
- For purchase list/detail/receipt/invoice pages, prefer the aggregated purchase APIs instead of manually stitching `Purchase Order / Purchase Receipt / Purchase Invoice / Payment Entry` state in the frontend.

### Appendix: Official APIs Used in Integration

These official APIs are not the primary business entry points of this app, but they are used in testing, frontend reads, debugging, and reconciliation.

Principles:

- Prefer `myapp.api.gateway.*` for write operations.
- Use official resource APIs for read operations when needed.
- Do not directly create or submit core sales / purchase documents through official APIs, otherwise you bypass idempotency, unified error handling, and business rules in the gateway layer.

#### 1. Login API

Used for host-side HTTP tests or frontend session-based integration.

Path:

- `POST /api/method/login`

Example:

```bash
curl -X POST http://localhost:8080/api/method/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d 'usr=Administrator&pwd=your-password'
```

#### 2. Resource Detail API

Used to read full documents and child rows, for example to fetch `items` from `Sales Order`, `Purchase Receipt`, `Sales Invoice`, or `Purchase Invoice` before calling the next gateway step by detail row.

Path:

- `GET /api/resource/<DocType>/<name>`

Common usage:

- Read `Sales Order` items to get `sales_order_item`
- Read `Purchase Order` items to get `purchase_order_item`
- Read `Purchase Receipt` items to get `purchase_receipt_item`
- Read `Delivery Note` / `Sales Invoice` / `Purchase Invoice` result details

Example:

```bash
curl -X GET \
  "http://localhost:8080/api/resource/Purchase%20Receipt/MAT-PRE-2026-00011" \
  -H "Authorization: token api_key:api_secret"
```

#### 3. Resource List API

Used to query resources by filters, for example stock ledger entries created by a receipt.

Path:

- `GET /api/resource/<DocType>?filters=...&fields=...`

Common usage:

- Query `Stock Ledger Entry`
- Query `Payment Entry` by condition
- Query result lists for specific vouchers

Example:

```bash
curl -X GET \
  "http://localhost:8080/api/resource/Stock%20Ledger%20Entry?filters=%5B%5B%22Stock%20Ledger%20Entry%22%2C%22voucher_no%22%2C%22%3D%22%2C%22MAT-PRE-2026-00011%22%5D%5D&fields=%5B%22name%22%2C%22voucher_no%22%2C%22actual_qty%22%2C%22incoming_rate%22%2C%22stock_value_difference%22%5D" \
  -H "Authorization: token api_key:api_secret"
```

#### 4. Official DocTypes Already Used in Integration

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

#### 5. Business Actions That Should Still Use the Custom Gateway

- Create sales order
- Create purchase order
- Deliver goods
- Receive goods
- Create sales invoice
- Create purchase invoice
- Record customer payment
- Record supplier payment
- Create sales return
- Create purchase return
- Confirm draft documents and run workflow actions
