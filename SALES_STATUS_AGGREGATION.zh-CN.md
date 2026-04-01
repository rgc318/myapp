# 《销售单聚合状态与详情接口设计文档》

## 1. 文档目标

本文档用于定义销售单在移动端 / Web 端业务页面中需要展示的“聚合状态”与“详情口径”，避免前端直接依赖 ERPNext 原生单据状态字段进行自行拼装和推断。

本文档重点解决以下问题：

- 销售单是否已出货
- 销售单是否已送达
- 销售单货款是否已结清
- 销售单是否可以视为“已完成”
- 应收、实收、未收金额如何统一口径
- 前端是否应该自行拼接 `Sales Order` / `Delivery Note` / `Sales Invoice` / `Payment Entry`

结论先行：

- 前端不应自行拼装这些状态
- 状态应由后端聚合接口统一计算后返回
- ERPNext 原生状态字段只作为底层事实来源，不直接作为前端最终业务状态

## 2. 为什么需要聚合状态接口

当前销售链路的事实来源分散在多个单据中：

- `Sales Order`：订单主单、计划数量
- `Delivery Note`：实际出货
- `Sales Invoice`：应收与结算口径
- `Payment Entry`：实际收款
- Return 单据：退货与红冲

因此，类似以下状态都不是单个 DocType 字段能完整表达的：

- 是否已全部出货
- 是否已全部送达
- 是否已全部结清
- 是否已完成整单闭环

如果前端自行拼接：

- 容易出现状态口径不一致
- 页面间会重复实现相同计算逻辑
- 后续引入“送达确认”“退货冲减”“部分开票”“部分收款”后会不断返工

因此建议新增后端聚合接口，把“底层事实”和“前端可直接展示的业务状态”一次性返回。

## 3. 状态设计原则

### 3.1 两层口径分离

返回结构应分成两层：

1. 底层事实层

- 原始数量
- 已发货数量
- 已开票数量
- 应收金额
- 已收金额
- 未收金额

2. 聚合状态层

- 发货状态
- 送达状态
- 收款状态
- 完成状态

### 3.2 先做“真实可判定状态”

第一阶段建议只对系统中已有事实支持的状态做强判定：

- `是否已出货`
- `是否已结清`
- `是否已完成`

“是否已送达”需要有明确的送达确认动作或配送签收数据支撑，否则不应伪造状态。

### 3.3 结清以发票应收口径为准

“是否已结清”不建议直接按销售订单金额判断，而应以财务应收口径判断。

推荐口径：

- `receivable_amount`：销售发票应收总额
- `paid_amount`：已收总额
- `outstanding_amount`：未收总额

判定规则：

- `outstanding_amount <= 0` 视为已结清

## 4. 推荐聚合状态字段

### 4.1 发货状态

字段：

- `fulfillment.total_qty`
- `fulfillment.delivered_qty`
- `fulfillment.remaining_qty`
- `fulfillment.status`
- `fulfillment.is_fully_delivered`

推荐枚举：

- `pending`：未出货
- `partial`：部分出货
- `shipped`：已全部出货

推荐规则：

- `delivered_qty <= 0` -> `pending`
- `0 < delivered_qty < total_qty` -> `partial`
- `delivered_qty >= total_qty` -> `shipped`

### 4.2 送达状态

字段：

- `delivery.status`
- `delivery.delivered_at`
- `delivery.delivery_confirmed_by`

第一阶段推荐枚举：

- `unknown`：系统尚未接入送达确认
- `pending`：未送达
- `delivered`：已送达

当前阶段建议：

- 如系统尚无送达确认动作，统一返回 `unknown`
- 不要用“已出货”直接替代“已送达”

### 4.3 收款状态

字段：

- `payment.receivable_amount`
- `payment.paid_amount`
- `payment.outstanding_amount`
- `payment.status`
- `payment.is_fully_paid`

推荐枚举：

- `unpaid`：未收款
- `partial`：部分收款
- `paid`：已结清

推荐规则：

- `paid_amount <= 0` 且 `receivable_amount > 0` -> `unpaid`
- `0 < paid_amount < receivable_amount` -> `partial`
- `outstanding_amount <= 0` -> `paid`

边界说明：

- 如果销售单尚未生成发票，可将 `receivable_amount` 视为当前已开票应收，而不是订单理论金额
- 订单页面可以同时返回 `order_amount_estimate` 作为业务参考，但“是否结清”只按发票口径判断

### 4.4 完成状态

字段：

- `completion.status`
- `completion.is_completed`

第一阶段推荐枚举：

- `open`：进行中
- `completed`：已完成
- `closed`：已关闭 / 人工终止 / 作废

第一阶段推荐规则：

- `is_fully_delivered == true` 且 `is_fully_paid == true` -> `completed`
- 否则 -> `open`

第二阶段可升级规则：

- 若后续引入送达确认，则可升级为：
  `is_fully_delivered && delivery.status == "delivered" && is_fully_paid`

## 5. 推荐返回结构

建议详情接口返回如下结构：

```json
{
  "order_name": "SO-0001",
  "document_status": "submitted",
  "customer": {
    "name": "Palmer Productions Ltd."
  },
  "amounts": {
    "order_amount_estimate": 1000,
    "receivable_amount": 1000,
    "paid_amount": 600,
    "outstanding_amount": 400
  },
  "fulfillment": {
    "total_qty": 20,
    "delivered_qty": 12,
    "remaining_qty": 8,
    "status": "partial",
    "is_fully_delivered": false
  },
  "delivery": {
    "status": "unknown",
    "delivered_at": null,
    "delivery_confirmed_by": null
  },
  "payment": {
    "receivable_amount": 1000,
    "paid_amount": 600,
    "outstanding_amount": 400,
    "status": "partial",
    "is_fully_paid": false
  },
  "completion": {
    "status": "open",
    "is_completed": false
  },
  "actions": {
    "can_submit_delivery": true,
    "can_create_sales_invoice": true,
    "can_record_payment": true,
    "can_process_return": true
  }
}
```

## 6. 建议新增的接口

### 6.1 `get_sales_order_detail`

用途：

- 销售单详情页
- 发货前确认页
- 开票前确认页
- 收款前查看整单状态

建议返回：

- 单据头信息
- 客户快照
- 收货信息快照
- 商品明细
- 金额汇总
- 聚合状态
- 可执行动作

### 6.2 `get_sales_order_status_summary`

用途：

- 列表页卡片状态展示
- 首页待办/最近单据摘要

建议返回：

- `order_name`
- `customer_name`
- `transaction_date`
- `fulfillment.status`
- `payment.status`
- `completion.status`
- `outstanding_amount`

补充说明：

- 该接口适合首页待办、最近订单、轻量摘要卡片
- 若后续要制作销售工作台，不建议继续把它当成真实搜索接口
- 工作台查询应改用 `search_sales_orders_v2`，由后端统一处理：
  - `search_key`
  - `customer`
  - `company`
  - `status_filter`
  - `exclude_cancelled`
  - `sort_by`
  - `limit`
  - `start`

### 6.3 第二阶段接口

若后续接入送达确认，可继续新增：

- `confirm_sales_delivery`

用途：

- 手动确认已送达
- 记录签收时间、签收人、签收备注

## 7. 各状态的底层事实来源建议

### 7.1 发货相关

来源建议：

- `Sales Order Item.qty`
- `Delivery Note Item.qty`
- `so_detail` / `against_sales_order` 关联字段

### 7.2 开票与应收相关

来源建议：

- `Sales Invoice Item`
- `Sales Invoice.outstanding_amount`
- `Sales Invoice.grand_total` / `rounded_total`

### 7.3 收款相关

来源建议：

- `Payment Entry`
- 发票未收金额字段

说明：

- 第一阶段建议优先按发票未收金额聚合，不要重复造一套复杂对账引擎

### 7.4 退货相关

来源建议：

- Return `Delivery Note`
- Return `Sales Invoice`

说明：

- 第一阶段可以先不把退货引入“完成状态”的复杂抵扣规则
- 但详情接口中建议预留：
  - `returned_qty`
  - `returned_amount`
- 当前销售退货后端已补：
  - `get_return_source_context_v2`
  - `process_sales_return` 增强返回
- 当前这套退货能力应明确理解为：
  - “来源单据依据版销售退货”
  - 即退货必须基于单一 `Delivery Note` 或单一 `Sales Invoice`
  - 适用于严格可追溯的标准逆向冲销
- 对已收款销售发票执行退货时，当前会建议前端进入：
  - `review_refund`
- 这表示系统当前支持“退货单创建 + 后续退款提示”，但尚未在退货接口中自动生成退款闭环
- 当前不应将其直接等同于：
  - 多订单混合退货
  - 多批次混合退货
  - 现场自由退货中心

## 8. 当前阶段推荐实现范围

### 第一阶段必须实现

- `get_sales_order_detail`
- 发货状态计算
- 收款状态计算
- 完成状态计算
- `actions` 可执行动作判断

### 第一阶段先预留、不强实现

- 真实送达状态
- 复杂退货冲减后的完成态
- 一单多收款方式的更细粒度渠道汇总

## 9. 前端使用约束

前端应遵守以下原则：

- 不自行通过多个原子接口拼装“是否结清”“是否完成”
- 不直接把 ERPNext 原生 `status` 字段当成最终业务状态
- 优先显示后端聚合后的 `fulfillment` / `payment` / `completion`
- 如果 `delivery.status = unknown`，前端展示为“待确认送达”或“不显示送达状态”，不要误显示为“已送达”

## 10. 建议的后续开发顺序

1. 先实现 `get_sales_order_detail`
2. 先把 `fulfillment` / `payment` / `completion` 三组状态做准
3. 先不实现真实送达，统一返回 `unknown`
4. 后续若业务确定了签收动作，再新增送达确认接口

## 11. 当前结论

对销售单来说：

- “是否已出货”应由发货事实聚合判断
- “是否已结清”应由发票应收与实收聚合判断
- “是否已完成”应由出货状态与结清状态联合判断
- “是否已送达”需要单独的配送确认数据，当前不应由“已出货”替代

因此，这一块明确应通过新的销售单聚合接口实现，而不是由前端自行拼接计算。
