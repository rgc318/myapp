# 开发交接摘要

更新时间：2026-03-11

## 1. 当前已完成

### 1.1 销售侧网关

已实现并可用：

- `create_order`
- `submit_delivery`
- `create_sales_invoice`
- `search_product`
- `confirm_pending_document`
- `update_payment_status`
- `process_sales_return`

其中以下接口已支持 `request_id` 幂等：

- `create_order`
- `submit_delivery`
- `create_sales_invoice`
- `update_payment_status`
- `process_sales_return`

### 1.2 采购侧网关

已实现并完成主链路联调：

- `create_purchase_order`
- `receive_purchase_order`
- `create_purchase_invoice`
- `record_supplier_payment`
- `process_purchase_return`

以上采购接口均已支持 `request_id` 幂等。

## 2. 本轮已验证结果

在 devcontainer / ERPNext 运行环境中，已通过 Postman `v3` 集合完成以下验证：

- 采购订单创建成功
- 采购收货成功
- 采购发票创建成功
- 供应商付款成功
- 采购退货成功

幂等验证结论：

- 相同 `request_id` 重试时，返回第一次成功结果
- 修改新的 `request_id` 后，会按新业务请求执行
- 若原业务已被消费，则会触发真实业务校验错误，例如：
  - 无可收货明细
  - 无可开票明细
  - 物料已被退回

## 3. 已新增或更新的重要文件

### 3.1 代码

- `myapp/services/purchase_service.py`
- `myapp/api/purchase_api.py`
- `myapp/api/gateway.py`
- `myapp/api/api.py`
- `myapp/api/__init__.py`
- `myapp/services/__init__.py`

### 3.2 测试

- `myapp/api/test_purchase_service.py`
- `myapp/api/test_gateway_wrappers.py`

### 3.3 文档

- `API_GATEWAY.zh-CN.md`
- `API_GATEWAY.md`
- `WHOLESALE_TECH_DESIGN.zh-CN.md`
- `PURCHASE_TECH_DESIGN.zh-CN.md`
- `README.zh-CN.md`
- `README.md`

### 3.4 Postman

- `postman/myapp-gateway-v3.postman_collection.json`
- `postman/myapp-local-v3.postman_environment.json`

## 4. 近期关键提交

- `e33ebca` `fix: pass idempotency keys through API wrappers`
- `1c98f39` `feat: add idempotency to fulfillment and return flows`
- `a19170a` `docs: update idempotency coverage`
- `c87ca81` `feat: add purchase gateway flow`
- `af01407` `docs: link purchase design from wholesale baseline`
- `bce2cff` `docs: refine frontend and printing strategy`

## 5. 当前前端与打印方向

已达成的设计结论：

- 前端优先面向管理员、内勤、仓管人员
- 移动端 / 平板端优先，重点承载扫码、收货、入库、发货、确认、打印预览
- 桌面 Web 端保留，用于查询、追踪、补打、较大单据打印
- ERPNext 后台继续负责主数据、财务底层、系统配置和复杂管理
- 当前不计划做完整替代 ERPNext 的独立管理后台

打印策略结论：

- 单据以半 A4 到 A4 这类较大格式为主，不是小票为主
- 模板预先固定，移动端只需要预览确认，不让用户手动调缩放和页面尺寸
- 第一阶段优先兼容主流品牌打印机，不追求全品牌全协议覆盖
- 打印设备连接方式后续按实际设备收敛，不先做无限兼容

## 6. 当前未完成但已明确的方向

### 6.1 销售与商品侧

- 单位换算交易规则补强
- 批次与保质期管理
- 商品搜索增强（分仓库存、最近成交价、专属价等）

### 6.2 采购侧

- 从 `Purchase Receipt` 直接生成采购发票的独立封装路径
- 采购部分收货 / 部分开票 / 部分退货的更完整测试
- 后续若进入质检、拒收、批次、效期场景，可能需要新增字段或 DocType

### 6.3 前端侧

- 需要确定移动端技术栈
- 需要确定打印机品牌 / 型号 / 连接方式范围
- 需要明确扫码方案与打印方案是系统打印、插件打印还是厂商能力

## 7. 下一步建议

如果继续后端：

1. 补 `Purchase Receipt -> Purchase Invoice` 的接口封装
2. 补采购边界场景测试
3. 开始批次 / 保质期规则设计

如果转前端：

1. 先确定移动端技术路线
2. 列出第一版页面清单
3. 明确打印机设备范围后再做打印能力接入
