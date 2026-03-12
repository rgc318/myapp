## API 网关文档

推荐使用以下自定义接口入口：

- 销售与商品：
- `myapp.api.gateway.search_product`
- `myapp.api.gateway.create_order`
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

- 销售与商品：`search_product`、`create_order`、`submit_delivery`、`create_sales_invoice`、`update_payment_status`、`process_sales_return`
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

行为：

- 基于 `Sales Order` 创建并提交 `Delivery Note`
- 支持通过 `delivery_items` 做部分发货
- 支持在 `delivery_items` 中按 `sales_order_item` / `so_detail` 或 `item_code` 改写数量与价格
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
- 支持在 `invoice_items` 中按 `sales_order_item` / `so_detail` 或 `item_code` 改写数量与价格
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
