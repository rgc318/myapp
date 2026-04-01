# 《副食批发采购与进货流程技术设计文档》

## 1. 文档信息

- 文档名称：副食批发采购与进货流程技术设计文档
- 适用项目：`myapp` for Frappe / ERPNext
- 文档定位：作为采购订单、到货收货、采购结算、采购退货功能的实现基线
- 当前版本：v0.4
- 更新日期：2026-04-01

## 2. 适用场景

本文档面向当前以管理员、内勤和仓管人员为主的后台操作场景，重点覆盖：

- 先下采购订单，再通知供应商备货
- 供应商实际到货数量与订单数量可能不完全一致
- 入库和结算以实际到货为准，而不是完全以采购订单为准
- 存在到货后再付款、部分付款、按实际收货金额结算的需求
- 存在向供应商退货的逆向流程

本文档不覆盖：

- 供应商门户或供应商自助确认页面
- 复杂采购审批流
- 到货质检子流程
- 批次、效期、拒收仓等高级仓储能力

## 3. 业务目标

建设一套采购侧业务网关，保持与当前销售侧网关一致的设计风格，对 ERPNext 原生采购单据进行二次封装，实现：

- 采购订单快速创建
- 按实际到货生成采购收货单
- 按实际收货结果生成采购发票
- 采购付款登记
- 采购退货处理
- 统一响应格式、统一错误码、统一幂等策略

## 3.1 终端策略补充

采购与进货流程后续将优先面向移动端和平板端落地，主要原因是：

- 到货收货、扫码入库、现场确认更适合移动作业端
- 打印模板固定后，移动端只需做预览确认，不需要复杂排版编辑
- 对于较大的正式单据，桌面 Web 端仍可作为补充预览和打印入口

当前建议分工：

- 移动作业端：扫码、收货、入库、现场确认、打印预览
- 桌面 Web 端：查询、追踪、补打、较大单据打印
- ERPNext 后台：主数据、财务底层、系统配置

## 4. 目标业务流程

### 4.1 标准采购流程

```text
Client
  -> create_purchase_order
  <- Purchase Order
  -> receive_purchase_order
  <- Purchase Receipt
  -> create_purchase_invoice / create_purchase_invoice_from_receipt
  <- Purchase Invoice
  -> record_supplier_payment
  <- Payment Entry
```

### 4.2 采购退货流程

```text
Client
  -> process_purchase_return(source_doctype, source_name)
  <- Return Purchase Receipt / Return Purchase Invoice
```

### 4.3 关键原则

- 采购订单表示“预期采购”
- 采购收货单表示“实际到货”
- 采购发票与付款应优先依据“实际到货 / 实际结算”处理
- 若采购订单与到货不一致，系统应允许按实收数量调整
- 采购订单主要用于对外下单、沟通和打印，不直接作为最终入库事实依据
- 收货时应允许按实际到货结果修改数量、价格，并移除未到货商品
- 最终库存入账应以 `Purchase Receipt` 为准，而不是以 `Purchase Order` 为准
- 若收货完成后发生问题货、错货、临期退回等情况，应单独生成采购退货单，不应直接回改原收货单
- 同一业务动作重复重试时，应支持 `request_id` 幂等
- 扫码与打印能力优先围绕主流设备和固定模板建设，不在第一阶段追求全品牌全协议适配

## 5. DocType 映射

| 业务动作 | 主要 DocType | 说明 |
| --- | --- | --- |
| 创建采购订单 | `Purchase Order` | 向供应商发出采购需求 |
| 到货入库 | `Purchase Receipt` | 按实际到货数量收货入库 |
| 应付开票 | `Purchase Invoice` | 记录应付金额和采购票据 |
| 供应商付款 | `Payment Entry` | 基于采购发票登记付款 |
| 采购退货 | Return `Purchase Receipt` / Return `Purchase Invoice` | 对供应商执行退货或红字冲销 |

## 6. 模块设计

### 6.1 模块 P1：采购订单

#### 6.1.1 目标

支持管理员通过接口快速创建并提交采购订单。

#### 6.1.2 建议能力

- `create_purchase_order` 作为采购侧统一入口
- 支持传入 `supplier`
- 支持传入采购明细 `items`
- 支持默认 `company`
- 支持行级 `warehouse`
- 支持备注、供应商订单号、期望到货日期
- 支持生成可打印、可发送给供应商的采购订单
- 订单中的数量和价格应允许业务人员继续调整，以适应供应商报价波动

#### 6.1.2.A 当前价格与单位口径补充

- 商品主数据当前只提供一个默认采购价口径：
  - `Standard Buying`
- 当前采购链路不区分：
  - 批发采购价
  - 零售采购价
- 采购单移动端 / 前端当前约定：
  - 新加入商品时，采购单位默认带入商品库存基准单位 `stock_uom`
  - 若现场业务需要，允许操作员再切换为箱、包等其他业务单位
  - 订单行数量仍应通过 `uom_conversions` 换算回库存基准单位
- 因此文档口径上应区分：
  - 商品级默认采购参考价
  - 订单行实际采购价
- 前者用于默认带值与参考展示，后者才是本次采购单真正成交口径

#### 6.1.2.B 当前默认入库仓口径补充

- 采购单移动端当前将“默认入库仓”定义为：
  - 本单新增商品默认带入的入库仓
  - 其职责属于采购单页，不属于商品搜索页
- 当前默认入库仓的优先级应为：
  - 当前公司默认仓
  - 若当前公司没有默认仓，再回退到供应商建议仓
  - 操作员手动修改后，以手动结果为准
- 商品搜索页当前只负责：
  - 搜索商品
  - 预览库存与参考采购价
  - 快速加入采购草稿
- 商品搜索页不再承担：
  - 每个商品独立切换目标入库仓
  - 采购行级仓库管理
- 采购行真正的仓库拆分、修改与校验，仍应在采购单页内完成
- 后端当前已补充采购公司上下文读取能力：
  - 服务入口：`get_purchase_company_context(company)`
  - 网关入口：`myapp.api.gateway.get_purchase_company_context`
  - 语义：按当前公司返回采购默认仓
  - 不负责返回供应商建议仓；供应商建议仍由 `get_supplier_purchase_context` 提供

#### 6.1.3 关键校验

- `supplier` 不可为空
- `items` 不可为空
- `qty` 必须大于 0
- `warehouse` 必须存在
- 仓库必须与采购单公司一致

#### 6.1.4 当前实现状态

已实现：

- 采购订单创建与提交
- 仓库与公司归属校验
- `request_id` 幂等支持
- 顺序幂等重放验证
- 同一 `request_id` 不同请求数据验证
- 不同 `request_id` 不同请求数据验证
- 并发条件下同一 `request_id` 验证

本期规划：

- 供应商默认参数和更多边界场景补充

### 6.2 模块 P2：到货收货与入库

#### 6.2.1 目标

根据采购订单生成采购收货单，并允许按实际到货结果调整数量和明细。

#### 6.2.2 关键业务规则

- 从 `Purchase Order` 映射生成 `Purchase Receipt`
- 默认只映射“尚未完全收货”的明细
- 支持按实际到货结果改写本次实收数量
- 支持在收货时按实际情况修改本次收货价格
- 若部分到货，本次仅收本次数量
- 若某个订单行本次未到货，可以不生成到目标单据，等价于整行移除
- 最终库存入账以 `Purchase Receipt` 为准
- 收货完成后，若后续需要退回供应商，应通过独立退货单处理，而不是回改原收货单

#### 6.2.3 当前实现状态

已实现：

- `receive_purchase_order`
- 基于采购订单生成采购收货单
- 支持按采购订单明细或 `item_code` 改写本次收货数量
- 支持按采购订单明细或 `item_code` 改写本次收货价格
- 支持在收货时移除本次未到货商品
- `request_id` 幂等支持
- 顺序重放验证

本期规划：

- 更多多行商品与复杂组合的部分收货边界测试

### 6.3 模块 P3：采购发票与结算

#### 6.3.1 目标

在采购收货完成后，按实际业务需要生成采购发票并登记付款。

### 6.6 快捷链路编排

为对齐销售侧已落地的快捷链路，采购侧当前已补齐两个“编排型”网关，避免移动端串行拼接 3~4 次写接口调用。

#### 6.6.1 `quick_create_purchase_order_v2`

目标：

- 在一个入口中按条件连续执行：
  - 创建采购订单
  - 可选立即收货
  - 可选立即开票
  - 可选立即付款

建议原则：

- 默认仅创建采购订单（最稳妥）
- `immediate_*` 作为显式开关，不做隐式自动联动
- 每一步都需要返回明确结果，便于前端展示“已完成步骤”

当前实现口径：

- 已实现 `myapp.api.gateway.quick_create_purchase_order_v2`
- 已完成真实 HTTP 回归验证
- 当前支持覆盖：
  - 仅下采购订单
  - 下单后立即收货
  - 下单后立即收货并开票
  - 下单后立即收货、开票并登记付款
- 对于“付款步骤失败”的场景，当前已验证可通过相同业务请求继续恢复后续付款

#### 6.6.2 `quick_cancel_purchase_order_v2`

目标：

- 在一个入口中完成采购链路逆向回退，并将采购订单恢复到“可继续编辑”的 `submitted` 状态

建议回退顺序（必须严格逆序）：

1. 付款单 `Payment Entry`
2. 采购发票 `Purchase Invoice`
3. 采购收货单 `Purchase Receipt`

当前实现口径：

- 快捷回退的职责是撤销下游单据，不直接作废采购订单本身
- 成功后应返回最新 `get_purchase_order_detail_v2(order_name)` 结果
- 前端可直接依据返回的 `detail.actions.can_receive_purchase_order` / `detail.actions.can_create_purchase_invoice` 判断订单已恢复为可编辑状态

建议保护规则：

- 若存在“多张发票 / 多张收货单 / 多笔付款”且超出快捷回退安全边界，应明确拒绝并提示改用分步回退
- 回退结果应返回每一步是否执行、执行成功与否，避免前端误判
- 若存在采购退货单，当前会体现在“多张采购收货单 / 多张采购发票”的保护分支中，快捷回退应保守拒绝

当前已验证口径：

- 已实现 `myapp.api.gateway.quick_cancel_purchase_order_v2`
- 当前按如下逆序回退：
  - `Payment Entry`
  - `Purchase Invoice`
  - `Purchase Receipt`
- 快捷回退成功后：
  - 不直接作废采购订单
  - 采购订单保留为可继续编辑的 `submitted`
  - 前端应直接依据返回的 `detail.actions` 刷新下一步动作
- 当前保护分支已完成真实 HTTP 验证：
  - 多张采购收货单时拒绝快捷回退
  - 多张采购发票时拒绝快捷回退
  - 多笔有效付款时拒绝快捷回退
  - 已付款但 `rollback_payment=false` 时拒绝快捷回退
  - 存在采购退货单时，当前会落入“多张采购收货单 / 多张采购发票”的保守拒绝分支
- 当前也已验证：
  - 中途失败后的恢复
  - 手动先回退一部分后，再走快捷回退
  - 快捷回退后重新走分步 `收货 -> 开票 -> 付款`

#### 6.3.2 关键业务规则

- 支持从 `Purchase Order` 直接生成 `Purchase Invoice`
- 支持从 `Purchase Receipt` 生成 `Purchase Invoice`
- 支持部分开票
- 支持按实际结算结果改写开票数量与价格
- 支持按实际应付金额登记付款
- 付款动作支持幂等
- 从业务上更推荐按 `Purchase Receipt` 的实际收货结果生成采购发票，以保持应付口径与实收入库一致

#### 6.3.3 当前实现状态

已实现：

- `create_purchase_invoice`
- `create_purchase_invoice_from_receipt`
- `record_supplier_payment`
- 采购发票创建与供应商付款主链路已验证
- `Purchase Receipt -> Purchase Invoice` 主链路已完成真实 HTTP 验证
- 基于 `Purchase Receipt` 的部分开票场景已完成真实 HTTP 验证
- 付款动作已支持 `request_id` 幂等与顺序重放验证
- 付款动作已完成同一 `request_id` 并发竞争验证
- 已确认 `paid_amount <= 0` 会直接拒绝
- 已确认超额付款会直接拒绝，不会作为 unallocated amount 挂账

本期规划：

- 更多多行商品与复杂组合的部分开票边界测试

#### 6.3.4 当前采购结算限制补充

当前系统存在一个已确认限制：

- 通用结算网关 `myapp.api.gateway.update_payment_status` 在销售发票上支持 `settlement_mode="writeoff"` 成功结清
- 但在采购发票上，当前真实 HTTP 行为是：
  - 返回 `当前无需执行差额核销。`
  - 不会生成付款单
  - 不会污染采购订单详情中的 `paid_amount / outstanding_amount / total_writeoff_amount`

因此当前采购侧结算口径应理解为：

- 标准付款：支持
- 部分付款：支持
- 多笔付款后快捷回退：不支持，应走分步回退
- 采购 `writeoff` 成功结清：当前尚未打通，不应在前端以“可正常使用”能力对外承诺

### 6.4 模块 P4：采购退货

#### 6.4.1 目标

支持将问题货、错发货、临期货退回供应商。

#### 6.4.2 关键业务规则

- 支持从 `Purchase Receipt` 发起采购退货
- 支持从 `Purchase Invoice` 发起借项红冲
- 支持部分退货
- 退货时应遵循 ERPNext 原生 return 机制
- 退货应单独生成 return 单据，不直接回改原 `Purchase Receipt`
- 若已经进入结算阶段，应同时考虑库存退回和应付冲减的口径一致性

#### 6.4.3 当前实现状态

已实现：

- `process_purchase_return`
- 支持从 `Purchase Invoice` 发起采购退货
- 支持从 `Purchase Receipt` 发起采购退货
- `request_id` 幂等支持
- 顺序重放验证
- 基于 `Purchase Receipt` 的部分退货场景已完成真实 HTTP 验证

本期规划：

- 多行商品条件下按明细行退货的更多验证
- 更复杂的部分退货边界测试

## 6.5 本轮测试补充

在 2026-04-01 的本轮开发与测试中，已通过宿主机 `python3` 直接访问 `http://localhost:8080` 的方式，对采购快捷链路与采购付款边界完成真实 HTTP 验证。

已跑通的采购侧链路：

- `create_purchase_order`
- `receive_purchase_order`
- `create_purchase_invoice`
- `create_purchase_invoice_from_receipt`
- `record_supplier_payment`
- `process_purchase_return`
- `quick_create_purchase_order_v2`
- `quick_cancel_purchase_order_v2`

已验证可用的当前样例主数据：

- `supplier="MA Inc."`
- `item_code="SKU010"`
- `warehouse="Stores - RD"`
- `company="rgc (Demo)"`

已补充的幂等验证类型：

- 同一 `request_id` 顺序重放
- 同一 `request_id` 但不同请求数据
- 不同 `request_id` 且不同请求数据
- 并发条件下同一 `request_id`
- 并发条件下同一 `request_id` 的付款动作只落一笔付款

当前阶段结论：

- 采购主链路已经具备可重复执行的 HTTP 回归测试
- 采购结算已同时支持 `Purchase Order -> Purchase Invoice` 与 `Purchase Receipt -> Purchase Invoice`
- 部分收货、基于收货单的部分开票、基于收货单的部分退货已完成真实 HTTP 验证
- 采购快捷开单 / 快捷回退已经具备独立 HTTP 回归文件
- 采购回退的恢复场景、付款边界、退货边界与并发误触场景均已完成验证
- 采购 `writeoff` 当前限制已经通过真实 HTTP 行为确认
- `myapp/tests/http/test_gateway_http.py` 已重构为可独立执行的链路测试，单条运行、分组运行和整份全量运行均已重新回归通过

## 6.6 当前系统设置约束补充

当前环境验证表明，若 ERPNext `Buying Settings` 中启用 `maintain_same_rate`，则系统会阻止 `Purchase Receipt` / `Purchase Invoice` 相对 `Purchase Order` 的价格变动。

对于存在“下单后供应商实际到货价格可能变化”需求的采购场景，建议：

- 取消勾选 `maintain_same_rate`
- 再允许在收货和基于收货单开票时传入实际价格

在 2026-03-12 的本轮真实 HTTP 验证中，关闭 `maintain_same_rate` 后：

- 收货时改价可成功提交
- 基于收货单的部分开票改价可成功提交

当前代码补充说明：

- `receive_purchase_order`
- `create_purchase_invoice`
- `create_purchase_invoice_from_receipt`

在检测到请求中包含 `price` 改写时，会主动检查 `Buying Settings.maintain_same_rate`。

若该设置重新启用，接口会直接返回明确业务错误，提示应先关闭该设置或先修改源采购订单价格，而不是落成 ERPNext 原生底层报错。

若后续重新启用 `maintain_same_rate`，则价格浮动场景需要改为：

- 先更新 `Purchase Order` 价格
- 再继续执行收货与开票
- 现阶段最关键的幂等风险点已完成验证
- `create_purchase_invoice_from_receipt` 已完成独立封装并通过真实 HTTP 验证

## 7. 建议接口清单

当前已实现的采购侧网关接口：

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
- `myapp.api.gateway.update_purchase_order_v2`
- `myapp.api.gateway.update_purchase_order_items_v2`
- `myapp.api.gateway.cancel_purchase_order_v2`
- `myapp.api.gateway.cancel_purchase_receipt_v2`
- `myapp.api.gateway.cancel_purchase_invoice_v2`
- `myapp.api.gateway.cancel_supplier_payment`

建议保持现有三层结构：

- `gateway`：统一响应、错误码、幂等行为说明
- `api`：薄转发层
- `services`：采购业务逻辑

### 7.1 `get_purchase_order_detail_v2` 字段语义对照

采购订单详情聚合当前混合了三类口径：

- 订单口径：采购订单自身金额与基础信息
- 收货口径：采购收货推进情况
- 发票 / 付款口径：基于已生成采购发票和付款单的应付结算状态

移动端消费时应明确区分，避免把“订单金额”和“已开票应付金额”混用。

| 返回路径 | 当前语义 | 主要来源 | 前端建议展示 |
| --- | --- | --- | --- |
| `purchase_order_name` | 采购订单号 | `Purchase Order.name` | 订单主标题 / 单号 |
| `document_status` | 单据状态：`draft/submitted/cancelled` | `Purchase Order.docstatus` | 单据状态 |
| `amounts.order_amount_estimate` | 订单理论金额 | `Purchase Order.rounded_total/grand_total` | `订单金额` / `预计采购金额` |
| `amounts.receivable_amount` | 已开票口径的应付金额汇总，不是订单理论金额 | 已关联 `Purchase Invoice` 聚合 | 不建议直接显示为“订单应付”；更适合标记为“已开票应付” |
| `amounts.paid_amount` | 已付款汇总 | 已关联 `Payment Entry` 聚合 | 已付款 |
| `amounts.outstanding_amount` | 已开票但未付金额 | 已关联 `Purchase Invoice` 的 `outstanding_amount` 汇总 | 待付款 / 未结清金额 |
| `receiving.total_qty` | 订单总采购数量 | `Purchase Order Item.qty` 汇总 | 总数量 |
| `receiving.received_qty` | 累计已收数量 | `Purchase Order Item.received_qty` 汇总 | 已收数量 |
| `receiving.remaining_qty` | 待收数量 | `total_qty - received_qty` | 待收数量 |
| `receiving.status` | 收货状态：`pending/partial/received` 等 | 收货汇总规则 | 收货状态 |
| `payment.status` | 付款状态，按已开票应付口径推导 | 发票 + 付款聚合 | 付款状态 |
| `completion.status` | 订单完成状态，综合收货 / 付款 / 单据状态 | 完成状态规则 | 完成状态 |
| `actions.can_receive_purchase_order` | 是否还能继续收货 | 提交状态 + 收货完成度 | “继续收货”按钮 |
| `actions.can_create_purchase_invoice` | 是否还能继续开票 | 提交状态 + 付款/开票完成度 | “继续开票”按钮 |
| `actions.can_record_supplier_payment` | 是否允许录入供应商付款 | `outstanding_amount > 0` | “去付款”按钮 |
| `actions.can_process_purchase_return` | 是否允许做采购退货 | 当前订单 / 下游单据状态 | “采购退货”按钮 |
| `references.purchase_receipts` | 已关联采购收货单列表 | 来源引用聚合 | 下游单据引用 |
| `references.purchase_invoices` | 已关联采购发票列表 | 来源引用聚合 | 下游单据引用 |
| `items[].qty` | 订单行数量 | `Purchase Order Item.qty` | 明细数量 |
| `items[].received_qty` | 订单行累计已收数量 | `Purchase Order Item.received_qty` | 明细已收数量 |
| `items[].rate` | 订单行采购单价 | `Purchase Order Item.rate` | 明细单价 |
| `items[].amount` | 订单行金额 | `Purchase Order Item.amount` | 明细金额 / 小计 |
| `items[].warehouse` | 订单行当前入库仓 | `Purchase Order Item.warehouse` | 明细仓库 |
| `meta.company` | 订单所属公司 | `Purchase Order.company` | 公司 |
| `meta.transaction_date` | 下单日期 | `Purchase Order.transaction_date` | 下单日期 |
| `meta.schedule_date` | 计划到货日期 | `Purchase Order.schedule_date` | 计划到货 |

当前前端页面建议遵守以下展示规则：

- `订单金额` 只使用 `amounts.order_amount_estimate`
- `收货状态 / 待收数量` 只使用 `receiving.*`
- `付款状态 / 待付款金额` 只使用 `payment.*` 或 `amounts.outstanding_amount`
- 不要把 `amounts.receivable_amount` 直接文案化成“订单总价”或“采购总额”
- 若页面需要同时展示订单口径与发票口径，应明确区分：
  - `订单金额`
  - `已开票应付`
  - `已付款`
  - `待付款`

### 7.2 `get_purchase_receipt_detail_v2` 动作字段补充

为避免移动端仅凭单据状态做按钮判断，采购收货单详情聚合建议以前置动作字段为主，而不是自行推断：

- `actions.can_cancel_purchase_receipt`
  - 含义：当前收货单是否允许作废
  - 典型限制：已有关联采购发票时不可直接作废
- `actions.cancel_purchase_receipt_hint`
  - 含义：当不可作废时的后端提示
  - 前端建议：直接展示该提示，不要写死本地文案
- `actions.can_create_purchase_invoice`
  - 含义：当前收货单是否还能继续开票
  - 典型口径：已提交且尚无关联采购发票时为 `true`

前端展示建议：

- `继续开票` 按钮优先读取 `actions.can_create_purchase_invoice`
- `作废收货单` 按钮优先读取 `actions.can_cancel_purchase_receipt`
- 当 `can_cancel_purchase_receipt = false` 时，应在回退区域展示 `cancel_purchase_receipt_hint`
- 若页面存在链路回退操作，建议按“先回退发票，再回退收货”的顺序引导，避免用户在不可作废状态下反复尝试

## 8. 与 ERPNext 原生能力的映射关系

当前仓库中的 ERPNext 原生入口可直接复用：

- `erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_receipt`
- `erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_invoice`
- `erpnext.controllers.sales_and_purchase_return.make_return_doc`

实现建议：

- `create_purchase_order`
  建议直接 `frappe.new_doc("Purchase Order")` + 明细组装 + `insert/submit`
- `receive_purchase_order`
  建议复用 `make_purchase_receipt(source_name, args=...)`
- `create_purchase_invoice`
  第一阶段建议复用 `make_purchase_invoice(source_name, args=...)`
- `process_purchase_return`
  建议复用 `make_return_doc("Purchase Receipt" | "Purchase Invoice", source_name)`
- `record_supplier_payment`
  建议复用 `get_payment_entry("Purchase Invoice", reference_name, party_amount=...)`

## 9. 建议代码落点

在当前 `myapp` 结构下，建议新增采购侧模块而不是把采购逻辑硬塞进现有销售服务：

- 新增服务模块：`myapp.services.purchase_service`
- 新增 API 转发层：`myapp.api.purchase_api`
- 在 `myapp.api.gateway` 中补采购接口入口
- 复用现有：
  - `myapp.utils.api_response`
  - `myapp.utils.idempotency`

当前已落地的核心函数原型：

```python
def create_purchase_order(supplier: str, items, **kwargs): ...
def receive_purchase_order(order_name: str, receipt_items=None, **kwargs): ...
def create_purchase_invoice(source_name: str, invoice_items=None, **kwargs): ...
def create_purchase_invoice_from_receipt(receipt_name: str, invoice_items=None, **kwargs): ...
def record_supplier_payment(reference_name: str, paid_amount: float, **kwargs): ...
def process_purchase_return(source_doctype: str, source_name: str, return_items=None, **kwargs): ...
def get_purchase_order_detail_v2(order_name: str): ...
def get_purchase_order_status_summary(...): ...
def get_purchase_receipt_detail_v2(receipt_name: str): ...
def get_purchase_invoice_detail_v2(invoice_name: str): ...
def get_supplier_purchase_context(supplier: str): ...
```

## 10. 第一阶段开发顺序

建议按以下顺序推进，而不是一次性全做：

1. `create_purchase_order`
2. `receive_purchase_order`
3. `create_purchase_invoice`
4. `record_supplier_payment`
5. `process_purchase_return`
6. 移动作业端扫码与打印预览联动

原因：

- 先打通“下采购单 -> 到货入库”主链路
- 再补“应付和付款”
- 最后补“退货”逆向链路

## 11. 当前结论

当前 `myapp` 已完成销售侧与采购侧第一版网关封装，采购主链路、采购聚合读取层和供应商上下文层均已落地。下一阶段最合适的新增方向是继续围绕移动端采购页面补细节，而不是再从零建设采购基础网关：

- 复用现有三层结构
- 复用统一响应和幂等工具
- 复用 ERPNext 原生采购映射能力
- 按“采购订单 -> 收货入库 -> 采购发票 -> 付款 -> 退货”逐步落地

在终端建设上，采购流程后续优先面向移动作业场景设计，并与打印模板、扫码能力同步考虑。
