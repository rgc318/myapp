# 扫码识别与条码多源解析技术设计

## 1. 背景

当前项目已经具备以下基础能力：

- 商品主数据管理
- 条码字段维护
- 商品搜索与详情
- 销售 / 采购选品与下单
- 正式业务单据打印

下一阶段希望补上扫码能力，用于：

- 通过扫码快速搜索已存在商品
- 在销售 / 采购业务页中快速加商品
- 在未命中本地商品库时，尝试通过外部条码信息源补全候选商品信息
- 由用户确认 / 编辑后快速新建商品

本设计文档用于收敛一套适用于正式环境的扫码识别与条码多源解析方案。

## 2. 设计目标

第一阶段目标：

- 支持移动端应用内扫码
- 支持条形码与二维码识别
- 支持本地商品库优先匹配
- 支持未命中时调用外部条码信息源
- 支持把外部候选信息映射为新商品预填数据
- 支持用户确认 / 编辑后创建新商品

第一阶段不做：

- 高速连续扫码盘点
- 蓝牙扫码枪 / 厂商 SDK 集成
- 离线条码商品数据库
- 自动无确认建商品
- 复杂 OCR 包装识别

## 3. 关键结论

总体策略：

- 前端负责扫码、展示和分流
- 后端负责查本地、调外部、做结果标准化
- 本地商品库始终优先于外部源
- 外部结果只能作为候选信息，不直接自动入库

正式环境推荐链路：

1. 前端扫码拿到条码值
2. 前端调用后端统一解析接口
3. 后端先查本地商品库
4. 本地未命中时，后端先判断是否允许联网搜索商品
5. 若允许联网搜索，则按配置依次调用多个外部 provider
6. 若不允许联网搜索，则直接返回“本地未命中”的结果
7. 后端返回统一结构给前端
8. 前端根据返回结果分流：
   - 已有商品：直接展示或加入订单
   - 外部候选：进入新建商品并预填
   - 无结果：只带条码进入新建商品

### 3.1 联网搜索开关

建议增加统一后端开关：

- `allow_external_lookup`

用途：

- 控制本地未命中时是否允许联网查询外部商品信息

建议规则：

- 默认关闭
- 由后端统一控制
- 可按环境、租户、角色或系统设置灰度开启

建议环境策略：

- 开发环境：
  - 默认关闭
- 测试环境：
  - 默认关闭或仅管理员开启
- 生产环境：
  - 初始关闭
  - 稳定后逐步灰度开启

前端不应自行决定是否联网查询，而应只消费后端统一返回结果。

### 3.2 两种工作模式

#### 本地-only 模式

流程：

1. 扫码
2. 查本地商品
3. 命中则直接使用
4. 未命中则只带条码进入新建商品

适用场景：

- 第一阶段快速落地
- 尚未接入外部 provider
- 需要严格控制成本
- 需要降低外部依赖风险

#### 本地 + 外部补全模式

流程：

1. 扫码
2. 查本地商品
3. 本地未命中时调用外部 provider
4. 命中候选信息后进入新建商品并预填
5. 用户确认后保存

适用场景：

- 已接入稳定条码信息服务
- 命中率和数据质量已通过验证
- 成本、限流与缓存策略已准备好
- 需要提升建档效率

## 4. 业务原则

### 4.1 扫码的第一目标是“查已有商品”

扫码一期的核心目标不是自动建商品，而是：

- 快速找到系统中已存在的商品
- 避免用户忘记商品名称或在同类商品中选错
- 在销售 / 采购中更快加商品

因此扫码入口应优先放在：

- 商品搜索页
- 销售选品页
- 采购选品页

### 4.2 条码本身不是完整商品信息

普通商品条形码通常只包含：

- 一串数字或字符串
- 条码类型

扫码后不能天然得到完整商品对象。完整商品信息只能来自：

- 本地商品库映射
- 外部条码信息服务
- 或用户手动补录

### 4.3 外部候选信息必须允许人工确认

外部商品条码数据可能存在：

- 名称不规范
- 规格不完整
- 品牌缺失
- 数据语言不统一
- 旧包装 / 旧名称

因此正式环境中必须保留用户确认与编辑步骤，不允许外部结果直接自动建档。

## 5. 架构方案

### 5.1 总体架构

推荐采用：

- 策略模式
- 注册表 / 简单工厂
- 按顺序回退的多 provider 解析链

结构分层：

- 前端扫码与业务分流层
- 后端统一解析服务层
- 本地商品 provider
- 外部条码 provider 集合
- 标准化结果模型

### 5.2 推荐目录

后端建议目录：

- `/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/services/barcode_resolver_service.py`
- `/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/integrations/barcode/types.py`
- `/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/integrations/barcode/registry.py`
- `/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/integrations/barcode/providers/base.py`
- `/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/integrations/barcode/providers/local_item.py`
- `/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/integrations/barcode/providers/gs1_china.py`
- `/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/integrations/barcode/providers/go_upc.py`
- `/home/rgc318/python-project/frappe_docker/apps/myapp/myapp/integrations/barcode/providers/upcitemdb.py`

前端建议目录：

- `/home/rgc318/python-project/frappe_docker/frontend/myapp-mobile/components/barcode/`
- `/home/rgc318/python-project/frappe_docker/frontend/myapp-mobile/services/barcode.ts`
- `/home/rgc318/python-project/frappe_docker/frontend/myapp-mobile/app/common/barcode-scan.tsx`

## 6. 设计模式说明

### 6.1 为什么使用策略模式

不同外部源的差异主要体现在：

- 认证方式
- API 地址
- 返回字段结构
- 数据完整度
- 错误码

因此每个 provider 应实现统一接口，例如：

```python
class BarcodeProvider(Protocol):
    provider_name: str

    def lookup(self, barcode: str) -> BarcodeLookupResult | None:
        ...
```

这样可以做到：

- provider 可替换
- provider 可按配置启停
- provider 可调整顺序
- 前端与业务层不感知具体来源

### 6.2 为什么使用注册表 / 简单工厂

正式环境通常需要：

- 开发环境只开本地 provider
- 测试环境接 1 个外部源
- 生产环境接 2 到 3 个外部源

因此建议由注册表按配置创建 provider 列表，而不是在业务代码里写死：

```python
enabled = ["local", "gs1_china", "go_upc"]
providers = build_providers(enabled)
```

这里不需要上复杂的抽象工厂，简单工厂或注册表即可满足需求。

## 7. 统一结果模型

建议定义统一类型：

```python
from dataclasses import dataclass


@dataclass
class BarcodeLookupCandidate:
    barcode: str
    item_name: str | None = None
    brand: str | None = None
    specification: str | None = None
    image_url: str | None = None
    source: str = "unknown"
    confidence: float | None = None
    raw_payload: dict | None = None


@dataclass
class BarcodeLookupResult:
    matched: bool
    source: str
    match_type: str
    barcode: str
    local_item: dict | None = None
    candidate: BarcodeLookupCandidate | None = None
```

建议 `match_type` 取值：

- `local_item`
- `external_candidate`
- `none`

## 8. Provider 顺序建议

正式环境推荐优先级：

1. `LocalItemProvider`
2. 国内条码 provider
3. 国际条码 provider
4. 垂直行业 provider

推荐顺序示例：

- `local`
- `gs1_china`
- `cn_aggregator`
- `go_upc`
- `open_food_facts`

原因：

- 本地命中最可靠
- 中国大陆商品优先查国内源
- 进口商品再查国际源
- 食品类可用垂直源补充

## 9. 本地商品 Provider 设计

本地 provider 也应作为统一 provider 体系中的第一项，而不是单独旁路逻辑。

本地匹配建议顺序：

1. `Item Barcode.barcode`
2. 商品主条码字段
3. 必要时二维码中提取出的 `item_code`

命中后返回：

- `matched = True`
- `source = local`
- `match_type = local_item`
- 完整商品对象

本地商品对象建议至少包含：

- `item_code`
- `item_name`
- `nickname`
- `specification`
- `brand`
- `barcode`
- `stock_uom`
- `image_url`
- 当前价格与库存摘要

## 10. 外部 Provider 设计

### 10.1 接入原则

- 前端不直连第三方
- 所有外部源只允许后端访问
- 后端统一做：
  - key 管理
  - 超时控制
  - 限流
  - 结果清洗
  - 日志

### 10.2 建议候选来源

适合中国大陆业务的一般建议：

- 国内官方 / 半官方商品条码体系
- 国内第三方条码聚合服务
- 国际商品条码服务
- 食品垂直公开数据库

正式环境建议至少准备 2 个外部 provider，以避免单源不可用带来整条链路中断。

### 10.3 外部结果标准化

不同外部源返回格式不同，应统一映射为：

- `item_name`
- `brand`
- `specification`
- `barcode`
- `image_url`
- `source`
- `confidence`

昵称 `nickname` 不建议自动生成，由用户确认后手动填写更稳。

## 11. 建议接口设计

建议新增统一网关能力：

- `myapp.api.gateway.resolve_barcode_v1`

### 11.1 入参

- `barcode: str`
- `context: str | None`
  - `product`
  - `sales_order`
  - `purchase_order`
- `allow_external: bool = True`

### 11.2 返回结构

```json
{
  "matched": true,
  "source": "local",
  "match_type": "local_item",
  "barcode": "6901234567890",
  "local_item": {
    "item_code": "COLA-500ML",
    "item_name": "可口可乐 500ml",
    "nickname": "可乐小瓶",
    "specification": "500ml",
    "brand": "可口可乐",
    "barcode": "6901234567890"
  },
  "candidate": null
}
```

或：

```json
{
  "matched": true,
  "source": "go_upc",
  "match_type": "external_candidate",
  "barcode": "6901234567890",
  "local_item": null,
  "candidate": {
    "item_name": "可口可乐",
    "brand": "可口可乐",
    "specification": "500ml",
    "barcode": "6901234567890",
    "image_url": "https://..."
  }
}
```

或：

```json
{
  "matched": false,
  "source": "none",
  "match_type": "none",
  "barcode": "6901234567890",
  "local_item": null,
  "candidate": null
}
```

## 12. 前端交互设计

### 12.1 扫码入口

第一阶段建议接入位置：

- 商品搜索页
- 销售选品页
- 采购选品页
- 商品创建页条码输入旁

### 12.2 分流规则

扫码后前端统一按返回结果分流：

#### 本地命中

- 商品管理页：
  - 直接跳商品详情
- 销售 / 采购选品页：
  - 直接加入订单或进入商品确认卡

#### 外部候选命中

- 进入新建商品页
- 自动带入：
  - `barcode`
  - `item_name`
  - `brand`
  - `specification`
  - `image_url`

#### 全未命中

- 进入新建商品页
- 只自动带入 `barcode`

### 12.3 为什么不直接自动建商品

因为正式环境中需要避免：

- 重复建档
- 错误名称
- 错误规格
- 错误品牌
- 脏数据污染

## 13. 移动端扫描能力建议

对于当前 Expo / React Native 技术栈，第一阶段建议使用：

- `expo-camera`

原因：

- 官方支持
- 支持常见条形码与二维码
- 接入复杂度低
- 足够支撑“业务扫码识别商品”场景

第一阶段关注的是：

- 单次扫码识别
- 快速商品匹配
- 业务页分流

第一阶段不追求：

- 高速连续扫码
- 工业级盘点场景
- 原生扫码枪性能级体验

## 14. 数据映射规则

建议统一映射为现有商品字段：

- 外部 `barcode` -> 本地 `barcode`
- 外部 `name` / `title` -> 本地 `item_name`
- 外部 `brand` -> 本地 `brand`
- 外部 `size` / `spec` / `package` -> 本地 `custom_specification`
- 外部 `image` -> 本地 `image_url`

以下字段不建议自动推断：

- `nickname`
- `stock_uom`
- `wholesaleDefaultUom`
- `retailDefaultUom`
- 价格

这些字段应保留给用户人工确认。

## 15. 生产环境能力要求

### 15.1 超时与降级

每个外部 provider 应设置独立超时，例如：

- 800ms 到 1500ms

超时后应继续尝试下一个 provider，而不是直接整个请求失败。

### 15.2 缓存

建议缓存维度：

- `barcode -> 解析结果`

缓存策略建议：

- 本地命中：短缓存
- 外部候选命中：中等缓存
- 未命中：短时负缓存

这样可以避免同一条码被连续扫描时反复打外部接口。

### 15.3 限流

外部接口应增加：

- 单条码请求节流
- 用户级限流
- 全局 provider 调用速率限制

### 15.4 审计与日志

建议记录：

- 扫码条码值
- 命中来源
- provider 耗时
- 是否命中本地
- 是否命中外部
- 用户最终是否创建商品

这些日志可用于：

- provider 质量评估
- 费用评估
- 错误排查

### 15.5 配置管理

建议环境变量：

- `MYAPP_BARCODE_PROVIDERS=local,gs1_china,go_upc`
- `MYAPP_BARCODE_ALLOW_EXTERNAL=true`
- `MYAPP_BARCODE_PROVIDER_TIMEOUT_MS=1200`
- `MYAPP_BARCODE_CACHE_TTL_SECONDS=86400`
- 各 provider 的 API key / secret

## 16. 安全要求

- 前端不暴露第三方 API key
- 第三方 key 只允许后端读取
- 对外部返回做字段白名单过滤
- 不直接信任第三方图片 URL
- 必要时对图片地址做代理或下载转存

## 17. 权限与开关策略

正式环境建议把扫码能力与商品建档能力分开控制，不默认对所有用户开放同等权限。

建议至少区分以下权限：

- `barcode_scan_use`
  - 允许进入扫码能力
- `barcode_scan_create_product`
  - 允许在扫码未命中后进入新建商品流程
- `barcode_scan_external_lookup`
  - 允许在开启联网模式时触发外部候选查询
- `barcode_scan_manage_settings`
  - 允许管理联网搜索总开关与 provider 配置

推荐规则：

- 普通销售 / 采购用户
  - 默认可扫码查本地商品
  - 不一定允许直接新建商品
- 商品主数据管理员
  - 允许扫码后新建商品
  - 允许确认外部候选信息
- 系统管理员
  - 允许管理联网搜索开关与 provider 配置

这样可以避免：

- 一线业务人员误建商品
- 未经过主数据校验的大量候选信息直接入库
- 外部查询费用失控

## 18. 重复商品与建档防护

正式环境中，扫码建档的最大风险不是查不到，而是重复建档。

建议强制规则：

- 条码必须全局唯一
- 新建商品前必须再次校验条码唯一
- 如果条码已存在，优先回已有商品，不允许继续新建

建议辅助规则：

- 在新建商品前，按以下维度做近似提示：
  - `item_name`
  - `brand`
  - `specification`
- 若发现高度相似商品，可前端提示：
  - `系统中可能已存在相似商品，请先核对。`

但第一阶段不建议：

- 仅凭名称相似就强制拦截建档

因为这可能误伤：

- 同品牌不同规格
- 同系列不同包装
- 同名但不同业务属性的 SKU

推荐最终规则：

- `barcode` 唯一约束为强拦截
- 名称 / 品牌 / 规格近似仅做提示，不做强拦截

## 19. 错误与兜底策略

### 17.1 常见失败场景

- 摄像头权限拒绝
- 条码无法识别
- 本地未命中
- 外部 provider 超时
- 外部 provider 无数据
- 外部 provider 数据结构异常

### 17.2 推荐用户提示

- 本地未命中但外部命中：
  - `已找到候选商品信息，请确认后保存。`
- 本地与外部都未命中：
  - `未找到商品信息，已为你带入条码，可手动新建商品。`
- 外部查询失败：
  - `未能从外部商品库获取信息，可继续手动新建商品。`

## 20. 缓存、限流与审计

### 20.1 缓存策略

建议缓存键：

- `barcode + provider + mode`

建议策略：

- 本地命中：
  - 短缓存
- 外部候选命中：
  - 中等缓存
- 外部未命中：
  - 负缓存，但时间应短

建议原因：

- 避免连续扫描同一商品时重复打外部接口
- 降低外部 provider 成本
- 提高移动端响应速度

### 20.2 限流策略

建议至少做三层限流：

- 用户级限流
- 设备级限流
- provider 全局调用速率限制

建议目标：

- 防止恶意或误操作造成高频外部请求
- 防止第三方接口额度被短时间耗尽

### 20.3 审计日志

建议记录：

- 用户 ID
- 设备标识
- 扫码时间
- 条码值
- 命中来源
- provider 名称
- 是否命中本地
- 是否进入建商品流程
- 是否最终保存商品

建议用途：

- 安全审计
- 成本分析
- provider 命中率评估
- 问题追踪

## 21. 测试与验收补充

建议把扫码模块测试拆成四层：

### 21.1 单元测试

- provider 注册表
- 本地 provider 匹配
- 外部 provider 结果标准化
- `allow_external_lookup` 开关行为
- 条码唯一校验

### 21.2 HTTP / 接口测试

- 本地命中
- 本地未命中且关闭联网搜索
- 本地未命中且开启联网搜索
- 外部 provider 超时降级
- 外部 provider 返回异常结构

### 21.3 前端交互测试

- 扫码后跳商品详情
- 扫码后加入销售单
- 扫码后加入采购单
- 未命中后进入新建商品页
- 外部候选预填商品页

### 21.4 真机验收

- Android 真机扫码权限
- iOS 真机扫码权限
- 明亮 / 昏暗环境识别
- 常见条形码与二维码识别
- 网络不稳定时的兜底体验

## 22. 验收标准

第一阶段至少需要覆盖：

- 扫码命中本地商品
- 扫码未命中本地、命中外部候选
- 扫码两边都未命中
- 销售选品页扫码加商品
- 采购选品页扫码加商品
- 商品搜索页扫码跳详情
- 商品创建页自动带入条码
- 外部 provider 超时降级
- 外部 provider 返回脏数据时仍可正常兜底

除以上功能性验收外，还应补充通过：

- 权限开关验收
- 重复建档防护验收
- 外部开关关闭时的本地-only 验收
- 日志记录与追踪验收

## 23. 分阶段实施建议

### 第一阶段

- 只做：
  - 扫码
  - 本地商品匹配
  - 未命中时带条码新建商品

### 第二阶段

- 接入第一个外部 provider
- 支持候选商品信息预填

### 第三阶段

- 配置多个 provider
- 加缓存、限流、日志
- 做命中率统计与 provider 策略优化

## 24. 方案结论

正式环境推荐方案如下：

- 扫码能力使用移动端应用内相机方案
- 前端只负责扫码与交互分流
- 后端负责条码统一解析
- 本地商品库优先
- 外部条码服务作为候选信息补充
- 使用“策略模式 + 注册表 / 简单工厂”实现多 provider 架构
- 外部结果必须经过统一标准化
- 用户必须能够确认 / 编辑后再建商品

这一方案可以同时满足：

- 一期快速落地
- 后续多源扩展
- 正式环境安全与可维护性
- 与现有商品、销售、采购链路平滑集成
