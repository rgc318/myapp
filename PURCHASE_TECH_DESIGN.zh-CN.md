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
  -> create_purchase_invoice
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
- 支持按 `item_code + qty` 指定本次实收数量
- 若部分到货，本次仅收本次数量
- 若某个订单行本次未到货，可以不生成到目标单据
- 最终库存入账以 `Purchase Receipt` 为准

#### 6.2.3 当前实现状态

已实现：

- `receive_purchase_order`
- 基于采购订单生成采购收货单
- `request_id` 幂等支持
- 顺序重放验证

本期规划：

- 按实收到货数量过滤和改写明细
- 更多部分收货边界测试

### 6.3 模块 P3：采购发票与结算

#### 6.3.1 目标

在采购收货完成后，按实际业务需要生成采购发票并登记付款。

#### 6.3.2 关键业务规则

- 支持从 `Purchase Order` 直接生成 `Purchase Invoice`
- 后续应优先评估是否补充“从 `Purchase Receipt` 生成采购发票”的业务封装
- 支持部分开票
- 支持按实际应付金额登记付款
- 付款动作支持幂等

#### 6.3.3 当前实现状态

已实现：

- `create_purchase_invoice`
- `record_supplier_payment`
- 采购发票创建与供应商付款主链路已验证
- 付款动作已支持 `request_id` 幂等与顺序重放验证

本期规划：

- `Purchase Receipt -> Purchase Invoice` 的独立封装
- 更多部分开票边界测试

### 6.4 模块 P4：采购退货

#### 6.4.1 目标

支持将问题货、错发货、临期货退回供应商。

#### 6.4.2 关键业务规则

- 支持从 `Purchase Receipt` 发起采购退货
- 支持从 `Purchase Invoice` 发起借项红冲
- 支持部分退货
- 退货时应遵循 ERPNext 原生 return 机制

#### 6.4.3 当前实现状态

已实现：

- `process_purchase_return`
- 支持从 `Purchase Invoice` 发起采购退货
- `request_id` 幂等支持
- 顺序重放验证

本期规划：

- 从 `Purchase Receipt` 发起退货的更多验证
- 部分退货边界测试

## 6.5 本轮测试补充

在 2026-03-12 的本轮开发与测试中，已通过宿主机 `python3` 直接访问 `http://localhost:8080` 的方式，对采购侧主链路完成真实 HTTP 验证。

已跑通的采购侧链路：

- `create_purchase_order`
- `receive_purchase_order`
- `create_purchase_invoice`
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
- 现阶段最关键的幂等风险点已完成验证
- 从 `Purchase Receipt` 直接生成采购发票的独立封装，仍然是后续优先事项

## 7. 建议接口清单

建议新增以下网关接口：

- `myapp.api.gateway.create_purchase_order`
- `myapp.api.gateway.receive_purchase_order`
- `myapp.api.gateway.create_purchase_invoice`
- `myapp.api.gateway.record_supplier_payment`
- `myapp.api.gateway.process_purchase_return`

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

建议的函数原型：

```python
def create_purchase_order(supplier: str, items, **kwargs): ...
def receive_purchase_order(order_name: str, receipt_items=None, **kwargs): ...
def create_purchase_invoice(source_name: str, invoice_items=None, **kwargs): ...
def record_supplier_payment(reference_name: str, paid_amount: float, **kwargs): ...
def process_purchase_return(source_doctype: str, source_name: str, return_items=None, **kwargs): ...
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

当前 `myapp` 已完成销售侧第一版网关封装，但采购侧仍是空白。下一阶段最合适的新增方向是采购与进货模块，且可以在不推翻现有结构的前提下平滑扩展：

- 复用现有三层结构
- 复用统一响应和幂等工具
- 复用 ERPNext 原生采购映射能力
- 按“采购订单 -> 收货入库 -> 采购发票 -> 付款 -> 退货”逐步落地

在终端建设上，采购流程后续优先面向移动作业场景设计，并与打印模板、扫码能力同步考虑。
