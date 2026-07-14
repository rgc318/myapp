# AI 高并发与性能技术设计

> 状态：生产化详细设计基线，尚未完成异步连接池、多副本、分布式限流和专项压测。当前本地 `bench serve + 单 Uvicorn + 单 Qdrant` 只用于开发和功能验收。

## 1. 目标与原则

- 在不削弱 Frappe 权限、审计和工具白名单的前提下扩展 AI 并发。
- 对 Chat、SSE、结构化草稿、Embedding、索引任务和评测实施隔离。
- 优先使用限流、背压和可解释降级，避免无界排队造成级联故障。
- 容量结论必须来自压测和生产指标，不能只凭副本数量宣称高并发。
- AI 服务过载不得影响 ERP 正式交易接口。

## 2. 当前基线与瓶颈

当前已有：超时、SSE、LiteLLM 路由、RQ 异步索引、Qdrant、内容哈希去重、关键词降级和 Langfuse Trace。

当前瓶颈：

- Frappe 使用开发态 `bench serve`，不是生产 Gunicorn。
- Orchestrator 只有一个 Uvicorn 进程。
- LiteLLM、Qdrant、Langfuse 调用使用同步客户端，并为每次请求创建连接。
- SSE 长连接占用 Frappe WSGI Worker。
- 商品索引主要按单商品调用 Embedding，缺少批量聚合。
- AI 索引与普通 short/default 任务共享 Worker。
- Qdrant 是单实例，无副本和分片故障切换。
- 没有分布式并发信号量、队列上限、熔断和 AI 专项压测基线。

## 3. 目标架构

```text
Web / Mobile
    ↓
Nginx / Traefik
    ↓
Frappe Gateway 多 Worker
    ├─ 权限、公司范围、工具执行、审计
    └─ 短时流式票据
    ↓
AI Stream Gateway / Orchestrator 多副本
    ├─ 异步连接池
    ├─ 并发池、限流、背压、熔断
    └─ Prompt / 模型策略
    ↓
LiteLLM 多副本 + Redis
    ↓
模型供应商

独立 ai-vector 队列 → 批量 Embedding → Qdrant
```

Frappe 仍是权限事实源。高并发流式方案不能让浏览器直接持有内部服务 Token，也不能让 Orchestrator 获得 ERP 超级账号。

## 4. Orchestrator 并发模型

- 使用 FastAPI lifespan 创建共享 `httpx.AsyncClient`。
- 为 LiteLLM、Qdrant 和 Langfuse 配置独立连接池、keep-alive、连接超时和读取超时。
- Chat、structured、embedding、eval 使用独立 `asyncio.Semaphore`，避免互相挤占。
- 设置请求体、上下文、消息数和输出 Token 上限。
- 部署至少两个副本，由负载均衡执行健康检查和优雅摘流。
- 关键运行状态放入 Redis/Frappe/LiteLLM，不依赖单进程内存。
- 关闭时停止接收新请求，等待活动请求到达上限时间后终止。

并发上限必须按模型供应商配额计算。使用 Little 定律估算基础容量：

```text
并发需求 ≈ 峰值请求率 × p95 请求时延
```

最终值必须由压测校准。

## 5. Frappe 与 SSE

生产环境使用 Gunicorn 多 Worker，不使用 `bench serve`。普通同步 API 和 AI SSE 应设置独立路由、超时和连接限制。

大量 SSE 连接会长期占用 WSGI Worker。目标方案：

1. Frappe 完成登录、权限、公司范围、场景和工具上下文校验。
2. Frappe 生成短时、一次性、带 audience 和 nonce 的流式票据。
3. 独立 ASGI Stream Gateway 校验票据后连接 Orchestrator。
4. 票据只包含裁剪后的授权上下文或上下文引用，不包含 ERP 凭据。
5. 票据过期、重放、公司不匹配或场景不匹配必须拒绝。

在该方案上线前，必须为现有 Frappe SSE 设置独立 Worker 池和最大连接数。

## 6. 限流、背压与熔断

使用 Redis 实现分布式控制：

- 每用户、公司、场景的 requests/minute。
- 每模型并发、tokens/minute 和每日预算。
- SSE 最大连接数和单用户连接数。
- 索引队列最大长度和每租户待处理数。
- Live eval 使用独立低优先级配额。

超限返回 HTTP 429、稳定错误码和 `Retry-After`。不能无限等待。

熔断状态：`closed → open → half_open → closed`。429、超时和 5xx 分别计数；权限、Schema 和业务校验错误不计入供应商熔断。熔断后只能切换同 capability 且已验证的降级模型。

## 7. 队列和向量索引

- 新增独立 `ai-vector` 队列和 Worker，不与交易 short/default 队列竞争。
- Worker 聚合 32～128 个 due 商品，批量调用 `/v1/embeddings` 和 Qdrant upsert。
- 每批设置最大字符数、最大商品数和超时，避免单个大商品拖垮整批。
- 失败使用指数退避和随机抖动；达到上限进入失败状态，禁止无限重试。
- 使用内容哈希、模型版本、collection 和 index version 保证幂等。
- 重建任务设置全局锁，避免多个管理员重复启动全量任务。
- 发布新 Embedding 时使用新 collection，验收后原子切换 alias。

## 8. LiteLLM 和供应商层

- LiteLLM 使用多副本和共享 Redis/数据库状态。
- 配置供应商 RPM、TPM、并发、预算、重试和同能力 fallback。
- MyApp 与 LiteLLM 双层限流：MyApp 保护业务公平性，LiteLLM 保护供应商配额。
- 重试只用于幂等、尚未向客户端输出字节的请求。
- SSE 开始输出后不得跨供应商续写，避免重复文本和损坏工具调用。

## 9. Qdrant 容量与高可用

小规模可继续单节点，但必须有 snapshot、恢复演练、磁盘和延迟告警。进入生产高可用后评估：

- collection shard 数和 replication factor。
- 三节点部署及故障域分布。
- 向量维度、点数、payload index、segment 和内存基线。
- 读写并发、索引优化阈值和 compaction 影响。
- collection alias 切换与旧版本保留期。

Qdrant 候选始终回到 Frappe执行权限和实时业务过滤，不能因缓存或副本切换跳过二次校验。

## 10. 缓存

允许缓存：

- LiteLLM 模型列表和健康状态。
- 相同 `embedding_model + normalized_query` 的短 TTL 查询向量。
- 已发布模型策略快照。
- 非敏感固定 Prompt 元数据。

禁止缓存：

- 未包含用户、公司和权限版本的业务查询结果。
- 实时价格、库存、应收应付和正式单据状态。
- 原始供应商密钥、内部服务 Token 和完整敏感上下文。

## 11. 可观测性和 SLO

至少记录：

- 活动请求数、排队时间、拒绝数和 429。
- Chat/SSE/structured/embedding 的 p50、p95、p99。
- SSE 首 Token 时间、连接时长和中断率。
- 各模型成功率、429、超时、5xx、降级和熔断状态。
- RQ 队列长度、最老任务年龄、吞吐和失败数。
- Qdrant 搜索、upsert、点数、segment、磁盘和 snapshot 状态。
- Frappe Worker、MariaDB、Redis 和连接池使用率。

初始 SLO 必须在压测后确定；发布前至少保证错误预算、告警阈值和降级行为有明确负责人。

## 12. 压测矩阵

使用 k6、Locust 或等价工具，测试数据必须是合成数据：

| 场景 | 阶梯 |
|---|---|
| 普通 Chat | 10 / 20 / 50 / 100 并发 |
| SSE | 20 / 50 / 100 / 200 长连接 |
| 商品混合检索 | 20 / 50 / 100 并发 |
| 结构化草稿 | 5 / 10 / 20 并发 |
| 批量 Embedding | 32 / 64 / 128 每批 |
| 索引重建 | 与在线检索并行运行 |

每档至少记录吞吐、p95/p99、首 Token、错误率、Token、成本和资源使用。还需演练 LiteLLM 429、供应商 5xx、Qdrant 停止、Redis 延迟、Langfuse 停止和单副本摘除。

## 13. 发布阶段

### P0：消除单点代码瓶颈

- 共享异步 HTTP Client 和连接池。
- 独立并发池、429 和基础指标。
- 独立 `ai-vector` 队列及批量 Embedding。
- 建立 AI 专项压测脚本和基线。

### P1：横向扩容

- Orchestrator 多副本、优雅摘流。
- Frappe 生产 Gunicorn 和 AI 独立 Worker 配置。
- LiteLLM 共享限流和预算。
- Redis 分布式信号量与熔断。

### P2：高可用流式与向量平台

- 短时票据 + ASGI Stream Gateway。
- Qdrant 多节点、副本、snapshot 和恢复演练。
- 自动扩缩容、容量告警和故障演练。

## 14. 验收标准

- 达到约定并发时，ERP 非 AI 接口不发生明显退化。
- 超限请求快速返回 429，不出现无界排队。
- 单个模型或供应商故障不会拖垮全部场景。
- SSE 断开不会留下失控模型任务或重复审计。
- 索引重建不阻塞在线商品检索。
- 多副本策略、限流和预算结果一致。
- 故障降级不绕过权限、公司范围和工具白名单。
- 容量、SLO、告警和恢复演练均有可复现报告。

