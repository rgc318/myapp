# 《副食批发业务二次开发需求及技术设计文档》

## 1. 文档信息

- 文档名称：副食批发业务二次开发需求及技术设计文档
- 适用项目：`myapp` for Frappe / ERPNext
- 文档定位：作为后续开发、接口联调、测试验收和团队协作的统一基准
- 当前版本：v1.3
- 更新日期：2026-03-12

## 2. 文档目标

本文档用于明确副食批发业务的二次开发范围、现阶段技术方案、接口设计约束和后续扩展方向，避免需求只停留在口头讨论、聊天记录或零散代码中。

本文档关注以下目标：

- 统一业务语言，降低产品、开发、测试、实施之间的理解偏差
- 明确当前 `myapp` 网关接口的职责边界和调用方式
- 约束开发实现，减少后续需求迭代时的结构性返工
- 为后续新增信用控制、批次管理、打印集成等能力预留设计空间

## 3. 业务背景

副食批发业务的特点与标准 ERPNext 长流程存在明显错位：

- 下单频率高，单据量大
- 商品单位复杂，常见箱、包、瓶、件等换算
- 现场业务要求响应快，不能依赖冗长审批或手工多步录单
- 库存实时性要求高，销售员需要边看库存边成交
- 结算模式混合，既有现结，也有预付、部分支付和账期
- 存在损耗、临期、错配等退货场景

标准 ERPNext 流程通常为：

`Quotation -> Sales Order -> Delivery Note -> Sales Invoice -> Payment Entry`

对副食批发现场来说，这条链路过长，因此本项目通过 `myapp` 自定义网关接口对核心流程做自动化封装，以降低录单步骤并保留 ERPNext 的账、货、库存主数据能力。

当前阶段补充说明：

- 本项目当前主要面向管理员、内勤、仓配或销售人员代客操作
- 暂不包含客户自助下单前端
- 因此当前开发优先级更偏向内部操作效率、幂等、安全校验和库存一致性，而不是前台用户风控

## 4. 建设目标与范围

### 4.1 总体目标

建设一个面向副食批发场景的轻量业务网关层，对 ERPNext 原生单据能力进行二次封装，实现：

- 快速下单
- 即时发货与即时开票
- 移动端商品搜索
- 现场收款
- 销售退货

### 4.2 当前纳入范围

- 销售订单创建
- 发货单创建与提交
- 销售发票创建与提交
- 商品搜索
- 收款登记
- 销售退货
- 草稿单据确认 / 工作流动作触发
- 统一 API 返回格式
- Postman 联调集合

补充说明：

- 采购与进货流程已单独立项，详见 `PURCHASE_TECH_DESIGN.zh-CN.md`
- 本文档当前主体仍聚焦销售侧业务网关

### 4.3 当前不纳入范围

- 客户自助下单前端
- 完整替代 ERPNext 的独立管理后台
- 全品牌打印机深度驱动适配
- 批次先进先出拣货引擎
- 客户授信冻结与额度审批流
- 复杂促销、搭赠、返利规则

### 4.4 版本分层说明

为避免“文档目标”和“当前代码状态”混淆，本文档对需求按三层口径描述：

- 已实现：代码已落地并完成基本联调
- 本期规划：应优先进入下一阶段开发或完善
- 后续规划：方向明确，但当前不进入实施

除非特别说明，文档中的“当前实现状态”均以仓库现状为准，而非纯业务愿景。

### 4.5 前端与终端策略

基于当前业务讨论，后续前端建设采用以下原则：

- 优先建设面向管理员、内勤、仓管人员的业务操作端，而不是客户自助前台
- 移动端与平板端是第一优先级，核心用于扫码、收货、入库、发货、确认和打印预览
- 桌面 Web 端保留，用于较大单据预览、打印、查询追踪和补充管理操作
- ERPNext 后台继续承担主数据、财务底层、系统配置和复杂管理职责
- 不在当前阶段额外建设完整替代 ERPNext 的独立管理后台

当前前端技术方向基线：

- 移动作业端优先按独立项目规划
- 技术选型优先考虑 Flutter 一类适合设备能力接入的移动技术
- 大单据打印优先采用固定模板 + 预览确认 + 系统打印或标准打印能力
- 前端需围绕现有 `myapp.api.gateway.*` 网关接口建设，而不是直接暴露 ERPNext 原生复杂接口

## 5. 业务流程设计

### 5.1 快速下单

目标：将标准流程压缩为单接口调用。

流程分为两种模式：

1. 分步模式：`immediate = 0`
2. 联动模式：`immediate = 1`

分步模式适用于：

- 先录单，后续再发货
- 需要人工确认库存或运输安排
- 接口联调与调试阶段

联动模式适用于：

- 现场成交即出货
- 钱货两清
- 对库存与价格规则较明确的门店/仓配场景

业务规则：

- 创建 `Sales Order`
- 若 `immediate=1`，继续自动创建并提交 `Delivery Note`
- 若 `immediate=1`，继续自动创建并提交 `Sales Invoice`
- 任一步失败时，整体事务回滚，不产生残留单据

### 5.2 商品搜索

目标：让销售员通过名称、编码或条码，快速拿到可卖商品信息。

业务规则：

- 支持按 `Item Code`
- 支持按 `Item Name`
- 支持按 `Barcode`
- 结果只返回未禁用且允许销售的商品
- 默认限制返回数量，防止全表扫描拉爆接口响应
- 可按仓库或公司范围计算库存
- 返回所有可用 UOM 转换信息，便于现场报价

### 5.2.1 单位换算规则基线

单位换算是副食批发场景的核心，不应只停留在“展示所有 UOM”的层面。当前与后续规则基线如下：

- 当前搜索接口会返回库存单位 `uom` 和所有换算单位 `all_uoms`
- 当前下单接口允许传入 `uom`，但业务方仍需明确该 `qty` 与 `rate` 的计价口径
- 当前实现未单独增加“按销售单位自动换算库存单位”的显式服务规则，主要依赖 ERPNext 原生单据逻辑
- 后续应补齐“按箱下单、按瓶出库、按销售单位计价”的明确规则文档和测试

后续必须明确的规则点：

- `qty` 默认口径是库存单位还是销售单位
- `rate` 对应的单位口径
- 开票单位与发货单位不一致时的换算责任边界
- 小数数量、拆箱销售和最小销售单位限制

### 5.3 收款与结算

目标：将“发票 + 收款”关联起来，减少财务二次补录。

业务规则：

- 基于 `Sales Invoice` 生成 `Payment Entry`
- 支持现金、微信、银行转账等支付方式
- 支持部分支付
- 默认把收款日期记为当天
- 默认生成业务可理解的收款参考说明

### 5.4 退货处理

目标：支持现场退货、破损退货、临期退货等逆向业务。

业务规则：

- 支持从 `Sales Invoice` 发起退货
- 支持从 `Delivery Note` 发起退货
- 退货单据采用 ERPNext 原生 return 机制
- 财务上形成红字冲销
- 库存上回补原仓或目标仓

说明：

当前实现依赖 ERPNext 原生退货逻辑完成库存和财务联动，不单独重复造轮子。

## 6. 核心功能模块设计

### 6.1 模块 A：快速下单与“钱货两清”

#### 6.1.1 需求说明

支持业务员在移动端、H5、小程序或快速录入页通过一个接口完成下单；在联动场景下，自动继续完成发货与开票。

#### 6.1.2 关键能力

- `create_order` 作为统一入口
- 根据 `immediate` 决定是否联动创建 `Delivery Note` 和 `Sales Invoice`
- 自动读取用户默认 `company`
- 自动推导默认配送日期
- 支持通过 `default_warehouse` 补齐行仓库
- 通过 Frappe 数据库事务保证原子性

边界说明：

- 当前实现是“支持默认仓库参数”，不是“已从客户档案自动提取客户默认仓库”
- 若后续要实现客户默认仓库，应明确优先级：行级仓库 > 请求级 `default_warehouse` > 客户默认仓库 > 系统默认仓库

#### 6.1.3 当前实现状态

已实现：

- 销售订单创建
- 联动创建发货与开票
- 仓库与公司归属校验
- 即时发货前库存可用量校验
- 空目标明细的明确错误提示
- `request_id` 幂等支持
- 同一 `request_id` 顺序重放验证
- 同一 `request_id` 不同请求数据验证
- 不同 `request_id` 不同请求数据验证
- 并发条件下同一 `request_id` 验证

本期规划：

- 客户默认仓库自动取值
- 客户默认配送路线 / 配送日期策略
- 价格规则和促销规则联动
- 客户信用额度校验

### 6.2 模块 B：增强型商品搜索系统

#### 6.2.1 需求说明

面向销售员、仓配人员、现场开单员提供高频商品检索能力。

#### 6.2.2 关键能力

- 多维匹配：编码、名称、条码
- 库存实时总览：基于 `Bin` 汇总库存
- 单位换算回传：基于 `UOM Conversion Detail`
- 价格展示：基于 `Item Price`
- 结果限制：默认 20 条，当前实现允许 1 到 100 条

#### 6.2.3 当前实现状态

已实现：

- 名称 / 编码 / 条码检索
- 商品库存汇总
- 多 UOM 列表回传
- 价格回传
- 过滤 `disabled = 0` 且 `is_sales_item = 1`
- 已通过 HTTP 方式对 `SKU010` 等真实样例完成联调验证

### 6.2.4 本轮测试补充

在 2026-03-12 的本轮开发与测试中，已通过宿主机 `python3` 直接访问 `http://localhost:8080` 的方式，对销售侧主链路完成真实 HTTP 验证，而不是只做本地服务层导入测试。

已跑通的销售侧链路：

- `search_product`
- `create_order`
- `submit_delivery`
- `create_sales_invoice`
- `update_payment_status`
- `process_sales_return`

已补充的幂等验证类型：

- 同一 `request_id` 顺序重放
- 同一 `request_id` 但不同请求数据
- 不同 `request_id` 且不同请求数据
- 并发条件下同一 `request_id`

当前阶段结论：

- 销售主链路已经具备可重复执行的 HTTP 回归测试
- 现阶段最关键的幂等风险点已完成验证
- 部分发货、部分开票等更细边界可在后续迭代补充

本期规划：

- 返回仓库维度分仓库存
- 支持最近成交价 / 客户专属价
- 支持模糊拼音
- 支持高频商品缓存和搜索排序优化

### 6.3 模块 C：灵活收款与结算

#### 6.3.1 需求说明

支持现结、预付、部分收款等典型批发结算场景。

#### 6.3.2 关键能力

- 根据发票生成收款凭证
- 支持多 `Mode of Payment`
- 允许传入参考号和参考日期
- 自动回写应收核销链路

#### 6.3.3 当前实现状态

已实现：

- 基于 `Sales Invoice` 创建 `Payment Entry`
- 默认模式可回退到 `Cash`
- 支持自定义 `mode_of_payment`
- 支持部分收款

本期规划：

- 预付款冲抵
- 一单多支付方式
- 第三方支付流水号校验
- 收款时间字段标准化

建议补充字段：

- `paid_at` 或 `received_at`
- `cashier`
- `external_trade_no`
- `channel`

### 6.4 模块 D：逆向物流（退货）

#### 6.4.1 需求说明

覆盖损耗、错送、临期和客户拒收等退货场景。

#### 6.4.2 关键能力

- 支持发票退货
- 支持发货单退货
- 支持部分退货
- 自动生成红字退货单

#### 6.4.3 当前实现状态

已实现：

- 从 `Sales Invoice` 或 `Delivery Note` 自动生成 return document
- 支持按 `item_code + qty` 做部分退货

本期规划：

- 退货原因编码
- 退货品相分级
- 退货入库仓策略
- 退货审核流

边界说明：

- 当前文档中的“库存回库”与“财务红冲”均依赖 ERPNext 原生 return 逻辑完成
- 当前实现不是额外再造一套独立的“红字发票 + 退货入库单”双单引擎
- 若后续出现“财务退货”和“实物退货”分离的业务场景，需要补充新的业务类型与状态设计

## 7. 技术架构设计

### 7.1 分层结构

当前 `myapp` 采用三层封装：

1. `gateway` 层  
   对外暴露 Frappe `whitelist` 接口，负责统一响应包与错误码转换

2. `api` 层  
   作为模块转发层，保持网关接口稳定，降低服务层重构影响

3. `services` 层  
   承载业务逻辑、单据创建、参数校验和 ERPNext 原生能力调用

### 7.2 当前代码入口

- 网关入口：`myapp.api.gateway`
- 订单服务：`myapp.services.order_service`
- 商品搜索服务：`myapp.services.wholesale_service`
- 结算与退货服务：`myapp.services.settlement_service`
- 返回包装：`myapp.utils.api_response`

### 7.3 设计原则

- 保持对 ERPNext 原生单据的复用，而非重写底层流程
- 所有对外接口返回统一 JSON 包
- 业务错误优先在服务层显式抛出，避免落成底层通用报错
- 优先通过配置与参数扩展，而不是复制接口
- 对交易型接口提供基于 `request_id` 的幂等重试能力

## 8. 关键业务边界

以下规则应视为当前接口设计的硬约束：

- 已完全发货的 `Sales Order` 不允许再次创建发货单
- 已完全开票的 `Sales Order` 不允许再次创建销售发票
- `message` 文案仅用于展示，调用方不得以自然语言文案做业务分支判断
- 调用方应以 `ok`、`code` 和 `data` 作为判断依据
- ERPNext 返回的 `_server_messages` 可能是提示、警告或附加信息，不等同于失败
- 分步模式与联动模式必须分别联调，不能混用旧单据号复测完整流程

## 9. 关键数据结构与 DocType 映射

| 功能模块 | 主要 DocType | 关键字段 / 方法 | 说明 |
| --- | --- | --- | --- |
| 快速下单 | `Sales Order` | `customer`, `items`, `company`, `delivery_date` | 作为销售主单据 |
| 发货处理 | `Delivery Note` | `items`, `posting_date`, `posting_time` | 从 `Sales Order` 映射生成 |
| 开票处理 | `Sales Invoice` | `items`, `due_date`, `update_stock` | 从 `Sales Order` 映射生成 |
| 商品搜索 | `Item`, `Bin`, `Item Price`, `UOM Conversion Detail` | `actual_qty`, `price_list_rate`, `conversion_factor` | 返回销售决策信息 |
| 收款结算 | `Payment Entry` | `paid_amount`, `reference_name`, `mode_of_payment` | 基于发票收款 |
| 退货处理 | Return `Sales Invoice` / Return `Delivery Note` | `is_return`, `return_against` | 使用 ERPNext 原生 return 机制 |

## 10. API 设计基线

### 10.1 对外接口清单

| 接口 | 方法路径 | 用途 |
| --- | --- | --- |
| 下单 | `myapp.api.gateway.create_order` | 创建销售订单，支持联动发货开票 |
| 发货 | `myapp.api.gateway.submit_delivery` | 从销售订单创建发货单 |
| 开票 | `myapp.api.gateway.create_sales_invoice` | 从销售订单创建销售发票 |
| 商品搜索 | `myapp.api.gateway.search_product` | 搜索商品、价格、库存和单位 |
| 收款 | `myapp.api.gateway.update_payment_status` | 基于发票生成收款单 |
| 退货 | `myapp.api.gateway.process_sales_return` | 从发票或发货单发起退货 |
| 单据确认 | `myapp.api.gateway.confirm_pending_document` | 草稿提交或工作流动作触发 |

### 10.2 统一响应结构

成功响应：

```json
{
  "message": {
    "ok": true,
    "status": "success",
    "code": "ORDER_CREATED",
    "message": "销售订单 SAL-ORD-2026-00007 已创建并提交。",
    "data": {},
    "meta": {}
  }
}
```

失败响应：

```json
{
  "message": {
    "ok": false,
    "status": "error",
    "code": "VALIDATION_ERROR",
    "message": "商品 SKU010 在仓库 成品 - R 没有库存记录，系统按可用库存 0 处理，本次需要 1.0。",
    "data": {},
    "meta": {}
  }
}
```

### 10.3 错误码约定

当前已统一映射的错误码包括：

- `VALIDATION_ERROR`
- `PERMISSION_DENIED`
- `AUTHENTICATION_REQUIRED`
- `RESOURCE_NOT_FOUND`
- `DUPLICATE_ENTRY`
- `WORKFLOW_ACTION_INVALID`
- `INSUFFICIENT_STOCK`
- `INTERNAL_ERROR`

说明：

- 对调用方来说，应优先消费 `code` 和 `data`
- `message` 作为展示文案，不应作为强依赖解析字段
- `_server_messages` 可能由 ERPNext 额外附带，前端需做好兼容

## 11. 事务、异常与一致性设计

### 11.1 事务原则

Frappe Web Request 默认运行在单次请求事务中。

因此在 `create_order(immediate=1)` 场景下：

- 若 `Sales Order` 创建成功
- 但 `Delivery Note` 或 `Sales Invoice` 任何一步失败

则整次请求应整体失败，数据库事务回滚，不保留残留主单。

### 11.2 异常处理原则

- 参数错误：在服务层提前校验并抛业务错误
- 库存不足：优先返回明确库存错误
- 源单无可发货 / 可开票明细：返回清晰业务错误
- 非预期异常：记录 `Error Log`，统一返回 `INTERNAL_ERROR`

### 11.3 已落地的异常场景

- 客户为空
- `items` 为空
- 公司为空
- 仓库不存在
- 仓库与公司不匹配
- 即时发货库存不足
- 无库存记录
- 无可发货明细
- 无可开票明细
- 无可退货明细

### 11.4 幂等与重复提交控制

当前状态：

- 交易型接口已支持基于 `request_id` 的幂等控制
- 相同业务动作重试时会直接返回第一次成功结果

风险场景：

- 移动端重复点击“提交”
- 弱网重试
- 第三方系统回调重复推送
- Postman / 自动化脚本误重复执行

建议优先级：

- 高优先级，应早于打印集成落地

建议方案：

- 所有交易型接口支持 `request_id`
- 在网关层或独立幂等表中记录 `request_id -> result_docname`
- 对高频交易动作优先实现
- 对重复请求直接返回已有结果而不是再次创建单据

当前已实现：

- `create_order`
- `submit_delivery`
- `create_sales_invoice`
- `update_payment_status`
- `process_sales_return`

说明：

- `request_id` 不是单据编号，也不是数据库主键
- `request_id` 应由前端或上游系统生成，并在同一笔业务重试时保持不变
- 不同业务动作不应复用同一个 `request_id`

## 12. 关键接口时序

### 12.1 分步模式

```text
Client
  -> create_order(immediate=0)
  <- Sales Order
  -> submit_delivery(order_name)
  <- Delivery Note
  -> create_sales_invoice(source_name)
  <- Sales Invoice
  -> update_payment_status(reference_name)
  <- Payment Entry
```

### 12.2 联动模式

```text
Client
  -> create_order(immediate=1)
     -> create Sales Order
     -> submit Delivery Note
     -> create Sales Invoice
  <- order + delivery_note + sales_invoice
```

### 12.3 退货模式

```text
Client
  -> process_sales_return(source_doctype, source_name)
  <- return_document
```

## 13. Postman 联调规范

### 13.1 版本说明

当前 Postman 文件分为两个版本：

- `postman/myapp-gateway-v1.postman_collection.json`
- `postman/myapp-gateway-v2.postman_collection.json`
- `postman/myapp-local-v1.postman_environment.json`
- `postman/myapp-local-v2.postman_environment.json`

### 13.2 适用场景

`v1`：

- 主下单接口名为 `create_order_immediate`
- 默认 `immediate=1`
- 适合演示一键下单、发货、开票的完整链路

`v2`：

- 主下单接口名为 `create_order_step_by_step`
- 默认 `immediate=0`
- 适合联调、排错和分步验证

### 13.3 联调约束

- 同一个 `Sales Order` 不应在已经完全发货后再次调用 `submit_delivery`
- 同一个 `Sales Order` 不应在已经完全开票后再次调用 `create_sales_invoice`
- `message` 文案可用于展示，但判断成功失败必须以 `ok` 和 `code` 为准
- 若返回含 `_server_messages`，需区分提示信息与真正失败

建议增加的联调用例：

- 跨公司仓库校验失败
- 可用库存不足
- 无 `Bin` 记录
- 已完全发货后重复发货
- 已完全开票后重复开票
- 部分退货
- 部分收款

## 14. 非功能性要求

### 14.1 性能要求

- 商品搜索默认结果量控制在 20 条
- 高频接口避免返回过重的单据结构
- 优先使用 Frappe ORM 和 Query Builder 聚合查询

### 14.2 可维护性要求

- 新需求优先扩展 `services` 层
- 网关层保持薄封装
- 错误码不可随意变更
- 新接口必须补文档和联调样例

### 14.3 可观测性要求

- 业务失败要能在 `Error Log` 中追踪
- 非预期异常统一 `frappe.log_error`
- 联调阶段保留可复制的错误文案

## 15. 待优化与后续规划

### 15.1 批次与保质期管理

目标：

- 副食品批次追踪
- 临期预警
- 出库优先早期批次（FIFO）

建议设计：

- 在选品与发货时引入批次策略服务
- 允许按商品启用批次必填
- 搜索结果补充批次和有效期视图

### 15.2 客户信用控制

目标：

- 防止超额赊销

建议设计：

- 在 `create_order` 提交前校验客户未收余额
- 超额时禁止提交或进入审批
- 对联动模式和分步模式保持统一控制口径

当前优先级说明：

- 该能力保留在规划中
- 由于当前系统主要由管理员代客录单和出货，暂不作为最近阶段优先开发项

### 15.3 打印集成

目标：

- 在订单完成、收货完成或结算完成后触发单据打印
- 支持固定格式的大单据打印，单据尺寸以半 A4 至 A4 场景为主

建议设计：

- 打印模板预先固化，移动端只负责预览确认，不要求用户手动调整缩放和页面尺寸
- 打印能力优先兼容主流品牌打印机，不追求第一阶段覆盖所有品牌和所有连接协议
- 优先支持标准系统打印或主流打印能力，再逐步扩展设备适配
- 打印作为异步扩展点，不阻塞主交易流程
- 支持采购单、收货单、送货单、销售发票等模板切换

优先级说明：

- 打印集成优先级高于大多数体验优化项，但晚于核心交易链路打通
- 若后续扫码、移动作业和打印进入同一阶段，应统一按“移动作业端 + 固定模板打印”思路推进

## 16. 开发者备忘录

### 16.1 Bench 运维动作

- 修改 Python 模型或新增 DocType 字段后执行 `bench migrate`
- 接口逻辑更新后若结果与预期不一致，执行 `bench clear-cache`
- 定期巡检 `Error Log`

### 16.2 开发约束

- 新接口必须定义成功码和错误码
- 新接口必须补 Postman 示例
- 新业务规则优先写在 `services` 层
- 涉及状态流转的逻辑必须补边界测试

### 16.3 联调建议

- 优先使用 `v2` 分步集合调试
- 验证完整链路时使用 `v1`
- 联调时保留关键单号：`Sales Order`、`Delivery Note`、`Sales Invoice`、`Payment Entry`

## 17. 当前实现与需求对应关系

| 需求项 | 当前状态 | 说明 |
| --- | --- | --- |
| 快速下单 | 已实现 | 支持分步和联动模式 |
| 钱货两清 | 已实现 | `immediate=1` 可联动发货和开票 |
| 多维商品搜索 | 已实现 | 支持编码、名称、条码 |
| 库存看板 | 已实现 | 当前为总量视图 |
| 多单位预览 | 已实现 | 返回 `all_uoms` |
| 灵活收款 | 已实现 | 支持 Payment Entry 创建 |
| 退货处理 | 已实现 | 支持发票/发货单退货 |
| 异常回滚 | 依赖 Frappe 事务 | 已按请求事务设计 |
| 客户默认仓库 | 部分实现 | 当前支持传 `default_warehouse`，未自动从客户档案取值 |
| 单位换算交易规则 | 部分实现 | 当前可返回 `all_uoms` 且允许传 `uom`，但计价与换算口径仍需补强 |
| 客户信用控制 | 未实现 | 后续增强项 |
| 幂等控制 | 已实现 | `create_order`、`submit_delivery`、`create_sales_invoice`、`update_payment_status`、`process_sales_return` 已支持 `request_id` |
| 批次与保质期 | 未实现 | 后续增强项 |
| 自动打印 | 未实现 | 后续增强项 |

## 18. 结论

当前 `myapp` 已经形成副食批发场景下的第一版业务网关骨架，具备继续承载需求迭代的基础。后续开发应以本文档为基准推进，遵循以下原则：

- 先补齐结构化设计，再继续加功能
- 保持接口契约稳定
- 将业务复杂度收敛在服务层
- 用 Postman 版本化集合管理联调流程
- 对每个新增需求同时更新代码、测试、文档和联调样例

采购与进货相关能力已进入下一阶段实现范围，并已形成独立设计文档：

- `PURCHASE_TECH_DESIGN.zh-CN.md`

下一阶段建议优先顺序：

1. 移动作业端与打印方案设计落地
2. 单位换算交易规则补强
3. 批次与保质期管理
4. 客户信用控制
5. 打印设备适配与模板扩展
