# 代理配置（Proxy Config）

> 本文档定义"代理配置"功能的完整设计：统一代理设置 + 失败自动直连回退，
> 覆盖 LLM API、models.dev 目录同步、provider /models 端点同步、web_search 工具。

## 1. 背景与目标

网络原因（如中国大陆访问海外 API 不稳定），需要为外网请求提供代理支持：

| 目标 | 说明 |
|---|---|
| 统一代理配置 | 设置页新增「代理」分组：全局开关、代理地址、失败回退开关、超时 |
| LLM API 按 Provider 走代理 | Provider 表单新增「走代理」开关（`use_proxy`），默认关闭，国内直连 Provider 不受影响 |
| models.dev 默认走代理 | 目录同步跟随全局代理开关（`enabled=true` 时走代理） |
| provider /models 同步 | 跟随 Provider 的 `use_proxy`（与 LLM 请求语义一致） |
| web_search 工具 | 跟随全局代理开关 |
| 失败自动直连 | 连接类错误（连接失败/超时）自动回退直连重试一次；4xx/5xx 业务错误不重试 |

**用户已确认的决策**（2026-08-15）：

| # | 决策 |
|---|---|
| 1 | 开关层级：全局 `proxy.enabled` 控制 models.dev 等基础设施请求；LLM 请求由 Provider 的 `use_proxy` 决定（默认关） |
| 2 | fallback 边界：仅连接类错误回退直连；流式对话只重试首包之前的失败（避免重复输出） |
| 3 | provider /models 同步跟随 Provider 的 `use_proxy` |
| 4 | 仅支持 http/https 代理，不支持 socks5（首版） |
| 5 | web_search 工具也走代理（跟随全局开关） |

## 2. 关键实现验证（litellm 代理实测）

litellm 1.96.2 **不支持** `proxy` 参数，环境变量 `HTTP(S)_PROXY` 也不生效
（httpx client 使用自定义 transport + `trust_env=False`，实测 2 次均直连）。

**可行方案**（实测通过）：litellm 的 `acompletion(client=...)` 接受预建
`AsyncOpenAI` 客户端；构造时传入带 `httpx.AsyncClient(proxy=...)` 的 http_client，
请求即走代理（实测无效代理被正确拦截，返回连接错误）。

```
# 走代理
http_client = httpx.AsyncClient(proxy="http://127.0.0.1:7890")
client = AsyncOpenAI(api_key, base_url, http_client=http_client)
acompletion(model, messages, client=client, stream=True)
```

aiohttp 侧（models.dev / /models / web_search）原生支持 `session.get(url, proxy=...)`。

## 3. 配置结构

### 3.1 config.yaml（新增 `proxy` 段）

```yaml
proxy:
  enabled: true                    # 全局开关（models.dev / web_search 跟随）
  url: "http://127.0.0.1:7890"    # 代理地址（仅 http/https）
  fallback_direct: true            # 代理失败自动直连重试
  timeout: 10                      # 代理连接超时（秒）
```

- `url` 标记为 secret（可含用户名密码认证，如 `http://user:pass@host:port`），前端掩码显示
- 设置页 ConfigView 自动渲染（GROUP_META 新增「代理」分组）

### 3.2 Provider 新增 `use_proxy` 字段

```python
class ModelProvider:
    ...
    use_proxy: bool = False   # LLM 请求是否走代理
```

- 存入 DB `model_providers.use_proxy`（INTEGER，默认 0）
- 旧库迁移：`PRAGMA table_info` 检查列不存在则 `ALTER TABLE ADD COLUMN`

## 4. 数据流

### 4.1 LLM 请求走代理

```
Provider 表单「走代理」开关 → DB model_providers.use_proxy
  ↓
发送消息 → POST /api/chat/stream → chat.py resolve_model()
  → llm_extra = {api_key, base_url, use_proxy: true}
  → RunSnapshot.metadata 持久化（跨 run 恢复保持）
  ↓
native_litellm_client.stream_completion():
  use_proxy=true → 构造 AsyncOpenAI(httpx proxy client) → acompletion(client=...)
  → 连接类错误 & fallback_direct → 直连 client 重试一次
```

### 4.2 models.dev / /models / web_search

```
设置页「代理」分组 → config.yaml proxy 段
  ↓
fetch_catalog / fetch_provider_models / web_search:
  proxy.enabled=true → aiohttp session.get(url, proxy=proxy.url)
  → 连接类错误 & fallback_direct → 直连重试一次
```

## 5. 模块划分与影响范围

```
UI (Vue)
  ├─ ProviderFormModal.vue   加「走代理」KunSwitch（use_proxy）
  └─ ConfigView.vue          代理分组自动渲染（meta.py 驱动，无代码改动）
API
  ├─ api/models.py           ProviderRequest/ProviderUpdateRequest 增加 use_proxy
Config
  ├─ schema.py               新增 ProxyConfig
  ├─ meta.py                 GROUP_META 增加 proxy（"代理"）
  └─ service.py              （无需改动，自动序列化新分组）
Net（新增，app/net/proxy.py）
  ├─ get_proxy_url(config_service) -> str | None    全局开关开启时返回 url
  ├─ get_proxy_timeout(config_service) -> float
  └─ is_conn_error(e) -> bool                       连接类错误判定（aiohttp/httpx/超时）
ModelConfig
  ├─ schema.py               ModelProvider 增加 use_proxy
  ├─ store.py                model_providers 表加列 + 旧库 ALTER 迁移
  ├─ service.py              resolve_model 返回 use_proxy；test_connection 走代理
  ├─ sync_models_dev.py      fetch_catalog 走代理 + 失败直连
  └─ sync_provider.py        _get_json 走代理（provider.use_proxy）+ 失败直连
Runtime Adapter
  └─ native_litellm_client.py   use_proxy → 预建 client；连接错误回退直连
Tools
  └─ web_search.py           SearchProvider 增加 proxy 参数（跟随全局开关）
```

## 6. fallback 机制（错误分类）

| 错误类型 | 是否回退直连 | 说明 |
|---|---|---|
| 连接失败 / 拒绝 / DNS 失败 | ✅ | `ClientConnectorError` / `httpx.ConnectError` 等 |
| 连接超时 / 读取超时 | ✅ | `asyncio.TimeoutError` / `httpx.ConnectTimeout` |
| TLS 错误 | ✅ | `ClientSSLError` / `ssl.SSLError` |
| 代理本身不可达 | ✅ | `ClientProxyConnectionError` |
| HTTP 4xx / 5xx | ❌ | API 端业务错误，直连无意义 |
| 认证错误 | ❌ | 401/403 是 API 端响应 |

**流式对话特殊处理**：仅当流**尚未产出任何事件**时发生连接类错误才回退直连重试
（首包前失败，无重复输出风险）；流中失败不重试，正常抛错。

## 7. 风险与边界

| 风险 | 处理 |
|---|---|
| litellm 传 client 在流式 + 工具调用场景兼容性 | 实测非流式通过；流式 + tools 需真实验证（含 fallback 重试） |
| 代理 URL 含认证信息 | `url` 标记 secret，前端掩码；不写入日志 |
| 旧库无 use_proxy 列 | PRAGMA 检查 + ALTER TABLE 迁移（幂等） |
| 代理失败时重复输出 | 流式仅首包前回退；已输出内容不重试 |
| fallback 放大延迟 | 每次连接失败额外一次直连尝试（最多 2 次请求，可接受） |
| Run 挂起恢复期间改代理配置 | llm_extra 持久化 use_proxy，恢复时用当时的设置；代理配置读取为运行时实时读（config.yaml），全局开关变化即时生效 |
| web_search 多服务商 × 代理/直连 | 每个服务商独立 try：先按代理设置请求，失败按 fallback 直连，再失败回退下一个服务商 |

## 8. 测试策略

### 单元测试
- ProxyConfig 解析（默认值 / 完整配置 / secret 掩码）
- `is_conn_error` 错误分类（aiohttp / httpx / asyncio 各类异常）
- fetch_catalog：代理参数传递（mock aiohttp）；代理失败 → 直连重试成功；代理失败且 fallback 关闭 → 抛错
- fetch_provider_models：use_proxy=true 传 proxy；use_proxy=false 不传
- resolve_model：llm_extra 含 use_proxy

### 集成测试
- LLM 测试连接走代理（mock httpx transport）：代理生效；连接错误 → 直连成功
- 流式 chat：use_proxy=true 的 provider 首包前失败 → 直连重试成功；流中失败 → 不重试

### 端到端（真实）
- 本地代理 127.0.0.1:7890：models.dev 同步、LLM 聊天流、provider /models 同步、web_search 全链路
- 关闭代理开关：全部直连

## 9. 文档同步

- `docs/product-spec.md`：配置分组表加「代理」；新增 5.7 代理配置小节
- `docs/progress.md`：开发记录追加
- `README.md`：配置示例更新
