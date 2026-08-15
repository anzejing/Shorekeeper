# 模型页 + 服务商页 改造方案（已确认）

> 状态：**设计已确认**（2025-08-15，用户确认全部决策点）。按 §9 分阶段开发，每阶段按 `docs/ai-development.md` 输出开发准备清单并再次确认后实施。

---

## 1. 功能理解（用户需求复述）

现有 `/models` 页是三 Tab 结构（当前模型 / Provider / models.dev 目录），不符合预期。改造目标：

| # | 需求 | 说明 |
|---|------|------|
| 1 | 拆分为两个页面 | **模型页**（`/models`）+ **服务商页**（`/providers`），侧边栏两个入口 |
| 2 | 模型页 | 最上面显示**当前选择的模型**；下面**按 provider 分组**展示各服务商的模型；每个模型可**启用/隐藏** |
| 3 | 服务商页 | 展示已添加的服务商；可**新增 / 删除 / 隐藏**服务商 |
| 4 | models.dev 目录页删除 | 删除现有"目录" Tab；**同步按钮移到服务商页** |
| 5 | 添加服务商改为**两步向导** | Step1 选择服务商 → Step2 填配置 + 选模型（详见 §3.3） |
| 6 | 只有选中的模型才展示 | 向导中勾选的模型才出现在模型页与聊天页选择器 |
| 7 | 默认端点调研 | models.dev 可提供默认 API 端点（详见 §4） |

---

## 2. 现状梳理与差距分析

| 需求 | 现状 | 差距 |
|------|------|------|
| 模型/服务商分页 | `/models` 单页三 Tab（ModelsView.vue） | 需拆分路由 + 视图 |
| 模型启用/隐藏 | `model_entries.enabled` 字段已存在（默认 1），但**无 UI 无 API** | 需新增切换 API + UI 开关 |
| 服务商启用/隐藏 | `model_providers.enabled` 存在，仅在编辑表单中可改 | 需服务商列表页直接开关 |
| 向导式添加 | `ProviderFormModal.vue` 单步表单（provider_id/name/kind/base_url/api_key/import_models 全量导入） | 需重构为两步向导 + 按需选模型 |
| models.dev 同步 | 目录 Tab 有同步按钮（`/catalog/sync`，ETag 增量） | 移到服务商页顶部 |
| 目录浏览 | 目录 Tab 搜索 + 导入 | 浏览能力并入向导 Step1；目录页删除 |
| 默认端点预填 | `CatalogProvider.api` 已透传（部分有值） | 补 `default_base_url` 计算字段统一预填 |
| 同步重置状态 | `replace_entries` 删除重建，`enabled` 全部重置为 true | 同步时应**保留用户隐藏状态** |

**现有基础（可复用）**：`ModelSelector.vue` 已过滤 `provider.enabled && model.enabled`；`get_current` 已校验 `entry.enabled`；`resolve_model` 未校验 `entry.enabled`（需补）；catalog 查询接口齐备。

---

## 3. 目标设计

### 3.1 页面结构（决策点 A）

```
侧边栏: 模型 (/models) · 服务商 (/providers)  ← 替换原单一"模型"入口

/models（模型页）
├─ 顶部卡片: 全局当前模型（Chip + ModelSelector + 清空 + 测试连接）
└─ 按 provider 分组: 每个 provider 一个分组
   └─ 模型行: 仅展示 **已启用** 的模型（显示名 / litellm_name / tool_call 标记 / 当前标记 / 隐藏开关）
      （隐藏的模型**不显示**；重新启用须在服务商页 → 编辑该 provider → 向导 Step2 重新勾选）

/providers（服务商页）
├─ 顶部卡片: models.dev 目录状态（数据日期/计数）+ 同步目录按钮  ← 原目录 Tab 迁移
└─ 服务商卡片列表: 名称 / kind / base_url / api_key 状态 / 模型数
   ├─ 启用开关（隐藏服务商）· 同步模型 · 编辑 · 删除
   └─ 展开: 模型列表（可开关）+ 手动添加模型
```

> **决策点 A-1（已确认）**：隐藏的模型在模型页**不显示**；需要在服务商页编辑对应 provider，在向导 Step2 重新勾选以启用。
>
> **决策点 A-2（已确认）**：目录独立页删除，浏览能力并入添加向导。

### 3.2 服务商页同步按钮

- 顶部展示目录状态（复用现有 `/catalog/status` + `/catalog/sync`）
- 未同步时提示"添加服务商前请先同步目录（用于搜索与模型预填）"

### 3.3 添加服务商向导（决策点 B）

模态框（size=lg，两步），替代现有 ProviderFormModal：

```
Step 1  选择服务商
├─ 搜索框（调 /catalog/providers?search=，从已同步的 models.dev 缓存查询）
├─ 搜索结果列表（名称 / kind / 模型数 / 默认端点），点击选中
└─ 或切换"自定义输入"：手动输入名称（不关联目录）
   （选中服务商 → 预填 kind + default_base_url + 目录模型列表）

Step 2  配置
├─ 显示名称（自动带出，可改）
├─ Base URL（预填目录 api 字段或 kind 官方端点，可改）
├─ API Key
├─ 获取模型地址 models_url（默认 = base_url + "/models"，可改；新增字段落库）
│   └─ [手动获取模型] 按钮 → 调该地址拉取真实模型列表，刷新下方列表
├─ 模型列表（默认展示该服务商在 models.dev 目录中的模型，带 [全选]）
│   └─ 勾选的模型才会在创建后写入 model_entries（enabled=true）
└─ 走代理开关 / 测试连接（保留现有能力）
```

> **决策点 B-1（已确认）**：向导用模态框两步流。
> **决策点 B-2（已确认）**：编辑服务商复用向导（Step2 预填现有模型勾选状态 = enabled 集合，可增删选）。

### 3.4 模型"启用/隐藏"语义（已确认）

- `enabled=false` = 隐藏：
  - **模型页不显示**（分组列表仅渲染 enabled=true）
  - 不出现在聊天页选择器（ModelSelector 已过滤）
  - `resolve_model` 拒绝用于新发送（需补校验）
  - 已挂起 Run 不受影响（RunSnapshot.metadata 持久化，resume 用原 model 参数）
  - **重新启用**：服务商页 → 编辑该 provider → 向导 Step2 重新勾选（DB 记录保留，不删除）

> 注意：隐藏 ≠ 删除。编辑向导保存时提交的 `model_ids` 语义为"启用集合"：未列出的现有模型置 `enabled=false`（隐藏），**不删除**。

### 3.5 models.dev 目录页删除

- 删除 ModelsView 中 catalog Tab 及 `store.catalogProviders` 相关 UI（store/API 保留，供向导使用）
- 目录同步、搜索、单服务商模型查询接口**全部保留**（向导依赖）

---

## 4. 默认 API 端点调研结论（用户问题）

实测 `https://models.dev/api.json`（185 个服务商，2025-08-15 拉取）：

| 情况 | 数量 | 示例 |
|------|------|------|
| 有 `api` 字段 | 159 | deepseek→`https://api.deepseek.com`、openrouter→`https://openrouter.ai/api/v1`、siliconflow→`https://api.siliconflow.com/v1`、zhipu→`https://open.bigmodel.cn/api/paas/v4` |
| 无 `api` 字段 | 26 | openai、anthropic、google、groq、mistral、xai 等 |
| 兜底（按 kind 官方端点） | — | openai→`https://api.openai.com/v1`、anthropic→`https://api.anthropic.com`、gemini→`https://generativelanguage.googleapis.com` |

**结论：可以获取默认端点。** 实现方式：后端在 catalog 查询时计算 `default_base_url`（优先 `api` 字段，兜底 kind 官方端点），向导 Step2 预填且可改。

---

## 5. 数据流（改造后）

### 5.1 添加服务商（向导）

```
用户 Step1 选择/输入服务商
  → GET /api/models/catalog/providers?search= （已同步缓存）
  → 选中 → 本地暂存 kind / default_base_url / 目录模型列表
用户 Step2 填 base_url / api_key / models_url → 勾选模型
  → POST /api/models/providers { …, models_url, model_ids: [勾选模型] }
  → ModelConfigService.create_provider → SQLite model_providers + model_entries（仅选中）
  → 刷新服务商页 / 模型页
```

### 5.2 手动获取模型（向导内）

```
用户点 [手动获取模型]（models_url 已填）
  → POST /api/models/providers/preview { base_url, models_url, kind, api_key }  （仅预览，不落库）
  → sync_provider.fetch_provider_models 适配三格式 → 返回模型列表 → 刷新勾选列表
```

> **决策点 C（已确认）**：新增 preview 接口（不落库，仅返回列表）。向导 Step2 的"手动获取模型"与"测试连接"均复用 preview（拉 /models 成功即连通）。

### 5.3 模型启用/隐藏

```
模型页隐藏开关 → PUT /api/models/providers/{pid}/models/{mid} { enabled:false }
  → ModelConfigService.set_model_enabled → SQLite model_entries.enabled
  → 若关闭的是当前模型 → 清空 current（复用 _clear_current_if_matches）
  → 模型页立即不显示该模型

服务商页编辑向导保存 → PUT /api/models/providers/{pid} { model_ids: [启用集合] }
  → 更新 models_url 等字段 + 同步 model_entries：
     model_ids 中的现有条目 → enabled=true；未列出 → enabled=false（隐藏，不删除）
     model_ids 中的新 id（手动获取后新勾选）→ 插入新条目
```

### 5.4 发送聊天（禁用模型校验）

```
聊天发送 → chat.py → resolve_model（新增 entry.enabled 校验，禁用则 422）
  → 正常路径不变（metadata 持久化 / resume 恢复）
```

### 5.5 服务商同步（保留隐藏状态）

```
服务商页 [同步] → POST /api/models/providers/{id}/sync
  → fetch_provider_models（models_url 优先，其次 base_url + /models）
  → replace_entries 前读取旧 enabled 状态并保留（决策点 D 已确认）
  → 刷新模型列表
```

---

## 6. 影响模块

| 层 | 文件 | 变更 |
|----|------|------|
| UI | `views/ModelsView.vue` | 重写：当前模型 + 按 provider 分组（仅已启用模型）+ 隐藏开关 |
| UI | `views/ProvidersView.vue` | **新增**：服务商列表 + 开关 + 同步按钮 + 删除/编辑 |
| UI | `components/AddProviderWizard.vue` | **新增**：两步向导（替代 ProviderFormModal，新增/编辑复用） |
| UI | `components/ProviderFormModal.vue` | 删除（由 AddProviderWizard 取代，决策点 B-2 已确认） |
| UI | `components/AppSidebar.vue` | 导航增加"服务商"入口 |
| UI | `stores/models.ts` / `api/models.ts` | 新增 toggleModelEnabled / preview / models_url / model_ids 支持 |
| API | `backend/app/api/models.py` | 新增模型启用切换、preview、catalog default_base_url；ProviderRequest/Update 增字段 |
| 业务 | `models_config/service.py` | create 支持 model_ids；set_model_enabled；resolve 校验 enabled；sync 保留 enabled |
| 业务 | `models_config/schema.py` | ModelProvider 增 `models_url` 字段 |
| 业务 | `models_config/store.py` | 迁移新增列 `models_url`；replace_entries 保留 enabled |
| 业务 | `models_config/sync_provider.py` | 支持自定义 models_url；导出 preview 用函数 |
| 文档 | `docs/models-management.md` | 同步更新 |

---

## 7. API 接口变更

### 新增

**① 切换模型启用状态**
- **路径**：`PUT /api/models/providers/{provider_id}/models/{model_id}`
- **请求**：`{ "enabled": boolean }`
- **响应**：`ModelEntry`
- **错误**：404 provider/模型不存在；422 参数错误

**② 预览模型列表（向导"手动获取模型"，不落库）**
- **路径**：`POST /api/models/providers/preview`
- **请求**：
```typescript
interface PreviewRequest {
  kind: ProviderKind
  base_url: string
  models_url?: string   // 缺省 = base_url + /models
  api_key?: string
}
```
- **响应**：
```typescript
interface PreviewResponse {
  models: { id: string; display_name?: string }[]
}
```
- **错误**：422 端点不可用/格式无法解析

**③ 目录服务商默认端点**
- **路径**：`GET /api/models/catalog/providers`（改造现有接口）
- **响应**：`CatalogProvider` 增加 `default_base_url: string`（api 字段优先，兜底 kind 官方端点）

### 修改

**④ `POST /api/models/providers`**：`ProviderRequest` 增加
```typescript
models_url?: string     // 获取模型地址，可空
model_ids?: string[]    // 要导入并启用的模型 id 列表（缺省：不导入）
```
> **决策点 E（已确认）**：删除 `import_models` 布尔字段，由 `model_ids` 取代。

**⑤ `PUT /api/models/providers/{id}`**：`ProviderUpdateRequest` 增加 `models_url` 与 `model_ids`（编辑时语义为"启用集合"：未列出的现有模型置隐藏，不删除；新 id 插入并启用）

**⑥ `POST /api/models/providers/{id}/sync`**：内部改用 `models_url`（优先）→ `base_url + /models`（兜底）

---

## 8. 数据模型变更

```typescript
// ModelProvider 增加字段（SQLite 迁移：_ensure_column）
models_url: string   // 获取模型地址（/models 端点），空 = 按 base_url 推导

// model_entries.enabled 已有，无需迁移
```

---

## 9. 分阶段实施（每 PR < 300 行，一次只做一件事）

| 阶段 | 内容 | 说明 |
|------|------|------|
| **PR1 后端基础** | schema 增 models_url + 迁移；create 支持 model_ids；set_model_enabled；resolve 校验 enabled；sync 保留 enabled；catalog default_base_url；preview 接口 | 后端先行，前端契约不变 |
| **PR2 模型页** | ModelsView 重写（当前模型 + 分组仅已启用模型 + 隐藏开关） | 依赖 PR1 的模型开关 API |
| **PR3 服务商页** | ProvidersView 新建；导航改造；同步按钮迁移；目录 Tab 删除 | 依赖 PR1 |
| **PR4 添加向导** | AddProviderWizard 两步流；替换 ProviderFormModal；编辑复用（B-2 已确认） | 依赖 PR1/PR3 |

---

## 10. 风险与边界

| 风险 | 说明 | 处理策略 |
|------|------|----------|
| 同步重置隐藏状态 | `replace_entries` 删除重建会把 enabled 重置为 true | replace 前读取旧 enabled 映射并保留（决策点 D 已确认） |
| 禁用当前模型 | 关闭的模型恰是当前模型 | set_model_enabled 复用 `_clear_current_if_matches` 清空当前模型 |
| resolve 未校验 enabled | 禁用模型仍可通过 API 直接指定发送 | resolve_model 补 `entry.enabled` 校验；已挂起 Run 不受影响（metadata 持久化） |
| 未同步目录就添加服务商 | 向导 Step1 无搜索结果 | 服务商页顶部强提示 + 向导空态引导先同步 |
| 自定义服务商无目录模型 | Step2 列表为空 | 靠"手动获取模型"或手动添加；空列表允许直接创建 |
| models_url 自定义 | 与 base_url 不同源的 /models 地址 | 预览与同步均优先用 models_url；留空回退 base_url 推导 |
| api_key 掩码回写 | 编辑时 "***" 不覆盖（已有保护） | 向导编辑流程沿用 MASK 保护 |
| 向导全选大列表 | openrouter 351 个模型全选 | 全选默认开启；性能可接受（单次批量 insert） |
| catalog 缓存损坏/缺失 | 向导搜索无数据 | load_catalog_file 返回 None → 提示先同步 |

---

## 11. 测试方案

### 单元测试（backend）
- `set_model_enabled`：开/关、关闭当前模型清空 current、404
- `create_provider`：model_ids 过滤导入；无 model_ids 不导入；models_url 落库
- `preview`：三格式解析（openai/anthropic/gemini mock）；URL 推导（models_url 优先）
- `sync_provider_models`：保留既有 enabled 状态；models_url 优先
- `catalog default_base_url`：api 字段优先 / kind 兜底

### 集成测试
- 禁用模型 → 聊天发送 422；恢复启用 → 可发送
- 关闭当前模型 → current 清空 → 聊天提示选择模型

### 端到端（Playwright）
- 服务商页：同步目录 → 添加服务商（选择 openrouter）→ 勾选 2 个模型 → 创建
- 模型页：分组展示、开关模型、切换当前模型
- 聊天页：选择器只出现已启用模型；发送成功

### Manual
- 真实 deepseek provider 全链路（api 字段预填端点 → 手动获取模型 → 多选 → 聊天）
- 自定义 provider（无目录关联）流程
- 服务商隐藏后聊天选择器不可见

---

## 12. 决策点确认记录

| 决策点 | 内容 | 结论 |
|--------|------|------|
| A-1 | 隐藏的模型在模型页不显示；重新启用须在服务商页编辑 provider，向导 Step2 重新勾选 | ✅ 已确认（用户） |
| A-2 | 目录独立页删除，浏览能力并入添加向导 | ✅ 已确认（用户） |
| B-1 | 向导用模态框两步流 | ✅ 已确认（用户） |
| B-2 | 编辑服务商复用向导 | ✅ 已确认（用户） |
| C | 新增 preview 接口（不落库） | ✅ 已确认（用户） |
| D | 同步模型时保留用户隐藏状态 | ✅ 已确认（用户） |
| E | `import_models` 由 `model_ids` 取代 | ✅ 已确认（用户） |

> 全部决策点已确认。按 §9 分阶段开发，每阶段按 ai-development.md 输出完整开发准备清单。
