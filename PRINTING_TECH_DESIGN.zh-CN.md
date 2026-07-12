# 打印模块技术设计

> 当前状态（2026-07-12）：本文前半部分保留最初的阶段设计背景；实际实现已经完成 7 类核心单据、单张/批量打印、审计、模板治理、ZIP、合并 PDF 和 Payment Entry。当前缺口以 16.9 节及 `docs/codex/PROJECT_GAP_ROADMAP.zh-CN.md` 为准。

## 1. 背景

当前移动端和业务流程已经逐步稳定，销售、采购、报表等核心模块已具备继续向“正式业务单据输出”推进的基础。下一阶段需要补上打印能力，用于：

- 正式单据预览
- 系统打印
- PDF 导出 / 分享
- 后续补打

现阶段仓库里已经形成一些一致结论：

- 打印以半 A4 到 A4 这类正式单据为主，不以热敏小票为主
- 模板应预先固定，移动端只负责预览确认，不让用户手动调版式
- 打印不应阻塞主交易流程
- 桌面 Web 端可继续承担补打与大单据打印

本设计文档用于把这些分散结论收敛成一套正式的打印模块方案。

## 2. 设计目标

第一阶段目标：

- 建立后端公共打印模块
- 建立前端统一打印入口与预览能力
- 优先打通正式业务单据打印链路
- 为后续 PDF、分享、补打和其他项目复用预留边界

第一阶段不做：

- 蓝牙热敏小票
- 标签打印
- 打印机厂商深度适配
- 离线本地复杂排版

## 3. 方案结论

总体策略：

- 后端负责打印上下文、模板选择、HTML / PDF 输出
- 前端负责发起预览、展示打印结果、触发系统打印或分享
- 正式单据版式不在移动端前端手工拼装

推荐技术路径：

- 后端优先复用 Frappe / ERPNext 现有打印体系与 Print Format 能力
- 若现有能力不足，再在 `myapp` 内补统一打印服务层
- 移动端使用 `expo-print` + `expo-sharing`
- 正式单据优先输出为 HTML 打印预览和 PDF 文件

原因：

- 版式稳定性更高
- 不同设备输出更一致
- 模板和权限更容易集中管理
- 以后扩展到其他项目时，复用的是打印引擎而不是页面逻辑

## 4. 模块边界

### 4.1 后端公共打印模块

建议目录：

- `/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/printing/`

建议子结构：

- `service.py`
  - 公共打印服务入口
- `registry.py`
  - 维护 `doctype -> 打印适配器 / 模板` 的映射
- `schemas.py`
  - 打印请求与响应结构
- `renderers/`
  - HTML / PDF 渲染器
- `contexts/`
  - 不同单据的打印上下文构建器
- `templates/`
  - 项目自定义模板或模板包装层

后端职责：

- 参数校验
- 权限校验
- 单据读取
- 打印上下文装配
- 模板解析 / 模板选择
- 生成 HTML / PDF
- 返回文件流、URL 或打印预览内容

### 4.2 前端公共打印模块

建议目录：

- `/home/rgc318/python-project/frappe_docker/frontend/myapp-mobile/services/printing.ts`
- `/home/rgc318/python-project/frappe_docker/frontend/myapp-mobile/app/print/`
- `/home/rgc318/python-project/frappe_docker/frontend/myapp-mobile/components/print/`

前端职责：

- 统一发起打印预览请求
- 统一承接 PDF / HTML 预览
- 统一打印、分享、补打入口
- 统一加载态、失败态、文件命名与用户提示

前端不负责：

- 正式版式拼装
- 单据口径计算
- 打印模板逻辑判断

## 5. 建议接口设计

建议新增网关能力：

- `myapp.api.gateway.get_print_preview_v1`
- `myapp.api.gateway.get_print_file_v1`

### 5.1 预览接口

用途：

- 返回可预览的 HTML 或预览元数据

建议入参：

- `doctype`
- `docname`
- `template`
- `output`
  - `html`
  - `pdf`

建议返回：

- `doctype`
- `docname`
- `template`
- `output`
- `title`
- `html`
- `file_url`
- `mime_type`

### 5.2 文件接口

用途：

- 直接生成可下载 / 可分享的 PDF

建议入参：

- `doctype`
- `docname`
- `template`
- `filename`

建议返回：

- `file_url`
- `filename`
- `mime_type`
- `expires_at`

当前实现补充：

- `get_print_file_v1` 现已默认只生成 PDF 元数据，不自动保存后端 `File`
- 普通预览、分享、下载优先走流式链路，避免把每次查看都沉淀成永久附件
- 仅在显式传 `archive=1` 时，后端才会把 PDF 归档为私有 `File`
- 归档目录统一为 `Home/Attachments/MyApp Print Files/Archive`
- 归档目录会在首次使用时自动创建，不需要提前手工建目录
- `download_print_file_v1` 继续只返回字节流，不负责后端落盘

联调验证：

- 真实站点单据验证已确认：
  - 默认 `stream` 模式不会新增后端 `File`
  - `archive=1` 会生成挂到业务单据上的私有 `File`
  - 归档文件会落到 `Home/Attachments/MyApp Print Files/Archive`

## 6. 打印数据流

建议链路：

1. 前端业务页点击 `打印预览`
2. 前端跳转统一预览页
3. 预览页调用后端打印预览接口
4. 后端按 `doctype + docname + template` 构建打印上下文
5. 后端渲染 HTML 或 PDF
6. 前端展示预览
7. 用户选择：
   - 系统打印
   - 分享 PDF
   - 下载 / 补打

## 7. 第一阶段单据范围

建议优先级：

### P0

- 销售发票
- 销售订单
- 销售发货单

原因：

- 这些单据与客户沟通、对账、交付最直接
- 当前移动端已经有发票预览骨架，适合作为第一条打印主链路

### P1

- 收款单
- 采购订单
- 采购收货单
- 采购发票
- 付款单

补充说明：

- `Purchase Invoice` 当前已接入与 `Sales Invoice` 相同的正式 PDF 打印链路
- 当前优先级定义里的 `P1` 保留其业务优先级含义，但不再表示“采购发票尚未具备打印能力”
- 之所以仍保留在 `P1`，是因为采购侧后续还会继续补：
  - 更完整的模板文案细化
  - 采购侧独有票据字段审校
  - 与付款链路联动的补打入口

## 8. 模板策略

模板策略建议：

- 优先复用 ERPNext / Frappe 既有 Print Format
- 如果标准模板不符合移动端 / 业务需求，再做 `myapp` 自定义模板
- 模板选择应由后端统一控制，不由前端自行拼字段和版式

模板层需要支持：

- 公司抬头
- 客户 / 供应商信息
- 单据头部摘要
- 商品明细表
- 金额汇总
- 备注
- 页眉页脚

### 8.1 当前已落地的 `Sales Invoice / standard`

当前已经不再直接依赖 ERPNext 默认的 `Standard` 打印版式，而是由 `myapp` 自行托管：

- 模板名：`myapp Sales Invoice Standard`
- 模板源码：
  - `/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/printing/templates/sales_invoice_standard.html`
- 模板名：`myapp Purchase Invoice Standard`
- 模板源码：
  - `/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/printing/templates/purchase_invoice_standard.html`
- 模板名：`myapp Delivery Note Standard`
- 模板源码：
  - `/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/printing/templates/delivery_note_standard.html`
- 模板名：`myapp Purchase Receipt Standard`
- 模板源码：
  - `/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/printing/templates/purchase_receipt_standard.html`
- 模板名：`myapp Sales Order Standard`
- 模板源码：
  - `/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/printing/templates/sales_order_standard.html`
- 模板名：`myapp Purchase Order Standard`
- 模板源码：
  - `/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/printing/templates/purchase_order_standard.html`

当前这套标准发票模板的版式原则是：

- 使用黑白正式单据风格，不使用彩色卡片和装饰性布局
- 页面上半部分只保留发票基础信息与购方基础信息
- 商品明细是唯一带表格边框的主体区域
- 发票金额区只保留：
  - `金额大写`
  - `发票金额`
- 销方信息放在页尾，不再与购方信息混排在顶部

当前字段来源约定：

- `销方信息`
  - 来自 `Company` 主数据
  - 目标是保证同一开票主体在不同发票中保持一致
- `购方信息`
  - 来自当前发票单据
  - 允许随客户与单据变化
- `备注`
  - 来自当前发票单据
  - 空值或常见英文默认值会统一规范成中文 `无备注`

当前商品表字段约定：

- `商品名称`
- `规格型号`
- `单位`
- `数量`
- `单价`
- `金额`

其中：

- 不再在正式发票上直接输出商品编码
- `规格型号` 在正式发票中必须作为独立列展示，不能退化成商品名称下方的附属说明
- 单位会做中文映射，如 `Nos -> 件`、`Box -> 箱`
- 金额大写会使用中文财务大写，而不是 ERPNext 默认的英文 `in_words`

当前规格字段取值约定：

- 商品主数据的规格字段来源是 `Item.custom_specification`
- 移动端销售/采购发票详情页与打印预览页都按独立 `规格` 列展示
- PDF / HTML 打印模板不能假设 `Sales Invoice Item` 或 `Purchase Invoice Item` 子表行天然带有 `custom_specification`
- 标准销售发票模板当前按以下顺序取规格：
  - `item.custom_specification`
  - `item.specification`
  - `frappe.db.get_value("Item", item.item_code, "custom_specification")`
  - 最终回退 `-`
- 标准采购发票模板也采用同一取值顺序

### 8.1.1 当前已落地的 `Delivery Note / standard`

当前销售发货单也已经切换为 `myapp` 托管标准模板：

- 模板名：`myapp Delivery Note Standard`
- 适用场景：
  - 仓库取货
  - 出货复核
  - 对外随货留档

当前版式原则：

- 整体按“仓库执行单据”设计，而不是按财务票据设计
- 客户信息与商品明细是页面重点，字号和字重均高于普通说明区
- 商品明细区中的：
  - `商品名称`
  - `规格型号`
  - `单位`
  - `数量`
  - `单价`
  - `金额`
  都会统一加粗加大，方便仓库快速扫读
- `金额大写` 已从发货单模板中移除
  - 原因是发货单的主要用途是拣货与复核，不是财务留档

当前商品名称展示约定：

- 若商品存在内部昵称，商品名称列展示为：
  - `（昵称）正式商品名`
- 若无昵称，则仅显示正式商品名
- `昵称` 不单独拆列
  - 原因是发货单表格列数已经较多，昵称更适合作为商品名称前缀辅助识别

当前规格字段取值约定：

- 发货单模板与发票模板保持一致，按以下顺序取规格：
  - `item.custom_specification`
  - `item.specification`
  - `frappe.db.get_value("Item", item.item_code, "custom_specification")`
  - 最终回退 `-`

### 8.1.2 当前已落地的 `Purchase Receipt / standard`

当前采购收货单也已经切换为 `myapp` 托管标准模板：

- 模板名：`myapp Purchase Receipt Standard`
- 适用场景：
  - 仓库收货
  - 到货复核
  - 采购留档

当前版式原则：

- 整体按“仓库收货执行单据”设计，而不是按财务票据设计
- 供应商信息与商品明细是页面重点，字号和字重均高于普通说明区
- 商品明细区中的：
  - `商品名称`
  - `规格型号`
  - `仓库`
  - `单位`
  - `数量`
  - `单价`
  - `金额`
  都会统一加粗加大，方便仓库快速扫读
- 模板只保留：
  - `收货金额`
  不再放 `金额大写`

当前商品名称展示约定：

- 若商品存在内部昵称，商品名称列展示为：
  - `（昵称）正式商品名`
- 若无昵称，则仅显示正式商品名
- `昵称` 不单独拆列

当前规格字段取值约定：

- 采购收货单模板与发票/发货单保持一致，按以下顺序取规格：
  - `item.custom_specification`
  - `item.specification`
  - `frappe.db.get_value("Item", item.item_code, "custom_specification")`
  - 最终回退 `-`

### 8.1.3 当前已落地的 `Sales Order / standard`

当前销售订单也已经切换为 `myapp` 托管标准模板：

- 模板名：`myapp Sales Order Standard`
- 适用场景：
  - 客户确认
  - 销售内部确认
  - 仓库备货依据

当前版式原则：

- 整体按“正式确认单据”设计，而不是按仓库执行单据或财务票据设计
- 客户信息、商品明细、订单金额是主要区域
- `规格型号` 在销售订单中继续作为独立列展示
- 正式销售订单不展示内部商品编码

当前商品名称展示约定：

- 若商品存在内部昵称，商品名称列展示为：
  - `（昵称）正式商品名`
- 若无昵称，则仅显示正式商品名
- `昵称` 作为商品识别辅助信息，放在商品名称列内，不单独拆列

当前规格字段取值约定：

- 销售订单模板按以下顺序取规格：
  - `item.custom_specification`
  - `item.specification`
  - `frappe.db.get_value("Item", item.item_code, "custom_specification")`
  - 最终回退 `-`

### 8.1.4 当前已落地的 `Purchase Order / standard`

当前采购订单也已经切换为 `myapp` 托管标准模板：

- 模板名：`myapp Purchase Order Standard`
- 适用场景：
  - 供应商确认
  - 采购内部确认
  - 仓库到货准备

当前版式原则：

- 整体按“正式确认单据”设计，而不是按仓库执行单据或财务票据设计
- 供应商信息、商品明细、订单金额是主要区域
- `规格型号` 在采购订单中继续作为独立列展示
- 正式采购订单不展示内部商品编码

当前商品名称展示约定：

- 若商品存在内部昵称，商品名称列展示为：
  - `（昵称）正式商品名`
- 若无昵称，则仅显示正式商品名
- `昵称` 作为商品识别辅助信息，放在商品名称列内，不单独拆列

当前规格字段取值约定：

- 采购订单模板按以下顺序取规格：
  - `item.custom_specification`
  - `item.specification`
  - `frappe.db.get_value("Item", item.item_code, "custom_specification")`
  - 最终回退 `-`

这样做的原因是：

- 销售发票行项目本身通常只保证 `item_code / item_name / qty / rate / amount` 等交易字段
- `规格` 属于商品主数据展示字段，不应依赖前端拼接后再传回打印模块
- 打印模板必须能够直接依据 `item_code` 回查商品主数据，才能保证正式 PDF 与移动端详情页展示一致

### 8.2 当前已知边界

当前模板链路已经可用，但仍有两类已知边界：

- 公司主数据不完整时，销方电话 / 地址可能为空
  - 这属于主数据质量问题，不是模板字段来源错误
- 多商品跨页规则已补齐，但仍建议使用超长单据再做一次真实分页验证
  - 当前模板已支持商品表跨页、表头重复、汇总区与销方信息尽量保持在最后一页

## 9. 权限与安全

打印模块必须遵守与业务详情页一致的权限规则。

至少要求：

- 只有能查看该单据的用户，才能打印该单据
- 打印 URL 不应成为可长期公开访问的静态文件入口
- 临时文件应有过期策略
- 文件命名不能泄露不必要的内部信息

## 10. 复用设计

该模块应按“公共打印引擎 + 项目适配层”设计。

可复用部分：

- 打印入口协议
- 模板解析与渲染流程
- 文件输出流程
- HTML / PDF 返回协议
- 权限与缓存策略

项目适配部分：

- 单据上下文构建
- 模板内容
- 业务字段组织

这意味着后续若要复用到其他项目，应复用打印框架与接口规范，而不是直接复用 `myapp` 的单据模板和字段映射。

## 11. 当前代码基础

当前前端已有可承接打印能力的基础：

- 销售发票页已有打印预览入口
- 销售发票预览页骨架已存在：
  - `/home/rgc318/python-project/frappe_docker/frontend/myapp-mobile/app/sales/invoice/preview.tsx`

当前状态仍属于“预览壳子已在，真实打印链路未接通”。

## 12. 第一阶段实施建议

建议按以下顺序推进：

1. 后端建立 `printing` 模块骨架
2. 打通 `Sales Invoice` 的打印预览接口
3. 前端预览页接真实 HTML / PDF 数据
4. 接入 `expo-print`
5. 接入 `expo-sharing`
6. 再扩展到 `Sales Order` / `Delivery Note`

## 13. 验收标准

第一阶段完成标准建议为：

- 销售发票可从移动端进入打印预览
- 预览内容与正式版式一致
- 可调起系统打印
- 可导出 / 分享 PDF
- 后端模板、权限、文件输出链路稳定
- 打印失败不影响原交易流程

## 14. 后续扩展

第二阶段再考虑：

- 补打列表
- 打印历史
- 多模板切换
- 小票 / 标签打印
- 设备适配能力
- 跨项目复用抽离

## 15. 当前第二阶段结论补充

在第一阶段打通 `Sales Invoice` 的真实 HTML / PDF 生成后，第二阶段前端预览能力已经有了更明确的取舍：

- 移动端正式文档预览不再继续依赖外部应用作为主路径
- `Sales Invoice` 现阶段采用“双页分工”：
  - 详情页负责业务核对
  - 正式 PDF 页负责正式预览、系统打印和分享
- Web 与原生端不强求使用同一套查看器壳子，而是各自复用更适合当前平台的能力

### 15.1 Web 端

- Web 端当前优先复用浏览器原生 PDF 查看器
- 这样可以直接获得浏览器已有的：
  - 缩放
  - 页码
  - 搜索
  - 打印
- 短期内不强制切到自建 Web PDF 工具栏
- 若后续需要更强控制能力，再评估引入 `pdf.js`

### 15.2 原生移动端

- 原生端当前采用 `react-native-pdf` 作为 App 内正式 PDF 查看器
- 这是 React Native 生态里较主流、也更符合当前项目阶段的方案
- 之所以选它，而不是继续走系统外部打开，是因为它能让：
  - 正式 PDF 留在 App 内查看
  - 打印/分享动作聚合在同一页

当前结论：

- `react-native-pdf` 适合作为当前阶段的正式移动端查看器
- 它不是浏览器级的完整文档阅读器，因此：
  - 缩放工具
  - 适宽
  - 重置
  - 缩放百分比
  这些交互需要由移动端页面自己补

### 15.3 交互边界

- 当 PDF 内容恰好完整贴合视口时，查看器通常不会给出可平移反馈
- 这是 PDF 查看器的自然行为，不完全是样式问题
- 当前项目采用的缓解方式是：
  - 默认进入略大于 `100%` 的阅读模式
  - 提供 `适宽`
  - 提供 `缩小 / 重置 / 放大`
- 如果后续仍需更强的自由拖动和文档交互控制，再评估更重的查看器方案

## 16. 通用打印平台升级设计

当前代码已经具备第一阶段基础：

- 后端已有统一入口：
  - `get_print_preview_v1`
  - `get_print_file_v1`
  - `download_print_file_v1`
- 后端已有打印 registry：
  - `myapp/printing/registry.py`
- 后端已有托管 Print Format 同步机制：
  - `myapp/printing/templates.py`
- 当前已接入：
  - `Sales Invoice`
  - `Purchase Invoice`
  - `Purchase Receipt`
  - `Sales Order`
  - `Purchase Order`
  - `Delivery Note`

下一阶段目标不是继续为每个页面单独拼打印，而是把现有能力升级为“通用打印平台”：

- 任意受支持单据都可以通过同一个打印入口打印
- 一个单据可以拥有多个模板
- 打印能力覆盖主流业务系统常见功能
- 后续新增单据时只做 registry / 模板 / 字段策略扩展，不新增一套页面级打印逻辑

### 16.1 总体原则

打印模块必须遵守以下原则：

- **通用入口**：所有单据统一调用 `doctype + docname + template + output`，不为每种单据新增专用打印 API。
- **显式白名单**：不是所有 Frappe DocType 默认可打印，必须在 registry 中登记后才能通过 myapp 打印入口访问。
- **多模板**：同一 DocType 支持多个模板，例如 `standard`、`compact`、`warehouse`、`finance`、`external`。
- **模板后端控制**：模板可选项、默认模板、禁用状态和适用场景由后端统一返回，前端不硬编码模板清单。
- **权限一致**：打印权限必须与单据详情读取权限一致，不能因为知道打印 URL 就绕过业务权限。
- **数据口径一致**：打印数据必须来自后端单据和共享领域能力，不能由前端临时计算金额、单位、状态或上下游关系。
- **正式输出优先**：A4 / 半 A4 正式 PDF 与 HTML 预览优先，小票、标签和设备厂商协议作为后续扩展。

### 16.2 通用单据接入模型

未来 registry 不应只保存 `doctype -> template list`，而应扩展为完整打印能力定义：

```python
PrintDocumentDefinition(
    doctype="Sales Invoice",
    label="销售发票",
    enabled=True,
    permission_ptype="read",
    title_field="name",
    party_field="customer",
    date_field="posting_date",
    amount_field="rounded_total",
    templates=(...),
    capabilities={...},
)
```

单据定义需要包含：

- `doctype`：Frappe / ERPNext 原生 DocType
- `label`：前端展示名
- `enabled`：是否启用打印
- `permission_ptype`：权限类型，默认 `read`
- `title_field`：文件名和标题默认字段
- `party_field`：客户 / 供应商 / 往来方字段
- `date_field`：打印日期或单据日期字段
- `amount_field`：金额摘要字段
- `status_field`：可选，用于在打印历史和补打列表中展示状态
- `templates`：该单据可用模板
- `capabilities`：该单据允许的输出和动作

模板定义需要包含：

```python
PrintTemplateDefinition(
    key="standard",
    label="标准模板",
    print_format="myapp Sales Invoice Standard",
    is_default=True,
    source="myapp",
    paper_size="A4",
    orientation="portrait",
    category="external",
    enabled=True,
)
```

模板字段建议：

- `key`：稳定模板编码，前端调用时传该值
- `label`：展示名
- `print_format`：Frappe Print Format 名称
- `is_default`：是否默认模板
- `source`：`myapp` / `erpnext` / `custom`
- `paper_size`：`A4` / `A5` / `half_a4` / `thermal_80mm` / `label`
- `orientation`：`portrait` / `landscape`
- `category`：`external` / `internal` / `warehouse` / `finance`
- `enabled`：模板是否启用
- `description`：模板说明

### 16.3 多模板策略

第一批模板分层建议：

#### 标准对外模板 `standard`

适用：

- 客户 / 供应商确认
- 对账
- 正式留档

特点：

- A4 或半 A4
- 正式抬头
- 明细完整
- 金额和备注清晰
- 不展示内部调试字段

#### 仓库执行模板 `warehouse`

适用：

- 拣货
- 发货
- 收货
- 复核

特点：

- 商品名称、规格、单位、数量加大
- 可展示仓库、货位、批号、条码
- 金额可选，默认弱化
- 支持大字号和少装饰

#### 财务模板 `finance`

适用：

- 发票留档
- 收付款凭证
- 内部审核

特点：

- 强调金额、已收 / 已付、未结、核销关系
- 展示关联发票、收付款单、退款单
- 可展示制单人、审核人、打印时间

#### 紧凑模板 `compact`

适用：

- 大批量补打
- 快速随货
- 节省纸张

特点：

- 更小页边距
- 更紧密表格
- 可隐藏低频字段
- 多页表头重复

#### 内部模板 `internal`

适用：

- 内部运营
- 排错
- 管理审核

特点：

- 可展示内部编码、商品编码、单据状态、上下游单据号
- 不作为对外模板默认项

模板命名约定：

- Print Format 名称：`myapp <DocType> <Template Label>`
- 模板 key 使用小写英文和下划线，例如：
  - `standard`
  - `warehouse`
  - `finance`
  - `compact`
  - `internal`

当前多模板阶段性落地：

- 7 类核心单据已从“单一标准模板”扩展为“标准模板 + 业务变体模板”：
  - `Sales Invoice`：`standard`、`finance`
  - `Purchase Invoice`：`standard`、`finance`
  - `Sales Order`：`standard`、`external`
  - `Purchase Order`：`standard`、`external`
  - `Delivery Note`：`standard`、`warehouse`
  - `Payment Entry`：`standard`、`finance`
  - `Purchase Receipt`：`standard`、`warehouse`
- 每个业务变体都已登记为独立托管 Print Format，例如 `myapp Sales Invoice Finance`、`myapp Delivery Note Warehouse`。
- 业务变体已经具备独立模板 key、分类、说明、版本号和 hash，可被 Web 通用打印入口选择，也会被打印历史记录。
- 业务变体继续共享稳定的基础模板结构，但已经通过模板 key 输出实际业务差异：财务版强化已收 / 已付、未结、核销与复核信息；仓库版增加拣货 / 收货 / 复核栏；外部确认版增加确认条款和签章栏。
- 模板角色可见性已在后端 registry 第一版落地：
  - `finance` 仅对 `Accounts Manager`、`Accounts User` 和 `System Manager` 可见。
  - 销售 `external` 对 `Sales Manager`、`Sales User` 和 `System Manager` 可见。
  - 采购 `external` 对 `Purchase Manager`、`Purchase User` 和 `System Manager` 可见。
  - `warehouse` 对 `Stock Manager`、`Stock User` 以及对应销售 / 采购业务角色可见。
  - `standard` 作为默认模板暂不限制角色。
- 前端只消费 `get_print_templates_v1` 返回的可见模板，不自行硬编码模板角色判断；后端 `resolve_print_template` 会再次校验，绕过前端传入不可见模板也会被拒绝。

#### 全局默认模板设置

当前已落地第一版后端打印设置表：

- 表名：`tabMyApp Print Setting`
- patch：`myapp.patches.create_print_setting_table`
- 唯一维度：`reference_doctype`

字段：

- `reference_doctype`：目标 DocType
- `default_template`：全局默认模板 key
- `enabled`：是否启用该默认设置
- `metadata_json`：预留扩展配置，当前可保存结构化 metadata

默认模板解析优先级：

1. 调用方显式传入 `template` 时，显式模板优先，并按 registry 和当前用户角色严格校验。
2. 未显式传入 `template` 时，优先读取启用状态的 `tabMyApp Print Setting.default_template`。
3. 如果配置的默认模板不存在、禁用或对当前用户不可见，则回退到 registry 中 `is_default=True` 的模板。

治理边界：

- 当前仅 `System Manager` 可以维护全局默认模板设置。
- 设置表缺失时，查询接口返回 `table_ready=false`，打印主流程自动回退 registry 默认模板，不阻断普通打印。
- 当前配置中心只覆盖默认模板；纸张、页边距、水印开关等仍由 registry / 模板版式控制，后续可沿用 `metadata_json` 扩展。

### 16.4 主流打印功能清单

打印模块最终应覆盖以下主流能力。

#### 预览与输出

- HTML 预览
- PDF 预览
- PDF 下载
- PDF 分享
- 浏览器系统打印
- 移动端系统打印
- 后端流式下载
- 可选归档到私有 `File`

#### 页面与版式

- 纸张大小：A4、A5、半 A4
- 方向：纵向、横向
- 页边距
- 页眉页脚
- 页码
- 打印时间
- 打印人
- 公司抬头
- 公司地址、电话、税号
- 签字栏 / 盖章栏
- 多页表头重复
- 汇总区尽量保持在末页
- 明细跨页不断裂或最小化断裂

#### 数据展示

- 商品名称
- 内部昵称
- 规格型号
- 单位展示名 `uom_display`
- 数量
- 单价
- 金额
- 税额 / 折扣 / 运费等扩展字段
- 金额大写
- 客户 / 供应商信息
- 联系人和地址
- 备注
- 关联单据

#### 条码与标识

- 单据号条码
- 单据二维码
- 商品条码
- 后续可扩展标签打印

#### 操作与治理

- 模板选择
- 默认模板
- 打印前预览
- 下载 PDF
- 归档 PDF
- 补打
- 打印历史
- 打印次数
- 最近打印时间
- 最近打印人
- 水印
- 作废 / 草稿状态标识
- 权限控制

### 16.5 后端接口升级

现有接口继续保留：

- `get_print_preview_v1`
- `get_print_file_v1`
- `download_print_file_v1`

已新增查询能力：

#### `list_print_doctypes_v1`

用途：

- 返回当前用户可打印的单据类型和能力。

返回：

- `doctype`
- `label`
- `templates`
- `capabilities`
- `default_template`

#### `get_print_templates_v1`

用途：

- 返回某个 `doctype` 可用模板。

入参：

- `doctype`

返回：

- `default_template`
- `templates[]`
- `capabilities`

当前模板元数据包含：

- `key`
- `label`
- `print_format`
- `is_default`
- `source`
- `category`
- `paper_size`
- `orientation`
- `description`
- `enabled`
- `managed`
- `template_version`
- `template_hash`
- `restricted`
- `allowed_roles`

说明：

- 当前只返回当前用户角色可见的模板。
- 模板可见性由后端 registry 控制；`System Manager` 可见所有模板。
- 默认模板会优先读取启用状态的 `tabMyApp Print Setting` 配置；配置模板对当前用户不可见时回退 registry 默认模板。

#### `get_print_settings_v1`

用途：

- 查询打印设置表中的全局默认模板配置。

返回：

- `settings[]`
- `table_ready`

`settings[]` 字段：

- `doctype`
- `default_template`
- `enabled`
- `metadata`
- `modified`
- `modified_by`

说明：

- 仅返回已写入设置表的配置项，不替代 `list_print_doctypes_v1` 的可打印 DocType 清单。
- 如果 `tabMyApp Print Setting` 尚未迁移创建，返回空列表和 `table_ready=false`。

#### `set_print_default_template_v1`

用途：

- 维护某个 DocType 的全局默认打印模板。

入参：

- `doctype`
- `template`
- `enabled`
- `metadata`

返回：

- `saved`
- `doctype`
- `default_template`
- `template`
- `enabled`

说明：

- 仅 `System Manager` 可调用。
- 会按 registry 校验目标模板存在、启用且对当前维护用户可见。
- 更新后，未显式传 `template` 的预览、PDF、下载和批量打印都会走该默认模板解析规则。
- 如果设置表尚未迁移创建，返回 `saved=false` 和 `reason=table_missing`。

#### `list_print_jobs_v1`

用途：

- 打印历史 / 补打列表。当前已实现基础版。

入参：

- `doctype`
- `docname`
- `date_from`
- `date_to`
- `user`
- `template`
- `action`
- `limit`

返回：

- `job_id`
- `doctype`
- `docname`
- `template`
- `action`
- `output`
- `filename`
- `file_url`
- `printed_by`
- `printed_at`
- `status`
- `metadata`

说明：

- 当前按目标单据查询，会先校验当前用户对该单据有读权限。
- 如果 `tabMyApp Print Job` 尚未迁移创建，返回空列表和 `table_ready=false`，不影响打印主流程。

#### `list_print_jobs_v2`

用途：

- 为 Web 打印中心提供跨单据、可分页的全局打印历史。

权限与兼容：

- 普通用户只查看本人产生的打印动作；`System Manager` 可以查看全部并按操作人筛选。
- 指定 `doctype + docname` 时仍校验目标单据读权限。
- `list_print_jobs_v1` 保留给详情页历史 Drawer，避免破坏现有 Web/Mobile 调用。

#### `create_print_batch_v1`

用途：

- 创建批量打印任务。当前已实现第一版。

入参：

- `documents[]`
  - `doctype`
  - `docname`
  - `template`
  - `filename`
- `output`: 当前仅支持 `pdf`
- `template`: 批次默认模板
- `run_async`: 是否进入 Frappe background job
- `metadata`

说明：

- 每批最多 100 张单据，避免同步请求或单个后台任务无限膨胀。
- 创建时校验模板 registry；实际 worker 逐单执行时继续沿用单据读取权限、模板同步、PDF 归档和文件命名规则。
- 默认异步入队；开发和测试可以传 `run_async=0` 直接同步处理。
- 成功结果返回每张单据归档后的私有 `file_url`，支持通过 `download_print_batch_archive_v1` 打包 ZIP，也支持通过 `download_print_batch_merged_pdf_v1` 按结果顺序合并 PDF。
- `request_id` 通过 `(requested_by, request_id)` 唯一约束提供严格幂等，重复请求返回原批次。
- Worker 对每张单据显式记录 `record_print_job_v1(action="archive")`，metadata 包含 `batch_id` 和 `batch_idx`。
- 如果 `tabMyApp Print Batch` 尚未迁移创建，返回 `queued=false` 和 `reason=table_missing`，不影响普通单据打印。
- 批次清理已接入 `myapp.tasks.cleanup_print_batches`，默认每小时清理 90 天以前最终态批次和其成功项归档 PDF，逐单 `MyApp Print Job` 审计记录保留。

#### `get_print_batch_v1`

用途：

- 查询批量打印任务进度、成功文件和失败原因。当前已实现第一版。

返回：

- `batch_id`
- `status`: `queued` / `processing` / `cancel_requested` / `canceled` / `completed` / `partial_failed` / `failed`
- `requested_by`
- `requested_at`
- `started_at`
- `completed_at`
- `enqueue_job_id`
- `total_count`
- `done_count`
- `success_count`
- `failed_count`
- `skipped_count`
- `progress`
- `items[]`
- `results[]`
- `metadata`

说明：

- 批次详情、取消、失败重试和 ZIP 下载只允许批次申请人或 `System Manager` 访问。

#### `list_print_batches_v1`

用途：

- 为 Web 打印中心提供可恢复的批次任务分页列表。

说明：

- 普通用户只返回本人创建的批次。
- `System Manager` 可以查看全部批次并按申请人筛选。
- 列表返回状态、进度、成功 / 失败 / 跳过计数、涉及单据类型和前 5 个单据号摘要。
- 逐单完整结果继续通过 `get_print_batch_v1` 按需加载，避免列表查询搬运大段 JSON。

#### `cancel_print_batch_v1`

用途：

- 取消批量打印任务。当前已实现第一版。

入参：

- `batch_id`

说明：

- `queued` 批次会直接进入 `canceled`，所有未处理单据记为 `skipped`。
- `processing` 批次会先进入 `cancel_requested`，Worker 在当前单据完成后跳过后续单据并最终进入 `canceled`。
- 已完成、部分失败、失败或已取消批次不做回滚。
- 取消不会删除已经归档的 PDF，也不会删除已写入的 `MyApp Print Job` 审计记录。

#### `retry_print_batch_failed_v1`

用途：

- 对批量打印失败项创建重试批次。当前已实现第一版。

入参：

- `batch_id`
- `run_async`
- `metadata`

说明：

- 只选择原批次 `results[]` 中 `status=failed` 的单据。
- 重试会创建新批次，不覆盖原批次结果，保证失败原因和历史审计可追溯。
- 新批次 metadata 会写入 `retry_of=<原批次号>`。
- 原批次没有失败项时返回业务校验错误。

#### `download_print_batch_archive_v1`

用途：

- 下载批次中所有成功 PDF 的 ZIP 包。当前已实现第一版。

入参：

- `batch_id`
- `filename`

说明：

- 只打包 `results[]` 中 `status=success` 且存在 `file_url` 的文件。
- 失败项不会阻断下载，失败原因仍通过 `get_print_batch_v1` 查看。
- ZIP 内文件名来自逐单结果 `filename`，重名自动追加序号。
- 文件读取优先使用 Frappe `File.get_content()`，从而复用站点本地文件或对象存储实现；本地路径读取保留为兼容兜底。

#### `record_print_job_v1`

用途：

- 前端实际触发系统打印、下载或分享后记录行为。当前已实现基础版。

入参：

- `doctype`
- `docname`
- `template`
- `action`: `preview` / `print` / `download` / `share` / `archive`
- `output`: `html` / `pdf`
- `status`: `success` / `failed` / `skipped`
- `filename`
- `file_url`
- `error`
- `metadata`

说明：

- 当前设计为显式记录，不由旧的预览 / 元数据 / 下载接口自动写入，避免改变 Web/Mobile 原有调用副作用。
- 调用时会校验单据存在、读权限、模板白名单和模板启用状态。
- 如果 `tabMyApp Print Job` 尚未迁移创建，返回 `recorded=false`，不阻断前端打印流程。
- 托管模板会自动把 `template_version`、`template_hash`、`template_managed` 和 `print_format` 固化到打印记录 `metadata`，用于审计追溯。
- `preview` 会保留在完整审计历史中，但不计入模板上的“打印副本次数”，因此单纯查看预览不会导致下一次显示“补打”。
- 当前计入打印副本次数的成功动作是 `download`、`print`、`share` 和 `archive`；Web 的 `print` 表示浏览器打印对话框已触发，无法承诺用户最终没有取消。

### 16.6 数据模型建议

如果要达到“主流打印功能级别”，建议新增轻量级治理 DocType。

#### `MyApp Print Template`

用于管理模板元数据，而不是替代 Frappe `Print Format`。

字段建议：

- `doctype`
- `template_key`
- `template_label`
- `print_format`
- `source`
- `paper_size`
- `orientation`
- `category`
- `is_default`
- `enabled`
- `description`
- `version`

第一阶段可以继续使用 Python registry；进入运营配置阶段后，再迁移到 DocType 管理。

#### `MyApp Print Job`

用于记录打印行为。

字段建议：

- `doctype`
- `docname`
- `template_key`
- `print_format`
- `output`
- `action`
- `file_url`
- `file_size`
- `printed_by`
- `printed_at`
- `client`
- `status`
- `error`

打印历史不是交易账本，不应影响原业务单据提交、作废和回退。

#### `MyApp Print Batch`

用于记录批量异步打印任务。

当前已由 patch `myapp.patches.create_print_batch_table` 创建物理表：

- 表名：`tabMyApp Print Batch`

核心字段：

- `status`
- `output`
- `requested_by`
- `requested_at`
- `started_at`
- `completed_at`
- `enqueue_job_id`
- `total_count`
- `success_count`
- `failed_count`
- `skipped_count`
- `items_json`
- `results_json`
- `metadata_json`
- `error`

当前边界：

- 批次表保存任务级状态，逐单打印审计仍写入 `tabMyApp Print Job`。
- 批次采用逐单归档 PDF，支持严格幂等、取消、失败项重试、ZIP 下载、合并 PDF，并已接入 90 天最终态批次 / 归档文件清理。

#### 批次清理任务

任务：

- `myapp.tasks.cleanup_print_batches`

默认策略：

- 每小时执行。
- 清理 90 天以前的最终态批次：
  - `completed`
  - `partial_failed`
  - `failed`
  - `canceled`
- 默认删除批次成功项对应的归档 PDF `File`。
- 删除 `tabMyApp Print Batch` 批次记录。
- 保留 `tabMyApp Print Job` 逐单审计记录。

当前边界：

- 不清理 `queued`、`processing`、`cancel_requested` 批次。
- 文件删除通过 Frappe `File` 文档生命周期执行，读取通过 `File.get_content()`；具体本地或对象存储行为由站点 File 存储实现负责。

### 16.7 前端通用打印入口

Web 和 Mobile 都不应在业务页里拼打印 URL。

前端应封装统一服务：

- `getPrintPreview`
- `getPrintFile`
- `downloadPrintFile`
- `getPrintTemplates`
- `recordPrintAction`

业务页只传：

- `doctype`
- `docname`
- 可选 `template`

前端通用组件建议：

- `PrintButton`
- `PrintTemplateSelect`
- `PrintPreviewDrawer` / `PrintPreviewPage`
- `PrintActionMenu`
- `PrintHistoryPanel`

页面接入方式：

- 详情页主操作区统一放 `打印` 按钮
- 下拉菜单展示可选模板
- 默认模板可一键预览
- `下载 PDF` 和 `系统打印` 进入统一流程

### 16.8 任意单据接入流程

新增单据打印时，必须按以下流程：

1. 确认该 DocType 是否允许打印。
2. 在 registry 或 `MyApp Print Template` 中登记 DocType。
3. 配置至少一个默认模板。
4. 如需正式业务模板，在 `myapp/printing/templates/` 增加托管模板。
5. 如模板需要派生字段，在后端打印上下文中统一补齐。
6. 补充单元测试：
   - 模板解析
   - 权限校验
   - HTML 预览
   - PDF 文件元数据
7. 前端业务页只接统一打印组件，不新增页面级打印拼装逻辑。

### 16.9 当前完成基线与后续路线

截至 2026-07-11，原阶段 A、阶段 B 的核心单据范围，以及阶段 C 的主要后端治理能力已经完成：

- registry 已支持模板元数据、capabilities、模板版本 / hash 和角色可见性。
- `get_print_templates_v1`、`list_print_doctypes_v1` 已作为模板发现接口落地。
- Web 端 7 类单据详情页已统一使用通用打印组件，模板清单由后端动态返回。
- 7 类核心单据均具备标准模板和第二业务模板：发票和收付款凭证 `finance`、订单 `external`、发货 / 收货 `warehouse`。
- 打印历史、打印归档、补打标识、水印、最近打印摘要和显式打印动作审计已落地。
- 批量打印已支持异步处理、进度查询、ZIP 下载、取消、失败项重试和过期清理。
- 全局默认模板设置和第一版模板角色权限已落地。

当前后端功能完成度按核心打印平台口径已接近完整：单张、批量、幂等、审计、设置、权限、ZIP、合并 PDF、收付款凭证和文件存储抽象均已落地。

后续建议按以下顺序推进：

1. 根据真实纸张样张继续微调各业务模板的分页和字号。
2. 把模板角色、纸张、页边距和水印策略进一步扩展为可运营维护的设置能力。
3. 上线前执行真实浏览器、后台队列、角色权限、ZIP / 合并 PDF 和 scheduler 清理冒烟验证。

### 16.10 当前可交付范围

当前可交付范围包括：

- `Sales Invoice`
- `Purchase Invoice`
- `Sales Order`
- `Purchase Order`
- `Delivery Note`
- `Purchase Receipt`
- `Payment Entry`

这些单据均支持：

- HTML / PDF 预览
- PDF 流式下载和可选私有归档
- 后端单据读取权限校验
- 后端模板白名单和角色可见性校验
- 模板动态查询和全局默认模板解析
- 打印历史和显式动作审计
- 异步批量归档、进度查询、ZIP 下载、取消、失败项重试和 90 天清理

发布时必须执行 `bench --site <site> migrate`，以创建或更新打印批次表和打印设置表。普通单张打印在相关治理表尚未创建时会尽量降级运行，但批量打印、设置维护和完整审计能力依赖迁移完成。
