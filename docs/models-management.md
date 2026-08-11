# 模型管理（Model Management）

> 本文档定义"模型管理"功能的完整设计：多 Provider + 多 Model 配置、models.dev 目录同步、
> provider `/models` 端点覆盖、全局模型切换、会话热切换、以及为计量页面预留的数据基础。

## 1. 背景与目标

旧机制（见 `model-config.md` 历史版）只有**单个全局模型**：`config.yaml` 的 `runtime` 段 + `.env`
的 `SHOREKEEPER_RUNTIME_*` 覆盖，改模型必须改文件 + 重启。本功能将其替换为：

| 目标 | 说明 |
|---|---|
| 多 Provider | openai（官方）/ openai_like（兼容端点）/ anthropic / gemini 四种类型 |
| 多 Model | 每个 provider 下挂多个模型，可增删改 |
| models.dev 目录 | 同步公开模型元数据（能力/上下文/定价），显示数据日期，手动同步（ETag 增量） |
| /models 覆盖 | 有 `/models` 端点的 provider 可从其服务器拉取真实模型列表，覆盖 models.dev 不一致数据 |
| 全局切换 | 全局"当前模型"存 DB，聊天页输入框左上方二级选择器（provider → model）切换 |
| 热切换 | 对话多轮后切换模型可继续对话；Run 挂起恢复时保持原模型不串 |
| 计量准备 | 模型元数据保留 cost 单价，Run 记录 model_id + usage，供后续计量页面使用 |
| 配置存 DB | provider / api_key / 当前模型全部存入 SQLite，不再依赖 config.yaml runtime 段 |

## 2. 关键设计决策（用户已确认）

| 决策 | 结论 |
|---|---|
| 设置页组织 | 侧边栏新增独立入口「模型」（`/models`），与「配置」（`/config`）并列；模型页内 Tab：模型 / Provider / 目录 |
| models.dev 数据 | 启动/手动同步 + 显示数据日期 + 同步按钮（ETag 判断 304 未变化） |
| api_key 存储 | 存入 SQLite（自托管信任边界，与旧 config.yaml 明文等价；响应/日志一律掩码） |
| 旧 runtime 段 | 直接删除，不再保底；`.env` 的 `SHOREKEEPER_RUNTIME_*` 覆盖逻辑整体移除；启动时无 provider 由前端引导配置 |
| 当前模型可空 | 当前模型**可为空也可删除**；为空时发送聊天 → 前端提示"请先选择模型" |
| 测试连接 | Provider 表单 + 模型选择器均支持"测试"：可选择或输入一个模型，点击按钮发最小请求验证 |
| 元数据覆盖 | provider `/models` 端点返回的模型列表（增删）覆盖 models.dev；models.dev 详细元数据（cost/context/tool_call）保留合并；缺失字段标记未知 |
| 聊天模型选择器 | 输入框左上方工具条，二级选择（provider → model） |

## 3. 数据流

### 3.1 Provider / Model 配置

```
用户 → ModelsView(Provider Tab) → POST/PUT /api/models/providers → ModelConfigService → SQLite(model_providers)
```

### 3.2 models.dev 目录同步

```
用户点「同步」→ POST /api/models/catalog/sync → 后台拉取 https://models.dev/api.json
  → 带上次 ETag（304 未变化 → 返回 unchanged）
  → 解析 provider + models 元数据 → 写入 model_catalog_meta / model_entries（source=catalog）
```

### 3.3 provider /models 端点同步

```
用户点「同步」→ POST /api/models/providers/{id}/sync
  → 按 kind 调用端点（openai 系 GET {base_url}/models；anthropic/gemini 各自格式）
  → 适配层统一为模型列表 → 覆盖合并 model_entries（meta_source=provider_api）
  → models.dev 详细元数据按 model_id 回填
```

### 3.4 热切换对话

```
用户切换模型 → PUT /api/models/current → SQLite(app_settings.current_model)
   ↓
发送消息 → POST /api/chat/stream { message, session_id, model? }
   ↓
chat.py：model 缺省取全局当前模型
   → RunRequest.metadata = { provider_id, model_id, litellm_name, llm_extra:{base_url,api_key}, temperature, max_tokens }
   ↓
NativePythonRuntime.create_run → RunSnapshot.metadata 持久化（model 随 run 落库）
   ↓
execute / resume 均从 RunSnapshot.metadata 读取 model + llm_extra（优先于全局默认）
   ↓
run_loop → LiteLLMCompletionRequest(model=litellm_name) → litellm（前缀已含，不再自动加 openai/）
   ↓
UI 展示回复 + 模型标记
```

### 3.5 计量准备

```
Run 完成 → RunSnapshot.metadata.model_id + Usage(tokens/cost)
  + model_entries.metadata.cost（单价）
  → 后续计量页面按 usage × cost 计算费用
```

## 4. 模块划分与影响范围

```
UI (Vue)
  ├─ ModelsView.vue（模型/Provider/目录 三 Tab）
  ├─ ChatInput 模型选择器（二级选择）
  ├─ stores/models.ts + api/models.ts
  └─ stores/chat.ts（发送携带 model）
API
  ├─ api/models.py（新增，REST 接口）
  └─ api/chat.py（ChatRequest 增加 model 字段）
ModelConfig 模块（新增，app/models_config/）
  ├─ schema.py      Pydantic 模型
  ├─ store.py       SQLite 存储（4 张新表）
  ├─ service.py     CRUD + 全局当前模型 + 编排
  ├─ sync_models_dev.py   models.dev 拉取/ETag/解析
  ├─ sync_provider.py     /models 端点调用 + 三格式适配
  └─ litellm_mapping.py   kind → litellm 前缀映射
Runtime Adapter
  ├─ runtime.py     从 metadata 读 model/llm_extra（create/execute/resume）
  └─ native_litellm_client.py  移除自动 openai/ 前缀逻辑
Config
  ├─ schema.py      删除 RuntimeConfig
  └─ service.py     移除 env 覆盖逻辑
```

## 5. 数据库表（新增 4 张）

```sql
CREATE TABLE IF NOT EXISTS model_providers (
    provider_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('openai','openai_like','anthropic','gemini')),
    base_url TEXT NOT NULL DEFAULT '',
    api_key TEXT NOT NULL DEFAULT '',        -- secret，响应掩码
    enabled INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'custom',   -- catalog | custom
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_entries (
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    litellm_name TEXT NOT NULL,              -- 含前缀，如 openai_like/deepseek-v4-flash
    enabled INTEGER NOT NULL DEFAULT 1,
    meta_source TEXT NOT NULL DEFAULT 'custom',  -- models_dev | provider_api | custom
    metadata TEXT NOT NULL DEFAULT '{}',     -- models.dev 元数据透传（含 cost 单价）
    PRIMARY KEY (provider_id, model_id),
    FOREIGN KEY (provider_id) REFERENCES model_providers(provider_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,                    -- current_model
    value TEXT NOT NULL                      -- JSON: {provider_id, model_id}
);

CREATE TABLE IF NOT EXISTS model_catalog_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    etag TEXT NOT NULL DEFAULT '',
    data_date TEXT NOT NULL DEFAULT '',      -- models.dev last_updated 最大值
    synced_at TEXT NOT NULL DEFAULT '',
    provider_count INTEGER NOT NULL DEFAULT 0,
    model_count INTEGER NOT NULL DEFAULT 0
);
```

## 6. API 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/models/providers` | provider 列表（api_key 掩码） |
| POST | `/api/models/providers` | 新增 provider |
| PUT | `/api/models/providers/{provider_id}` | 更新 provider |
| DELETE | `/api/models/providers/{provider_id}` | 删除（级联删模型；当前模型自动清空） |
| POST | `/api/models/providers/{provider_id}/sync` | 调 /models 端点同步模型 |
| POST | `/api/models/providers/{provider_id}/test` | 测试连接（body: {model_id?} 可选） |
| GET | `/api/models/providers/{provider_id}/models` | 模型列表（含合并元数据） |
| GET | `/api/models/catalog/status` | 目录状态（数据日期/etag/计数） |
| POST | `/api/models/catalog/sync` | 手动同步 models.dev |
| GET | `/api/models/current` | 全局当前模型（可能为 null） |
| PUT | `/api/models/current` | 设置全局当前模型 |
| POST | `/api/chat/stream` | ChatRequest 增加可选 `model` |

### litellm_name 生成规则（kind → 前缀）

| kind | 前缀 | base_url 处理 |
|---|---|---|
| openai | `openai/{model}` | 留空用官方；有值传 api_base |
| openai_like | `openai_like/{model}` | 必填 api_base |
| anthropic | `anthropic/{model}` | 留空用官方 |
| gemini | `gemini/{model}` | 留空用官方 |

## 7. 风险与边界

| 风险 | 处理 |
|---|---|
| api_key 明文存 DB | 接受（自托管信任边界）；响应/日志掩码 |
| models.dev 3.6MB 同步 | 后台任务 + 进行中标记；ETag 304 秒回 |
| /models 三格式差异 | 适配层按 kind 转换；解析失败返回明确错误 |
| /models 不可用 | 降级：models.dev 数据 + 手动添加模型 |
| Run 挂起期间切模型 | RunSnapshot.metadata 持久化 model+llm_extra，resume 恢复 |
| 当前模型为空/被删 | 允许；聊天发送时前端提示"请先选择模型" |
| 并发同步 | provider 级同步锁 + 进行中标记 |
| 模型 tool_call=false | UI 提示"可能不支持工具调用" |
| 旧 runtime 迁移 | config.yaml runtime 段忽略；无 provider 前端引导 |

## 8. 测试策略

- **单元**：litellm_name 生成（4 kind）；provider store CRUD + 掩码 + 级联删除；/models 三格式解析（mock）；models.dev 同步 + ETag 304；覆盖合并规则
- **集成**：热切换（Run A 用模型1 挂起 → 切模型2 → resume 仍用模型1）；ChatRequest 带/不带 model；删除当前模型清空
- **Playwright**：模型页添加 provider → 同步 → 元数据显示；聊天页二级切换 → 发送 → SSE model 字段正确
- **Manual**：真实 opencode provider 全链路；models.dev 手动同步 + 数据日期显示

## 9. 文档同步

- `docs/product-spec.md`：配置管理功能域更新，新增模型管理功能
- `docs/progress.md`：开发记录追加
- `docs/model-config.md`：标注旧机制废弃，指向本文档
- `README.md`：配置示例更新
