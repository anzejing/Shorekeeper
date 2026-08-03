# Skill 模块开发准备清单（v3）

## 1. 功能理解

Skill 模块管理 AI 助手的能力。每个 Skill 是一个 **SKILL.md 文件**（Markdown + YAML frontmatter），描述一组 Prompt 指令。

核心设计：**文件系统存内容，数据库存状态。**

- SKILL.md 文件：name、description、system_prompt、instructions
- SQLite：enabled、config（用户覆盖）

Tool 注册由独立的 **ToolRegistry** 负责，Skill 只管 Prompt。

## 2. 模块边界

```
~/.shorekeeper/skills/              ← Skill 文件（安装/手动放置）
  ├── memory/SKILL.md
  ├── deploy/SKILL.md + deploy.sh
  └── .skills.json                  ← 安装清单（兼容 skills.sh）

SkillLoader                         ← 启动时扫描目录，解析 SKILL.md
  ↓
SkillStore (SQLite)                 ← 存储状态（enabled, config）
  ↓
SkillService                        ← 合并文件内容 + 数据库状态
  ↓
Runtime                             ← 获取 system_prompts

ToolRegistry（独立）                ← Tool 注册，与 Skill 无关
```

## 3. 数据流

### 3.1 Skill 加载（启动时）

```
~/.shorekeeper/skills/*/SKILL.md
        ↓
SkillLoader.scan()
        ↓
解析 YAML frontmatter → name, description, system_prompt
        ↓
与 SkillStore 同步：
  - 新 Skill → 自动创建记录（enabled=true）
  - 已存在 → 更新文件内容字段
  - 已删除 → 标记为 removed
```

### 3.2 Skill 安装

```
方式1：npx skills add owner/repo → SKILL.md 写入 ~/.shorekeeper/skills/
方式2：手动放置 SKILL.md 文件
方式3：API 上传 SKILL.md
        ↓
SkillLoader.scan() → 发现新 Skill → 同步到 Store
```

### 3.3 Prompt 注入

```
用户消息 → Assistant Service → SkillService.get_system_prompts()
                                      ↓
SkillStore 查询 enabled Skills
                                      ↓
读取每个 Skill 的 SKILL.md → 提取 system_prompt
                                      ↓
拼接 → 注入到系统消息 → Runtime
```

### 3.4 Skill 管理

```
用户操作 → API → SkillService → SkillStore 更新 enabled/config
```

## 4. API 接口定义

### 4.1 Skill 管理（HTTP API）

**接口1：获取 Skill 列表**
- **路径**：`GET /api/skills`
- **查询参数**：`enabled: bool | None`
- **响应**：`200 OK`
```python
class SkillResponse(BaseModel):
    name: str                    # 唯一标识，来自 SKILL.md
    description: str             # 来自 SKILL.md
    category: str                # 来自 SKILL.md frontmatter
    enabled: bool                # 来自数据库
    system_prompt: str           # 来自 SKILL.md
    path: str                    # 文件路径
    has_scripts: bool            # 是否附带脚本文件
    config: dict                 # 来自数据库
    installed_at: datetime | None

class SkillListResponse(BaseModel):
    skills: list[SkillResponse]
    total: int
```

**接口2：获取 Skill 详情**
- **路径**：`GET /api/skills/{name}`
- **响应**：`200 OK` → `SkillResponse`

**接口3：更新 Skill 状态**
- **路径**：`PATCH /api/skills/{name}`
- **请求**：
```python
class UpdateSkillRequest(BaseModel):
    enabled: bool | None = None
    config: dict | None = None
```
- **响应**：`200 OK` → `SkillResponse`

**接口4：安装 Skill（上传 SKILL.md）**
- **路径**：`POST /api/skills/install`
- **请求**：multipart/form-data（SKILL.md 文件 + 可选附件）
- **响应**：`201 Created` → `SkillResponse`

**接口5：卸载 Skill**
- **路径**：`DELETE /api/skills/{name}`
- **响应**：`204 No Content`
- **行为**：删除文件 + 数据库记录

### 4.2 内部接口

```python
class SkillLoader:
    """扫描 skills 目录，解析 SKILL.md，同步到 Store。"""
    def __init__(self, skills_dir: Path, store: SkillStore): ...
    async def scan(self) -> list[SkillInfo]: ...
    async def load_skill(self, name: str) -> SkillInfo | None: ...

class SkillService:
    """Skill 业务服务。"""
    def __init__(self, store: SkillStore, loader: SkillLoader): ...
    async def get_system_prompts(self) -> list[str]: ...
    async def list_skills(self, enabled: bool | None) -> SkillListResponse: ...
    async def get_skill(self, name: str) -> SkillResponse | None: ...
    async def update_skill(self, name: str, **fields) -> SkillResponse: ...
    async def install_skill(self, skill_md: bytes, attachments: dict[str, bytes] | None) -> SkillResponse: ...
    async def uninstall_skill(self, name: str) -> bool: ...

class ToolRegistry:
    """Tool 注册中心（独立于 Skill）。"""
    def register(self, tool_def: ToolDef, executor: Any) -> None: ...
    def unregister(self, tool_name: str) -> None: ...
    def get_all_tools(self) -> list[ToolDef]: ...
    async def execute(self, tool_call: ToolCall, *, cancellation: Any, context: dict | None) -> ToolResult: ...
```

## 5. 数据模型

```python
# ─── SKILL.md Frontmatter ────────────────────────────────

# ---
# name: deploy
# description: 部署应用到生产环境
# category: utility
# version: 1.0.0
# author: shorekeeper
# ---
#
# # Deploy Skill
#
# 当用户要求部署时，执行以下步骤...
#
# 系统提示词部分（注入到 system message）

@dataclass
class SkillInfo:
    """从 SKILL.md 解析出的 Skill 信息。"""
    name: str                    # 唯一标识
    description: str
    category: str                # memory | utility | custom
    version: str
    author: str
    system_prompt: str           # SKILL.md body（注入到系统消息）
    path: Path                   # SKILL.md 文件路径
    has_scripts: bool            # 目录中是否有脚本文件

# ─── 数据库存储（状态）────────────────────────────────────

@dataclass
class SkillState:
    """Skill 的运行时状态（数据库）。"""
    name: str                    # 关联 SkillInfo.name
    enabled: bool
    config: dict                 # 用户配置覆盖
    installed_at: datetime

# ─── Store 接口 ──────────────────────────────────────────

class SkillStore(Protocol):
    async def get(self, name: str) -> SkillState | None: ...
    async def list(self, enabled: bool | None) -> list[SkillState]: ...
    async def upsert(self, name: str, enabled: bool = True, config: dict | None = None) -> SkillState: ...
    async def update(self, name: str, **fields) -> SkillState: ...
    async def delete(self, name: str) -> bool: ...
```

## 6. SKILL.md 格式

```markdown
---
name: memory
description: 记忆管理能力，提供读写和搜索长期记忆的工具
category: memory
version: 1.0.0
author: shorekeeper
---

# Memory Skill

你拥有记忆管理能力。你可以：

- 读取用户的长期记忆（偏好、事实、指令）
- 写入新的长期记忆
- 搜索历史对话和记忆

## 使用场景

当用户提到之前的事情、表达偏好、或需要查找历史信息时，使用记忆工具。

## 注意事项

- 写入记忆前确认用户意图
- 搜索时使用简洁关键词
- 尊重用户隐私
```

## 7. 风险和边界情况

| 风险 | 说明 | 处理策略 |
|---|---|---|
| SKILL.md 格式错误 | frontmatter 缺少必填字段 | 跳过该 Skill，记录警告日志，不影响其他 Skill |
| 文件与数据库不同步 | 手动删除 SKILL.md 但数据库仍有记录 | scan() 时标记为 removed，API 返回时过滤 |
| 系统提示词膨胀 | 太多 Skill 的 prompt | 设置总 token 上限，超出时截断低优先级 Skill |
| 同名 Skill 冲突 | 多个目录有相同 name | 后扫描的跳过，记录警告 |
| Skill 目录中有脚本 | deploy.sh 等 | Skill 文件目录原样保留，脚本由 agent 执行，Skill 模块不直接运行 |

## 8. 测试方案

### 单元测试

| 测试点 | 说明 |
|---|---|
| SkillLoader 解析 SKILL.md | 正确提取 frontmatter 和 body |
| SkillLoader 缺少字段 | 跳过并记录警告 |
| SkillLoader 同步 | 新 Skill 创建、已存在更新、已删除标记 |
| SkillStore CRUD | 状态的增删改查 |
| SkillService get_system_prompts | 只返回 enabled Skill 的 prompt |
| SkillService install | 写入文件 + 同步数据库 |
| SkillService uninstall | 删除文件 + 数据库记录 |
| ToolRegistry 注册/执行 | Tool 的注册和执行 |

### 集成测试

| 测试场景 | 说明 |
|---|---|
| API → SkillService → 文件系统 + 数据库 | 安装/卸载全链路 |
| 启动扫描 → Skill 加载 | 模拟重启后 Skill 自动发现 |

## 9. 模块结构

```
backend/app/tool/
├── __init__.py
└── registry.py            # ToolRegistry

backend/app/skill/
├── __init__.py
├── models.py              # SkillInfo, SkillState
├── loader.py              # SkillLoader — 扫描 SKILL.md
├── store.py               # SkillStore — SQLite 状态存储
├── service.py             # SkillService — 业务逻辑
└── builtin.py             # 内置 Skill（如 memory skill 的 SKILL.md 内容）

backend/app/api/
└── skill.py               # Skill HTTP API

backend/tests/
├── test_skill_loader.py
├── test_skill_store.py
├── test_tool_registry.py
└── test_api_skill.py
```

## 10. 确认

- [ ] 用户已确认以上内容
- [ ] 可以开始开发
