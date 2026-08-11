# 模型配置（Model Configuration）

> 本文档说明 Shorekeeper 的 LLM 模型配置机制：配置来源、优先级、加载链路与切换方法。

## 1. 配置来源（三层优先级）

| 优先级 | 来源 | 位置 | 说明 |
|---|---|---|---|
| 1（最高） | 环境变量 | `backend/.env` 中的 `SHOREKEEPER_RUNTIME_*` | 通过 `load_dotenv` 加载，启动时覆盖 config.yaml |
| 2 | 配置文件 | `~/.shorekeeper/config.yaml` 的 `runtime` 段 | 主配置文件，可在前端「设置 → Runtime」修改 |
| 3（兜底） | 代码默认值 | `backend/app/config/schema.py` 的 `RuntimeConfig` | 默认 `gpt-4`，仅在上述两者都缺失时生效 |

**覆盖规则**：`SHOREKEEPER_RUNTIME_BASE_URL` / `SHOREKEEPER_RUNTIME_API_KEY` / `SHOREKEEPER_RUNTIME_MODEL` 等环境变量会**覆盖** config.yaml 中的同名配置（见 `ConfigService._apply_env_overrides`）。

## 2. 配置字段（`runtime` 段）

```yaml
runtime:
  base_url: https://opencode.ai/zen/go/v1   # OpenAI 兼容端点（留空使用 litellm 默认）
  api_key: sk-xxx                            # API Key
  model: deepseek-v4-flash                   # 模型名
  temperature: 0.7                           # 温度
  max_tokens: 4096                           # 最大 Token 数
```

## 3. 加载链路

```
backend/.env (load_dotenv)
        ↓ SHOREKEEPER_RUNTIME_* 环境变量
~/.shorekeeper/config.yaml (runtime 段)
        ↓
ConfigService._load()          # yaml 加载 + env 覆盖 → AppConfig
        ↓
main.py lifespan               # runtime_config = config.config.runtime
        ↓
NativePythonRuntime(
    default_model=model,       # 默认模型
    llm_extra={base_url, api_key},
)
        ↓
NativeLiteLLMClient.stream_completion()
        ↓ 自动加 openai/ 前缀（有 api_base 且模型名无前缀时）
litellm.acompletion(model="openai/deepseek-v4-flash", api_base=..., api_key=...)
```

## 4. 切换模型

1. 修改 `backend/.env` 中的 `SHOREKEEPER_RUNTIME_*` 或 `~/.shorekeeper/config.yaml` 的 `runtime` 段（**两者需一致**，.env 优先级更高）
2. 重启后端生效

```bash
# 示例：切换到 opencode-go 的 DeepSeek V4 Flash
# backend/.env
SHOREKEEPER_RUNTIME_BASE_URL=https://opencode.ai/zen/go/v1
SHOREKEEPER_RUNTIME_API_KEY=sk-xxx
SHOREKEEPER_RUNTIME_MODEL=deepseek-v4-flash

# ~/.shorekeeper/config.yaml（与上保持一致）
runtime:
  base_url: https://opencode.ai/zen/go/v1
  api_key: sk-xxx
  model: deepseek-v4-flash
```

## 5. 注意事项

| ⚠️ 事项 | 说明 |
|---|---|
| **.env 与 config.yaml 必须同步** | 若 .env 存在 `SHOREKEEPER_RUNTIME_*`，前端「设置 → Runtime」的修改（写入 config.yaml）**重启后会被 .env 覆盖**，看起来"改了不生效" |
| DeepSeek 系模型工具名限制 | DeepSeek V4 Flash（opencode.go）要求工具名匹配 `^[a-zA-Z0-9_-]+$`，不接受 `/`。因此 MCP 工具（命名 `server/tool`）不直接暴露给 LLM，通过 tool_search 发现、tool_executor 执行（渐进式披露设计） |
| `openai/` 前缀 | 有 `base_url` 且模型名不含 `/` 时，NativeLiteLLMClient 自动加 `openai/` 前缀（OpenAI 兼容协议） |
| 测试配置 | `backend/tests/test_llm_execution.py` 的 `llm_config()` fixture 需与生产配置同步，否则测试会打到旧的 API |

## 6. 当前生效配置（2026-08-11）

| 项 | 值 |
|---|---|
| Provider | opencode-go（OpenCode Go 订阅） |
| Base URL | `https://opencode.ai/zen/go/v1` |
| Model | `deepseek-v4-flash` |
| API Key | `backend/.env` + `~/.shorekeeper/config.yaml`（sk- 开头） |
| 配置同步 | 两层一致 ✅ |
