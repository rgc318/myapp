# AI Copilot 模块技术设计

> 状态：Phase A 只读纵向链路、Phase B 三类结构化草稿、商品语义检索、模型治理控制面、高并发 P0、OTLP 可观测性、备份恢复演练和首期商品数据治理任务均已实现。2026-07-15 已从在线 `myapp-products-live → myapp-products-v1` 清理 439 个明确 `HTTP-` 测试 points，保留 143 个非排除商品向量 / 1024 维；582 个 ERP Item 和 854 个 Sales Order 未修改。`erp-embedding` 当前单条、批量和在线检索均已恢复，30 条中文门禁 Top-1 96.67%、Top-3 100%、Provider error 0。新的 v2 collection、完整删除/重建/恢复门禁和正式发布回滚尚未执行；生产 Secret Manager、SSO 和正式环境密钥轮换仍属于部署侧待办。

## 1. 目标与非目标

### 1.1 目标

为 Web、后续 Mobile 提供受权限和审计约束的 AI Copilot，首期覆盖：

- 多轮业务聊天与流式回答。
- 根据商品名称、昵称、规格、用途等描述搜索商品。
- 使用自然语言查询销售订单、采购订单、库存、资金流水和既有经营报表。
- 根据对话内容生成销售订单、采购订单、库存调整的**结构化草稿**。
- 自动发现商品资料、流水、订单、数量等数据的异常或缺口，并生成可复核的整理建议。
- 将查询结果、统计口径、引用单据、草稿版本和用户最终动作完整审计。

### 1.2 非目标

- AI 不直接创建、提交、取消、回退任何正式单据。
- AI 不直接操作 MariaDB、Frappe Document、库存或会计字段。
- AI 不生成或执行原始 SQL。
- 首期不覆盖发票、收付款、退款、退货、取消订单等高风险账务动作。
- 不把所有交易数据无差别写入向量库；实时业务事实以受控工具查询为准。

## 2. 核心安全原则

1. **草稿优先**：AI 的产物是 `AI Draft`，不是 Sales Order、Purchase Order 等 ERP 正式单据。
2. **用户执行**：用户可继续让 AI 调整、手工编辑、放弃草稿，或进入现有编辑页；最终“创建 / 提交 / 取消”等按钮由用户主动点击。
3. **Frappe 是事实源**：权限、价格、库存、UOM 换算、单据校验、幂等与正式写入均由 `myapp` 服务层执行。
4. **最小权限**：模型和编排服务只能使用工具白名单，所有工具继承当前用户的公司、仓库、客户、供应商等数据范围。
5. **可解释与可追溯**：查询回答必须带来源和筛选口径；草稿与建议必须记录模型、Prompt 版本、工具调用与用户修改链路。
6. **实时复核**：用户进入正式业务页或创建前，必须重新校验商品、库存、价格、UOM、权限和单据状态，不能相信生成时的缓存数据。

## 3. 总体架构

```text
Web AI 工作台 / 后续 Mobile
    │ JWT、SSE
    ▼
myapp AI Gateway（Frappe）
    ├─ 身份、数据范围、会话、草稿、审计
    ├─ 受控业务工具与正式写入
    └─ AI 服务短期访问凭证
    │ 内网服务身份
    ▼
AI Orchestrator（独立 FastAPI 服务）
    ├─ 场景编排、Prompt 版本、RAG、结构化校验
    ├─ 工具调用、模型能力策略、降级、异步任务
    └─ Langfuse trace / 评测事件
    │ OpenAI 兼容协议
    ▼
LiteLLM Proxy（内部部署）
    ├─ 模型别名、供应商适配、限流、预算、降级
    └─ 供应商密钥与模型路由
    ▼
GPT / Claude / DeepSeek / GLM / Embedding 模型
```

ERP 场景采用混合编排：用户身份、公司范围、商品/订单/库存/报表工具执行和审计留在 Frappe；AI Orchestrator 负责 Prompt、模型能力和对裁剪结果的表达。这样避免 AI 服务使用超级账号回调 ERP，也避免复制业务逻辑。未来无 ERP 数据的通用聊天、摘要、翻译等能力可增加独立客户端入口，但必须另行实现 OIDC/JWT、多应用、租户预算、CORS 和限流；当前内部 Bearer 接口禁止浏览器直连。

当前 LiteLLM 内网地址只作为 AI Orchestrator 的部署环境变量，例如 `MYAPP_AI_LITELLM_BASE_URL`；不得由 Web/Mobile 访问，也不得在前端暴露供应商密钥或 LiteLLM 管理密钥。

## 4. 模型接入与能力策略

业务代码不得写死 `gpt-*`、`claude-*`、`deepseek-*` 或 `glm-*`。业务只声明能力，AI Orchestrator 通过 LiteLLM 模型别名选择实际模型。

| 能力别名 | 典型用途 | 必须能力 |
|---|---|---|
| `erp-fast-chat` | 分类、摘要、简单问答 | 流式文本 |
| `erp-reasoning` | 风险分析、复杂解释、汇报归纳 | 长上下文、稳定中文推理 |
| `erp-structured` | 查询 DSL、单据草稿 | 工具调用、JSON Schema |
| `erp-vision` | 票据、报价单、商品图片理解 | 图像输入 |
| `erp-embedding` | 商品 / 知识库检索 | 固定向量维度 |
| `erp-rerank` | 商品和知识搜索重排 | 查询-文档相关性评分 |

跨供应商默认接口：

- 文本、工具调用、流式输出：LiteLLM `/v1/chat/completions`。
- 向量化：LiteLLM `/v1/embeddings`。
- GPT `Responses API` 等厂商高级能力只能以显式 capability extension 使用，不能作为所有模型的通用契约。

降级只能在同一能力组且已通过兼容性验证的模型之间进行。例如视觉不能降级到纯文本模型，严格 JSON 草稿不能降级到未通过 Schema 回归的模型。

模型注册、场景策略、预算、灰度、审批、发布、回滚和 Embedding collection 切换的详细设计见 `AI_MODEL_GOVERNANCE_TECH_DESIGN.zh-CN.md`。

## 5. Web 信息架构

新增一级路由 `/ai`：

```text
/ai
 ├─ 会话列表：我的会话、共享模板、已归档会话
 ├─ 对话区：流式回答、澄清问题、工具调用状态、来源引用
 └─ 上下文与产物区：公司/数据范围、商品候选、查询结果、单据草稿、风险提示

/ai/drafts/:draftId
 ├─ 草稿版本与字段差异
 ├─ 校验问题、候选选择与 AI 修改入口
 └─ “在业务编辑器中继续”入口
```

页面必须使用领域 service，不解析 LiteLLM 或供应商原始响应。聊天消息中的订单、商品、报表和草稿应渲染为可点击的业务卡片，而非仅展示 Markdown 文本。

## 6. 核心业务流程

### 6.1 单据草稿生成与用户确认

```text
用户对话请求
    ↓
AI 调用 search_products / search_parties 等只读工具
    ↓ 有歧义则返回候选项和澄清问题
AI 输出严格 JSON 草稿
    ↓
myapp validate_document_draft 进行业务校验
    ↓
Web 显示草稿、来源、库存/价格/UOM/权限问题
    ↓
用户选择：继续 AI 调整 / 手工编辑 / 放弃 / 在业务编辑器中继续
    ↓
现有订单编辑页面预填草稿
    ↓
用户主动点击创建或保存
    ↓
既有业务接口重新校验并以 Idempotency-Key 创建正式单据
```

草稿中不确定内容必须显式标为 `needs_clarification` 或 `warning`，例如客户或商品多候选、未配置价格、库存不足、仓库缺失。禁止模型静默猜测后将任意值作为确定事实。

### 6.2 商品描述搜索

采用混合检索：

1. 商品编码、名称、昵称、条码、品牌和分类的精确/模糊检索。
2. 商品名称、昵称、规格、用途、品牌、分类的向量语义检索。
3. Rerank，并按公司、启停状态、可见范围、仓库库存等业务过滤。
4. 返回商品候选、匹配原因、单位、价格、库存和详情跳转。

商品主数据变更后通过 Item Hook 异步更新独立 Qdrant 索引，并由小时任务补偿漏同步和失败记录。`MyApp AI Product Vector State` 记录内容哈希、索引版本、源修改时间、Embedding 模型、collection、状态与失败原因；模型或 collection 变化会强制补建，避免混用不同向量空间。Item 删除会进入幂等向量删除。索引只保存商品主数据文本和治理元数据，不保存价格、库存或交易数据。

测试数据噪声通过 `MYAPP_AI_VECTOR_EXCLUDED_ITEM_PREFIXES` 治理。前缀匹配在增量写入、Item Hook、小时补偿、管理员重建、候选 collection 构建和语义候选二次过滤中统一执行。排除项已有 point 时转为幂等删除并把向量状态标记为 `deleted`；ERP Item、销售/采购/库存历史保持原样，避免破坏审计和外键引用。初始仅启用已确认的 `HTTP-` 测试前缀，其他疑似测试编码必须先审计交易引用再扩展。

检索使用关键词候选与向量候选的 Reciprocal Rank Fusion，再叠加确定性字段命中和向量相似度进行第二阶段重排。Qdrant 候选必须回到 Frappe，重新执行当前用户记录权限、公司范围、启停状态、销售/采购属性，并通过 `search_product_v2` 读取实时价格、库存与 UOM；向量服务失败时降级到关键词检索。

Qdrant 运行单元和内部 upsert/delete/search 契约已完成。LiteLLM `erp-embedding` 当前单条字符串、单条数组和两条批量请求均返回 HTTP 200、1024 维；当前运行 Orchestrator 的真实 `数码相机` 查询返回 `SKU010` Top-1。历史 582 points 基线完成删除幂等、恢复和 10 条中文 Top-1/Top-3 10/10 验收；质量治理后在线 alias 仍指向 `myapp-products-v1`，points 从 582 降到 143，剩余 payload 中 `HTTP-` 为 0 且 SKU001～SKU010 全部存在。最新 30 条中文门禁 Top-1 96.67%、Top-3 100%、Provider error 0、排除候选泄漏 0、p50 145.692ms、p95 211.745ms，达到当前 v1 在线门槛；唯一 Top-1 未命中是背包用途表达，目标 `SKU008` 位于 Top-2。若底层模型权重或向量空间发生变化，仍必须新建 collection、全量补建、执行完整门禁并原子切换 alias，不得只复用别名覆盖旧向量空间。

系统管理员可通过 `get_ai_product_vector_status_v1` 查看启用状态、索引版本、Embedding 模型、collection、商品总数、待建数量、状态分布、排除前缀/Item/仍已索引数量、最近失败以及 Qdrant 点数/维度；`rebuild_ai_product_vector_index_v1` 支持指定商品、仅失败项和最多 500 条的受控分批重建，且不会重新加入排除项。`cleanup_excluded_ai_product_vectors_v1` 支持 dry-run 和带原因、幂等键、critical 审计的正式清理，只删除 Qdrant points。普通业务用户不能访问这些治理接口。

中文检索质量门禁使用版本化 `product-retrieval-zh-cn-v1` 数据集，围绕 SKU001～SKU010 各提供直接名称、用途表达和模糊描述三类查询，共 30 条。`python -m myapp_ai.retrieval_quality` 生成机器可读报告，检查 Top-1、Top-3、Provider 错误、排除候选泄漏和 p50/p95；真实运行必须显式启用 live eval。Provider 故障时门禁失败关闭，不能用 mock 通过替代真实发布证据。

商品请求会先用确定性规则移除“帮我找、只说明”等操作语言，并从复合描述中提取最多 5 个搜索短语，再合并去重候选；该步骤不额外调用模型，控制测试和运行成本。

### 6.3 自然语言查询与汇报

模型先输出受限查询 DSL，而不是 SQL：

```json
{
  "entity": "sales_order",
  "filters": {
    "date_range": "this_month",
    "payment_status": "unpaid"
  },
  "aggregation": "summary"
}
```

Frappe 校验实体、字段、操作符、时间范围和用户数据权限后，调用既有订单、库存、资金、报表领域服务。回答必须带：公司、日期范围、过滤条件、生成时间、指标口径和原始单据/报表入口。

当前 `order_query` 已实现第一版确定性 DSL，支持销售/采购、今天/本周/本月/上月/近 N 天、未完成/收发货/收付款/完成/取消、金额排序与最低金额、最多 20 条结果。它复用 `search_sales_orders_v2` / `search_purchase_orders_v2`，并对返回单据再次执行记录级权限过滤。未识别的日期默认限定近 30 天；同时出现销售和采购语义时要求用户拆分问题。

当前 `report_summary` 已实现第一版确定性 DSL，支持经营总览、销售、采购、资金、应收应付，以及今天/本周/本月/上月/近 N 天（最多 366 天）。Frappe 在执行既有结构化报表服务前校验公司范围和报表依赖 DocType 的读取权限，只向模型提供指标、趋势、排行和口径元数据；Web 以独立报表来源卡片展示服务端事实。

当前报表的钻取、通用导出、多公司对账和性能基线仍是独立 P1 工作；AI 不得虚构这些尚未存在的指标或数据。

### 6.4 数据整理与异常建议

首期 `MyApp AI Data Task` 已实现商品主数据的受控建议闭环：

- `analyze_ai_product_data_v1` 使用确定性规则扫描启用且描述为空的 Item，按商品名称、品牌和商品组生成描述建议；该扫描不调用模型、不产生供应商费用。
- `create_ai_data_task_v1` 支持数据管理员手工创建商品字段建议，首期只允许 `item_name`、`description`、`brand`、`item_group`。
- 任务保存前值、建议值、证据、分析结果、模型/Prompt/策略版本、发起人、审批人、执行人、回滚人和结果摘要。
- 角色按职责分离：`AI Data Steward` 可查看、创建和执行；`AI Data Approver` 可查看和审批；`AI Auditor` 只读；只有 `System Manager` 可回滚。
- 发起人不能审批自己的任务，审批人不能执行同一任务。执行前重新读取 Item 并核对源数据；发生漂移时任务进入 `failed`，不会覆盖人工变更。
- 执行只调用既有 `update_product_v2`，使用任务版本化幂等键；回滚只在当前值仍等于任务建议值时恢复原值，避免覆盖任务执行后的新修改。

生命周期：`review_required → approved → executed → rolled_back`，并支持 `rejected`、源数据漂移后的 `failed`；`queued`、`analyzed` 保留为后续异步分析扩展状态。

首期明确禁止价格、库存、订单、发票、收付款和其他正式交易字段。订单异常、流水归类、库存建议、重复项合并和高风险批量治理仍只属于后续扩展，必须另行设计权限、批次、双人审批和失败恢复，不能复用首期单字段任务绕过正式业务流程。

## 7. 工具白名单与权限

AI Orchestrator 不直连 MariaDB，也不调用 Frappe 的泛化 `get_list` / `run_doc_method`。仅允许调用明确登记的内部工具。

只读工具：

- `search_products`
- `get_product_context`
- `search_sales_orders`
- `search_purchase_orders`
- `get_order_detail`
- `get_inventory_summary`
- `get_cashflow_entries`
- `get_business_report`
- `search_knowledge`

草稿工具：

- `build_sales_order_draft`
- `build_purchase_order_draft`
- `build_inventory_adjustment_draft`
- `validate_document_draft`
- `save_ai_draft`

AI 不拥有 `submit`、`cancel`、`record_payment`、`adjust_stock` 等执行工具。正式写入只能由用户在既有页面调用既有 API 完成。

每次工具调用均由 Frappe 根据当前用户重新计算公司、仓库、客户、供应商和 DocType 权限；不得信任模型请求中携带的 company 或数据范围。

## 8. 领域数据与审计

当前已建立以下内部审计表；后续如需要 Desk 表单治理，再评估升级为标准 DocType：

| DocType | 作用 | 核心字段 |
|---|---|---|
| `MyApp AI Conversation` | 会话主档（已实现） | owner、company_scope、status、retention_until |
| `MyApp AI Message` | 消息与来源引用（已实现） | conversation、role、content_hash、citations、prompt_version |
| `MyApp AI Run` | 一次模型运行（已实现） | scenario、model_alias、latency、token_usage、trace_id、status、tool_calls |
| `MyApp AI Draft` | 可编辑业务草稿 | draft_type、payload、validation_result、version、status、source_run |
| `MyApp AI Draft Line` | 草稿行审计 | item、uom、qty、rate、source_candidates、user_overrides |
| `MyApp AI Data Task` | 整理建议、职责分离执行与回滚（已实现） | task_type、before_value、proposed_value、evidence、requested_by、reviewer、executed_by、rollback_by、status |
| `MyApp AI Audit Event` | 不可抵赖审计 | actor、action、object、tool_name、parameter_hash、result_hash |

敏感原文、Prompt 和工具返回不应默认永久明文保存。应按数据分级决定脱敏、加密、访问角色和保留期；审计至少保存必要的哈希、摘要、来源与操作链路。

## 9. API 契约

Web 只调用 `myapp` 网关，不调用 LiteLLM。建议 API：

- `create_ai_conversation_v1`（已实现）
- `list_ai_conversations_v1`（已实现）
- `get_ai_conversation_v1`（已实现）
- `archive_ai_conversation_v1`（已实现）
- `chat_ai_v1`（已实现同步事件契约）
- `stream_ai_message_v1`（已实现真正 SSE）
- `get_ai_draft_v1`
- `update_ai_draft_v1`
- `validate_ai_draft_v1`
- `prepare_ai_draft_handoff_v1`
- `analyze_ai_product_data_v1`（已实现）
- `create_ai_data_task_v1`（已实现）
- `list_ai_data_tasks_v1`（已实现）
- `get_ai_data_task_v1`（已实现）
- `review_ai_data_task_v1`（已实现）
- `execute_ai_data_task_v1`（已实现）
- `rollback_ai_data_task_v1`（已实现）
- `submit_ai_feedback_v1`（已实现）

`stream_ai_message_v1` 使用 SSE，事件类型至少包括：`message_delta`、`tool_started`、`tool_completed`、`citation`、`draft_created`、`warning`、`completed`、`error`。服务端对模型响应实施 JSON Schema 校验、超时、内容过滤和重试策略。

`chat_ai_v1` 保留同步兼容契约；Web 默认使用 `stream_ai_message_v1`，通过 POST、JWT Bearer 和 `ReadableStream` 增量消费 SSE。浏览器不使用无法携带 POST body / Authorization 的原生 `EventSource`。流中断会把 Run 标为失败，不会生成半条成功消息。

`prepare_ai_draft_handoff_v1` 只返回可被现有订单/库存编辑器预填的安全载荷与当前校验结果；它不创建正式单据。

当前销售订单草稿已实现 `generate_ai_sales_order_draft_v1`、`get_ai_draft_v1` 和 `prepare_ai_draft_handoff_v1`。模型只提取客户/商品称呼、数量、单位、日期和备注候选；Frappe 再按当前用户权限解析真实 Customer、Item、Warehouse，使用商品接口返回的 UOM、换算系数和当前参考价，并把歧义保存为候选与校验错误。模型建议价格不会直接采用。只有 `ready_for_handoff=true` 的草稿可交接，Web 使用一次性 sessionStorage 载荷预填现有销售订单页面；用户仍需主动点击创建，既有 v2 接口会再次校验。

草稿生命周期已补充 `update_ai_draft_v1` 和 `discard_ai_draft_v1`。人工修改保存后，Frappe 不信任浏览器提交的商品事实或价格，会重新解析真实主数据、重建 Draft Line、递增版本并刷新 validation；行审计记录 `updated_by_user`。只有 `draft` 状态允许修改、放弃或交接，`handed_off` 状态不可再次修改或放弃。Web 草稿卡片提供结构化编辑表单、校验错误、版本和状态展示。

版本治理使用不可变 `MyApp AI Draft Version` 快照。每次生成、人工修改或历史恢复都会保存 payload、validation、变更来源、操作者和版本号；`list_ai_draft_versions_v1` 返回字段与商品行差异。`restore_ai_draft_version_v1` 不直接覆盖当前 JSON，而是把历史 payload 重新送入当前主数据解析和校验流程，并创建一个新的版本，避免恢复旧价格、失效仓库或过期 UOM。

结构化模型优先使用 OpenAI 兼容 `json_schema`；供应商明确拒绝该能力时，Orchestrator 可降级为 JSON-only 输出，但结果仍必须通过同一 Pydantic Schema，任何自由文本、缺字段、越界数量或类型错误都会失败，不会持久化为草稿。

采购订单草稿使用独立 `purchase_order_draft` Schema 和 `/internal/v1/drafts/purchase-order`。Frappe 解析真实 Supplier，并以 `item_context=purchase` 查询采购商品；价格只取后端 `standard_buying_rate` / buying prices，不复用销售价或模型建议价。采购默认 UOM、换算系数、收货仓库、公司币种、供应商参考号、订单日期和预计到货日期独立校验。校验通过后仅预填现有采购订单编辑器，正式采购单仍由用户主动创建。

库存调整草稿使用独立 `inventory_adjustment_draft` Schema 和 `/internal/v1/drafts/inventory-adjustment`，只允许单个库存商品的 `set_target`、`increase`、`decrease` 三种候选语义。Frappe 按当前用户和公司权限解析真实 Item / Warehouse，使用 `item_context=inventory` 和共享 UOM 换算重新计算实时库存、目标库存、差异数量与估值参考；调整原因必填，减少后目标库存不得为负。交接只把库存单位下的安全目标数量预填到现有 `/inventory/adjustments` 页面，AI 不调用 `reconcile_inventory_stock_v1`，也不创建或提交 `Stock Entry` / `Stock Reconciliation`。

## 10. 可观测性、治理与防护

- 使用 Langfuse 或等价自托管平台记录 trace、Prompt 版本、模型别名、Token、成本、延迟、失败和用户反馈。
- LiteLLM 负责供应商密钥、模型别名、限流、预算和同能力降级；业务系统不保存供应商密钥。
- 管理台需维护场景到 capability 的映射、模型启停、预算、超时、降级候选、数据留存和灰度范围。
- 外部文档、商品描述、备注和用户输入都视为不可信数据，不能改变工具权限、模型策略或系统指令，防止 Prompt Injection。
- 模型、Prompt 或工具策略变更必须经过固定评测集、回归测试和灰度发布；不得直接全员切换。

异步连接池、多副本、限流背压、SSE 长连接、独立向量队列、Qdrant 高可用和压测验收的详细设计见 `AI_HIGH_CONCURRENCY_TECH_DESIGN.zh-CN.md`。当前本地 `bench serve + 单 Uvicorn + 单 Qdrant` 仅用于开发与功能验收，不代表生产高并发能力。

当前 Orchestrator 已实现 Langfuse ingestion 接入：trace 关联 Frappe conversation / run，generation 记录模型、Token、成功或错误状态，点赞/点踩和固定评测结果同步为 score。集成为可选且失败开放，未配置或 Langfuse 不可用时不阻断模型调用和 ERP 反馈保存。HTTP 207 批次响应必须同时确认逐事件 `errors` 为空、`successes` 覆盖本批次全部事件 ID，不能只按状态码或任意一个 success 判断成功。Trace 的 `release`、generation 的 Prompt `version`、score 的 `environment/source` 使用 Langfuse 原生字段；用户反馈为 `source=API`，固定评测为 `source=EVAL`。默认 `MYAPP_AI_LANGFUSE_CAPTURE_CONTENT=0`，输入、输出和反馈 comment 只发送 SHA-256、字符数和字节数；只有完成数据分级、访问控制和保留期评审后才能上传原文。

父仓库现提供 `overrides/compose.langfuse.yaml` 和随机密钥初始化脚本，本地固定使用 Langfuse v3.212.0，并隔离 PostgreSQL、ClickHouse、Redis、MinIO 数据卷。初始化脚本生成 `0600` 密钥文件且拒绝覆盖现有文件。Web/MinIO 只绑定 loopback，数据库、ClickHouse、Redis 和 MinIO Console 不发布宿主机端口。Orchestrator 镜像固定基础镜像 digest，以 UID/GID `10001` 运行，并由 Compose 强制只读根文件系统、清空 capabilities、启用 `no-new-privileges` 和 `/tmp` tmpfs。真实验收已确认 trace、generation、固定评测 score 和 `user-feedback` 可查询；停止 Langfuse Web 时模型调用仍完成，反馈仍被本地接受且明确返回观测未同步。

固定评测集采用 21 个纯合成用例和确定性 grader，覆盖三类结构化草稿、grounding、无上下文事实边界、Prompt Injection、写操作诱导和系统提示/密钥提取。Offline replay 与低价真实模型 live gate 均需满足：critical、安全、Schema 和禁止模式 100%，结构化字段准确率不低于 95%，普通场景通过率不低于 90%。只有覆盖当前 mode 全部用例的报告具备 `release_gate_eligible=true`；`--case` / `--tag` 子集报告只用于诊断，缺失指标返回 `null`，未知 case ID 直接作为配置错误拒绝。报告默认只保留输出哈希、长度、失败原因、Prompt/DataSet 版本、延迟和 Token。当前 Prompt registry 的有效版本为只读 `erp-readonly-v5`，三类草稿分别为 `sales-order-draft-v2`、`purchase-order-draft-v2`、`inventory-adjustment-draft-v2`，Frappe 审计和 Orchestrator/Langfuse 必须保持同值。调用方显式提供不一致或空白 Prompt 版本时，Orchestrator 返回 HTTP `409`；`/health` 返回完整 `prompt_versions`，不得静默覆盖版本漂移。

generation/trace 已迁移到 Langfuse OTLP HTTP `/api/public/otel/v1/traces`；用户反馈和固定评测 score 继续使用 score ingestion，并保留 HTTP 207 全事件成功校验。父仓库已完成 Qdrant snapshot、Langfuse PostgreSQL/ClickHouse/Redis/MinIO clean-stop 联合备份、隔离恢复和 AI 内部服务 Token 轮换演练。生产剩余缺口是正式 Secret Manager 下的 Langfuse Project Key/恢复根密钥轮换、SSO/访问治理、成本看板和定时异地备份。

## 11. 分期计划与验收

### Phase A：平台与只读 Copilot

- AI Orchestrator、LiteLLM capability 别名、Langfuse trace、模型能力矩阵。
- `/ai` 聊天页、会话、SSE、来源引用和反馈。
- 商品描述搜索、自然语言订单查询、经营报表解释。
- 只读工具白名单、数据范围透传、审计和费用统计。

验收：无权限用户不能通过 AI 获取越权数据；所有回答可追溯来源；模型不可调用写工具；服务故障有明确降级/错误状态。

### Phase B：单据草稿

- 销售订单、采购订单、库存调整草稿。
- 结构化 Schema、候选澄清、版本对比、校验中心和现有编辑页预填。
- 草稿到正式单据的用户手动交接与幂等创建。

验收：AI 不创建任何正式单据；用户编辑后的值优先；创建前实时复核；草稿可追溯到会话，正式单据可追溯到草稿。

### Phase C：数据治理与主动助手

- 数据完整性/异常任务、人工审批、批量建议、定时经营简报。
- 固定评测集已完成第一版；继续建设灰度、成本治理、模型策略管理台和生产级观测运维。

验收：建议与实际执行分离；批量变更可审计、可回滚；高风险场景满足审批规则；模型升级不会导致指标或权限回归。

## 12. 实施前决策

开始编码前需确认：

1. AI Orchestrator 的部署方式、内部域名、服务认证和高可用要求。
2. LiteLLM 的模型别名、供应商数据留存策略、预算和降级顺序。
3. Qdrant 或 pgvector 的选型、备份、索引更新与删除策略。
4. 会话、Prompt、工具结果和审计日志的数据分级与保留期。
5. Phase B 第一批允许的单据类型、每类草稿必填字段和审批要求。
