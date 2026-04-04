# 报表模块设计基线

## 目标

当前移动端报表模块已经具备基础总览与分析展示能力，但仍处于“单接口聚合过多内容”的阶段。

本设计文档用于明确：

- 当前一期正式化改造的边界
- 关键经营指标的统计口径
- 后端接口拆分策略
- 现金流模块优先改造方案

## 当前问题

### 1. 单个接口承载过多职责

`myapp.api.gateway.get_business_report_v1` 当前同时返回：

- 经营总览
- 销售分析
- 采购分析
- 应收汇总
- 应付汇总
- 商品排行
- 资金流水
- 趋势数据

这会带来几个问题：

- 前端不同模块重复请求同一份“大包数据”
- 很难针对单一模块做分页、缓存和慢查询优化
- 某一块口径变化时容易影响整包响应

### 2. 现金流明细与趋势需求不应共享同一套 limit

现金流趋势需要聚合数据，现金流明细需要分页列表。

如果二者共用同一个 `limit`：

- 明细可能被错误截断
- 趋势与列表的取数意图混在一起
- 前端容易误判“当前列表是否为全量结果”

### 3. 经营口径需要先固定，再继续扩前端展示

正式环境下，报表首先要解决“数字是否可信”，其次才是“图表是否丰富”。

## 一期改造范围

本期先做后端结构化拆分，不一次性重构整个报表域。

### 本期新增接口

#### `get_business_report_overview_v1`

用途：

- 提供报表首页卡片区所需 KPI

建议返回：

- `overview`
  - `sales_amount_total`
  - `purchase_amount_total`
  - `received_amount_total`
  - `paid_amount_total`
  - `net_cashflow_total`
  - `receivable_outstanding_total`
  - `payable_outstanding_total`
- `meta`
  - `company`
  - `date_from`
  - `date_to`

#### `get_sales_report_v1`

用途：

- 提供销售分析页所需的总览 KPI
- 提供销售趋势、商品排行与小时分布

建议返回：

- `overview`
  - `sales_amount_total`
  - `received_amount_total`
  - `receivable_outstanding_total`
- `tables`
  - `sales_summary`
  - `sales_trend`
  - `sales_trend_hourly`
  - `sales_product_summary`
- `meta`
  - `company`
  - `date_from`
  - `date_to`
  - `limit`

#### `get_purchase_report_v1`

用途：

- 提供采购分析页所需的总览 KPI
- 提供采购趋势、商品排行与小时分布

建议返回：

- `overview`
  - `purchase_amount_total`
  - `paid_amount_total`
  - `payable_outstanding_total`
- `tables`
  - `purchase_summary`
  - `purchase_trend`
  - `purchase_trend_hourly`
  - `purchase_product_summary`
- `meta`
  - `company`
  - `date_from`
  - `date_to`
  - `limit`

#### `get_cashflow_report_v1`

用途：

- 提供资金总览 KPI
- 提供资金趋势图数据

建议返回：

- `overview`
  - `received_amount_total`
  - `paid_amount_total`
  - `net_cashflow_total`
- `trend`
  - 按 `posting_date` 聚合的收入 / 支出趋势
- `meta`
  - `company`
  - `date_from`
  - `date_to`

#### `list_cashflow_entries_v1`

用途：

- 提供可分页的现金流明细列表

建议返回：

- `rows`
  - `name`
  - `posting_date`
  - `direction`
  - `party_type`
  - `party`
  - `mode_of_payment`
  - `amount`
  - `reference_no`
- `pagination`
  - `page`
  - `page_size`
  - `total_count`
  - `has_more`
- `meta`
  - `company`
  - `date_from`
  - `date_to`

#### `get_receivable_payable_report_v1`

用途：

- 提供应收账款表和应付账款表所需总览与聚合表

建议返回：

- `overview`
  - `receivable_outstanding_total`
  - `payable_outstanding_total`
- `tables`
  - `receivable_summary`
  - `payable_summary`
- `meta`
  - `company`
  - `date_from`
  - `date_to`
  - `limit`

## 统计口径

### 统一过滤规则

除非后续版本另有说明，一期报表统一遵循：

- 仅统计 `docstatus = 1` 的已提交单据
- 如果传入 `company`，则按公司过滤
- 时间范围使用对应单据的业务日期字段

### 现金流口径

资金流水基于 `Payment Entry`：

- 日期字段：`posting_date`
- 收入：
  - `payment_type = 'Receive'`
- 支出：
  - `payment_type = 'Pay'`
- 其他类型：
  - 当前归类为 `transfer`

金额规则：

- 收入优先使用 `received_amount`
- 支出优先使用 `paid_amount`
- 若主要字段为空，则回退到另一金额字段

### 经营总览中的现金流口径

总览中的：

- `received_amount_total`
- `paid_amount_total`
- `net_cashflow_total`

均来自 `Payment Entry` 的区间汇总，不尝试映射回销售或采购单据日期。

## 后续拆分路线

现金流接口拆完后，继续按模块拆分：

1. `get_business_report_overview_v1`
2. `get_sales_report_v1`
3. `get_purchase_report_v1`
4. `get_receivable_payable_report_v1`

拆分原则：

- 总览接口只返回首页需要的 KPI
- 销售分析只返回销售相关表与趋势
- 采购分析只返回采购相关表与趋势
- 分页列表与聚合图表分开

## 测试要求

### 一期必须补齐

- 现金流总览接口返回结构测试
- 现金流趋势聚合测试
- 现金流分页边界测试
- 日期范围校验测试
- 公司过滤参数透传测试

### 二期建议补齐

- 多公司真实对账测试
- 跨月与跨季度聚合测试
- 大数据量性能基线测试

## 前端接入建议

在后端现金流接口拆分完成后，移动端应改为：

- 销售分析请求 `get_sales_report_v1`
- 采购分析请求 `get_purchase_report_v1`
- 总览卡片请求 `get_business_report_overview_v1`
- 应收/应付表请求 `get_receivable_payable_report_v1`
- 趋势图请求 `get_cashflow_report_v1`
- 明细列表请求 `list_cashflow_entries_v1`

不要再通过提高 `limit` 来模拟“全量明细”，也不要继续让销售/采购分析页重复拉取整包经营报表。
