# AI Copilot 模块技术设计

> 状态：Phase A 只读纵向链路已覆盖会话/消息/Run、SSE、反馈、商品/订单/报表工具和可选 Langfuse。Phase B 已完成销售与采购订单草稿纵向链路，以及人工修改、不可变版本、差异、安全恢复、放弃和现有编辑器预填。库存调整草稿、语义向量检索、真实 Langfuse 实例和数据治理任务仍待继续。

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

商品主数据变更后异步更新向量索引。推荐使用独立 Qdrant；规模较小的首期可采用 PostgreSQL + pgvector。索引条目必须携带公司范围、启停状态和索引版本。

当前第一阶段先复用 `search_product_v2` 完成编码、名称、昵称、条码和规格的精确/模糊检索，最多向模型提供 8 条裁剪候选，并以商品卡片作为来源引用。向量检索和 rerank 尚未启用，因此当前能力不应宣传为完整语义检索。

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

首期只生成建议任务：

- 商品名称、昵称、条码、品牌、分类、单位缺失或疑似重复。
- 订单数量、价格、未结、交期、库存异常。
- 流水的往来方、付款方式、参考号归类建议。
- 库存数量、单位或资料完整性检查。

生命周期：`queued → analyzed → review_required → approved → executed / rejected / failed`。

任何批量更新必须通过已有主数据/业务写接口，记录前后值、审批人、模型与证据。交易、库存、发票、收付款相关建议必须人工确认；高风险批量变更应支持双人审批。

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
| `MyApp AI Data Task` | 整理建议与审批 | task_type、before_value、proposed_value、evidence、reviewer、status |
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
- `list_ai_data_tasks_v1`
- `review_ai_data_task_v1`
- `submit_ai_feedback_v1`（已实现）

`stream_ai_message_v1` 使用 SSE，事件类型至少包括：`message_delta`、`tool_started`、`tool_completed`、`citation`、`draft_created`、`warning`、`completed`、`error`。服务端对模型响应实施 JSON Schema 校验、超时、内容过滤和重试策略。

`chat_ai_v1` 保留同步兼容契约；Web 默认使用 `stream_ai_message_v1`，通过 POST、JWT Bearer 和 `ReadableStream` 增量消费 SSE。浏览器不使用无法携带 POST body / Authorization 的原生 `EventSource`。流中断会把 Run 标为失败，不会生成半条成功消息。

`prepare_ai_draft_handoff_v1` 只返回可被现有订单/库存编辑器预填的安全载荷与当前校验结果；它不创建正式单据。

当前销售订单草稿已实现 `generate_ai_sales_order_draft_v1`、`get_ai_draft_v1` 和 `prepare_ai_draft_handoff_v1`。模型只提取客户/商品称呼、数量、单位、日期和备注候选；Frappe 再按当前用户权限解析真实 Customer、Item、Warehouse，使用商品接口返回的 UOM、换算系数和当前参考价，并把歧义保存为候选与校验错误。模型建议价格不会直接采用。只有 `ready_for_handoff=true` 的草稿可交接，Web 使用一次性 sessionStorage 载荷预填现有销售订单页面；用户仍需主动点击创建，既有 v2 接口会再次校验。

草稿生命周期已补充 `update_ai_draft_v1` 和 `discard_ai_draft_v1`。人工修改保存后，Frappe 不信任浏览器提交的商品事实或价格，会重新解析真实主数据、重建 Draft Line、递增版本并刷新 validation；行审计记录 `updated_by_user`。只有 `draft` 状态允许修改、放弃或交接，`handed_off` 状态不可再次修改或放弃。Web 草稿卡片提供结构化编辑表单、校验错误、版本和状态展示。

版本治理使用不可变 `MyApp AI Draft Version` 快照。每次生成、人工修改或历史恢复都会保存 payload、validation、变更来源、操作者和版本号；`list_ai_draft_versions_v1` 返回字段与商品行差异。`restore_ai_draft_version_v1` 不直接覆盖当前 JSON，而是把历史 payload 重新送入当前主数据解析和校验流程，并创建一个新的版本，避免恢复旧价格、失效仓库或过期 UOM。

结构化模型优先使用 OpenAI 兼容 `json_schema`；供应商明确拒绝该能力时，Orchestrator 可降级为 JSON-only 输出，但结果仍必须通过同一 Pydantic Schema，任何自由文本、缺字段、越界数量或类型错误都会失败，不会持久化为草稿。

采购订单草稿使用独立 `purchase_order_draft` Schema 和 `/internal/v1/drafts/purchase-order`。Frappe 解析真实 Supplier，并以 `item_context=purchase` 查询采购商品；价格只取后端 `standard_buying_rate` / buying prices，不复用销售价或模型建议价。采购默认 UOM、换算系数、收货仓库、公司币种、供应商参考号、订单日期和预计到货日期独立校验。校验通过后仅预填现有采购订单编辑器，正式采购单仍由用户主动创建。

## 10. 可观测性、治理与防护

- 使用 Langfuse 或等价自托管平台记录 trace、Prompt 版本、模型别名、Token、成本、延迟、失败和用户反馈。
- LiteLLM 负责供应商密钥、模型别名、限流、预算和同能力降级；业务系统不保存供应商密钥。
- 管理台需维护场景到 capability 的映射、模型启停、预算、超时、降级候选、数据留存和灰度范围。
- 外部文档、商品描述、备注和用户输入都视为不可信数据，不能改变工具权限、模型策略或系统指令，防止 Prompt Injection。
- 模型、Prompt 或工具策略变更必须经过固定评测集、回归测试和灰度发布；不得直接全员切换。

当前 Orchestrator 已实现 Langfuse ingestion 接入：trace 关联 Frappe conversation / run，generation 记录模型、Token、成功或错误状态，点赞/点踩同步为 score。集成为可选且失败开放，未配置或 Langfuse 不可用时不阻断模型调用和 ERP 反馈保存。默认 `MYAPP_AI_LANGFUSE_CAPTURE_CONTENT=0`，只发送输入输出的 SHA-256、字符数和字节数；只有完成数据分级、访问控制和保留期评审后才能上传原文。当前本地环境尚未配置真实 Langfuse 实例，因此部署、成本看板和固定评测集仍待完成。

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
- 评测集、灰度、成本治理、模型策略管理台。

验收：建议与实际执行分离；批量变更可审计、可回滚；高风险场景满足审批规则；模型升级不会导致指标或权限回归。

## 12. 实施前决策

开始编码前需确认：

1. AI Orchestrator 的部署方式、内部域名、服务认证和高可用要求。
2. LiteLLM 的模型别名、供应商数据留存策略、预算和降级顺序。
3. Qdrant 或 pgvector 的选型、备份、索引更新与删除策略。
4. 会话、Prompt、工具结果和审计日志的数据分级与保留期。
5. Phase B 第一批允许的单据类型、每类草稿必填字段和审批要求。
