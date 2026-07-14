# AI 模型治理与策略管理技术设计

> 状态：详细设计基线，尚未实现管理 DocType、API 和 Web 页面。当前运行配置仍来自 `.env.ai.local` 与 LiteLLM；本文定义后续企业级管理模块的边界和验收标准。

## 1. 目标与边界

目标：

- 让业务场景选择稳定的 capability，而不是写死供应商模型。
- 支持模型注册、场景策略、预算、限流、灰度、审批、发布和回滚。
- 模型或 Prompt 变更必须经过固定评测和可审计发布。
- 统一展示调用量、Token、成本、延迟、错误率和用户反馈。
- 对 Embedding 变更执行新 collection 建设、质量验收和原子切换。

非目标：

- MyApp 不保存供应商 API Key，也不替代 LiteLLM 的供应商适配能力。
- 普通用户不能在每次对话中任意选择高成本模型。
- 模型策略不能扩大 Frappe 权限、工具白名单或正式写入能力。
- 不允许把尚未通过 Schema、安全和质量评测的模型直接发布到全量用户。

## 2. 职责边界

| 组件 | 职责 |
|---|---|
| Frappe | 策略主数据、权限、审批、审计、预算口径、发布版本和使用汇总 |
| AI Orchestrator | 按已发布策略解析 capability、执行模型调用、超时、并发控制和运行降级 |
| LiteLLM | 供应商密钥、实际模型映射、供应商路由、供应商级限流和成本元数据 |
| Langfuse | Trace、generation、Prompt、评分、延迟和质量分析 |
| Qdrant | 按不可变 Embedding 版本保存向量 collection |

Frappe 只保存 LiteLLM 别名和治理元数据。LiteLLM 管理 Key 不得进入浏览器、MyApp DocType、审计正文或日志。

## 3. 权限模型

- `System Manager`：查看全部状态、创建策略草稿、发起发布和紧急回滚。
- `AI Model Manager`：维护模型注册信息和策略草稿，但不能自行审批生产发布。
- `AI Model Approver`：审批发布、预算提升和高风险供应商切换。
- `AI Auditor`：只读查看版本、评测、成本、失败和操作日志。
- 普通业务用户：只能消费当前生效策略，不可读取供应商配置和内部成本细节。

生产环境默认要求起草人与审批人分离。紧急回滚允许 System Manager 执行，但必须填写原因并产生高优先级审计事件。

## 4. 数据模型

### 4.1 `MyApp AI Model Registry`

记录可被策略引用的 LiteLLM 能力别名，不保存密钥。

主要字段：

- `model_alias`：唯一、稳定；例如 `erp-fast-chat-v1`。
- `capability`：`fast_chat / reasoning / structured / vision / embedding / rerank`。
- `status`：`discovered / validated / active / degraded / disabled / retired`。
- `provider_family`、`provider_model_display`：只用于治理展示，不作为业务调用参数。
- `supports_streaming`、`supports_json_schema`、`supports_vision`。
- `embedding_dimensions`、`embedding_space_version`：仅向量模型使用。
- `data_region`、`retention_policy`、`sensitive_data_allowed`。
- `input_cost`、`output_cost`、`currency`：来自受控同步或人工复核。
- `last_health_at`、`last_health_status`、`last_error_code`。
- `registry_version`、`source_hash`。

模型同步只能新增或更新发现状态，不能自动发布到业务策略。

### 4.2 `MyApp AI Model Policy`

定义一个业务场景如何选择 capability 和模型。

主要字段：

- `policy_code`、`policy_name`、`scenario`、`capability`。
- `company_scope`、`role_scope`、`environment`。
- `primary_model_alias`、`fallback_model_aliases`。
- `reasoning_effort`、`max_completion_tokens`、`timeout_seconds`。
- `max_concurrency`、`requests_per_minute`、`tokens_per_minute`。
- `daily_budget`、`monthly_budget`、`budget_currency`、`budget_action`。
- `rollout_percentage`、`rollout_seed`、`effective_from`、`effective_to`。
- `status`：`draft / validating / review_required / approved / scheduled / active / superseded / disabled`。
- `current_version`、`published_version`。

### 4.3 `MyApp AI Model Policy Version`

不可变快照，保存完整策略 JSON、内容哈希、起草人、审批人、评测报告、发布时间和回滚来源。任何修改都创建新版本，不能覆盖已发布版本。

### 4.4 `MyApp AI Model Usage Daily`

按日期、环境、公司、场景、策略版本和模型别名聚合：请求数、成功数、错误数、Token、估算成本、p50/p95 延迟、首 Token 延迟、用户反馈和降级次数。原始内容不进入聚合表。

## 5. 策略解析

解析顺序固定且可解释：

1. `scenario + company + role`。
2. `scenario + company`。
3. `scenario + global`。
4. capability 默认策略。
5. 安全的系统降级策略。

同一优先级出现多个有效策略时必须拒绝发布，不能运行时随机选择。灰度使用稳定哈希：`user_hash + company + scenario + rollout_seed`，保证同一用户在灰度周期内稳定命中。

Orchestrator 返回并审计 `policy_code`、`policy_version`、`model_alias`、`fallback_reason`；客户端不能覆盖这些字段。

## 6. 发布生命周期

```text
draft
  → validating
  → review_required
  → approved
  → scheduled / active
  → superseded / disabled
```

发布前必须通过：

- LiteLLM 模型存在性和健康检查。
- capability 兼容性检查。
- Prompt 版本兼容性检查。
- Offline full gate。
- 受控 Live gate。
- 预算和数据留存评审。
- 回滚目标可用性检查。

发布采用版本化配置快照。Orchestrator 通过短 TTL 缓存消费已发布策略，发布事件主动失效缓存；缓存或 Frappe 暂时不可用时继续使用最后一个已验证快照，不回退到客户端参数。

## 7. 降级、预算和熔断

- 降级候选必须属于同一 capability，并单独通过固定评测。
- `structured` 不得降级到未通过 JSON Schema 的模型。
- 预算动作支持 `warn / use_lower_cost_fallback / reject_noncritical`，不得静默扩大预算。
- 连续超时、429 或 5xx 达到阈值后对模型别名短时熔断；半开探测成功后恢复。
- 草稿生成、只读查询和评测使用独立并发池，避免评测挤占生产业务。
- 所有 429、降级、预算拒绝和熔断都写入 Run 与指标聚合。

## 8. Embedding 特殊治理

Embedding 别名不得原地映射到新的向量空间。正确流程：

1. 注册不可变别名，例如 `erp-embedding-v2`。
2. 创建新 collection，例如 `myapp-products-v2`。
3. 全量补建并记录模型、维度、collection 和内容版本。
4. 执行固定语义集、权限、删除、恢复和性能验收。
5. 使用配置版本或 Qdrant alias 原子切换。
6. 保留旧 collection 至回滚窗口结束。
7. 审批后清理旧 collection。

维度相同也不能跳过重建，因为不同模型的向量空间仍不兼容。

## 9. 计划 API

以下接口属于设计目标，尚未进入当前 API Gateway：

- `get_ai_model_governance_overview_v1`
- `sync_ai_model_registry_v1`
- `list_ai_model_policies_v1`
- `save_ai_model_policy_draft_v1`
- `validate_ai_model_policy_v1`
- `approve_ai_model_policy_v1`
- `publish_ai_model_policy_v1`
- `rollback_ai_model_policy_v1`
- `get_ai_model_usage_summary_v1`

所有写接口必须使用 POST、权限检查、幂等 key 和审计原因。发布、预算提升、供应商区域变化和 Embedding 切换属于高风险操作。

## 10. Web 管理台

建议路由：

```text
/administration/ai/models
  ├─ 模型注册表与健康状态
  ├─ 场景策略
  ├─ 发布与回滚
  ├─ 预算与用量
  └─ 评测与异常
```

页面使用 ProTable、ProCard、Descriptions、Steps 和 Drawer。策略编辑必须明确展示实际影响的场景、公司、角色、预算和降级链，发布前展示评测差异与回滚目标。

## 11. 验收标准

- 普通用户不能指定模型或读取供应商密钥。
- 相同请求上下文得到确定性策略解析结果。
- 未通过 full gate 的版本不能发布。
- 灰度分流稳定、可观测并可一键回滚。
- 预算、限流、降级和熔断行为可审计。
- Orchestrator 多副本读取到同一发布版本。
- Embedding 切换不会混用向量空间。
- 管理服务故障不绕过既有权限和工具边界。

## 12. 实施顺序

1. 模型注册表、策略与不可变版本 DocType。
2. 只读模型同步、健康检查和策略解析器。
3. 策略草稿、验证、审批、发布和回滚 API。
4. Orchestrator 策略缓存、限流、预算和降级执行。
5. Web 管理台与用量看板。
6. Embedding 双 collection 发布和回滚自动化。

