# 《副食批发采购与进货流程技术设计文档》

## 1. 文档信息

- 文档名称：副食批发采购与进货流程技术设计文档
- 适用项目：`myapp` for Frappe / ERPNext
- 文档定位：作为采购订单、到货收货、采购结算、采购退货功能的实现基线
- 当前版本：v0.3
- 更新日期：2026-03-12

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

本期规划：

- 更多多行商品与复杂组合的部分开票边界测试

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

在 2026-03-12 的本轮开发与测试中，已通过宿主机 `python3` 直接访问 `http://localhost:8080` 的方式，对采购侧主链路完成真实 HTTP 验证。

已跑通的采购侧链路：

- `create_purchase_order`
- `receive_purchase_order`
- `create_purchase_invoice`
- `create_purchase_invoice_from_receipt`
- `record_supplier_payment`
- `process_purchase_return`

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

当前阶段结论：

- 采购主链路已经具备可重复执行的 HTTP 回归测试
- 采购结算已同时支持 `Purchase Order -> Purchase Invoice` 与 `Purchase Receipt -> Purchase Invoice`
- 部分收货、基于收货单的部分开票、基于收货单的部分退货已完成真实 HTTP 验证
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
