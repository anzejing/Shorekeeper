# Shorekeeper

<div align="center">

**AI Assistant Platform** — 长期维护的个人 AI 助手平台

![Shorekeeper](frontend/public/favicon-32x32.png)

</div>

Shorekeeper 是一个自托管的 AI 助手平台：Web 界面 + 流式对话 + 工具调用 + 权限审批 + 长期记忆，全部本地部署。你的数据、你的助手。

---

## ✨ 核心特性

| 特性 | 说明 |
|---|---|
| 💬 **流式对话** | SSE 实时流式输出，支持思考过程展示 |
| 🛠️ **工具调用** | bash 执行、文件读写、记忆读写等工具，可扩展 |
| 🔐 **权限审批** | 敏感操作（命令执行等）需人工确认，支持允许/拒绝 |
| 🧠 **长期记忆** | 跨会话保存用户偏好、事实、指令，自动检索 |
| 📚 **Skill 系统** | 模块化能力注入，可安装社区 Skill |
| 💾 **会话管理** | 多会话切换、搜索、分组、删除，上下文独立 |
| 🎨 **现代 UI** | Vue 3 + KunUI + Tailwind CSS v4 |

## 🏗️ 架构概览

```
Vue (UI)                    前端界面（流式渲染、审批卡片）
  ↓
FastAPI (API Layer)         HTTP 接口、SSE 流
  ↓
Assistant Service           会话编排、消息组装
  ↓
Memory / Skill / Permission 业务模块
  ↓
Runtime Adapter             Agent Loop、Tool Calling、审批挂起/恢复
  ↓
LiteLLM                     多 Provider 统一调用
  ↓
LLM Provider                mimo / OpenAI / Anthropic / ...
```

> 详细架构规范见 [`docs/architecture.md`](docs/architecture.md)

## 🛠️ 技术栈

- **前端**：Vue 3.5 + TypeScript + Vite + Pinia + KunUI (`@kungal/ui-vue`) + Tailwind CSS v4
- **后端**：FastAPI + Python 3.11+ + LiteLLM
- **存储**：SQLite（开发）/ 可扩展 PostgreSQL
- **通信**：HTTP + SSE

## 🚀 快速开始

### 1. 安装后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 2. 安装前端

```bash
cd frontend
pnpm install                     # 或 npm install
```

### 3. 配置

模型配置在 Web 界面完成：打开「模型」页（`/models`）添加 Provider（openai / openai_like / anthropic / gemini）
并选择模型；api_key 等配置存入数据库。首次启动后若无任何 Provider，请在「模型」页配置。

其他系统配置仍由 `~/.shorekeeper/config.yaml` 管理（可在「配置」页修改）。

> 模型管理详细设计见 [docs/models-management.md](docs/models-management.md)。

### 4. 启动

一键启动前后端：

```bash
./start.sh
```

或分别启动：

```bash
# 后端（http://localhost:8000）
cd backend && source .venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8000

# 前端（http://localhost:5173）
cd frontend && npm run dev
```

打开 http://localhost:5173 开始使用。API 文档见 http://localhost:8000/docs。

## 🧪 测试

```bash
cd backend && source .venv/bin/activate
pytest tests/ -q        # 290 个测试
```

## 📁 目录结构

```
├── backend/                 # FastAPI 后端
│   └── app/
│       ├── api/             # HTTP 接口（chat/runtime/memory/skill/permission/...）
│       ├── memory/          # 记忆模块（会话 + 长期记忆 + 搜索）
│       ├── skill/           # Skill 模块
│       ├── permission/      # 权限引擎 + 审批管理
│       ├── runtime/         # Runtime 适配器（Agent Loop、状态机、事件）
│       ├── tools/           # 内置工具（bash_execute / read_file / write_file）
│       └── config/          # 配置服务
├── frontend/                # Vue 3 前端
│   └── src/
│       ├── views/           # 页面（ChatView / ConfigView）
│       ├── components/      # 组件（聊天、审批卡片、工具卡片、侧边栏）
│       ├── stores/          # Pinia 状态（chat / config）
│       └── api/             # API 客户端
├── docs/                    # 项目文档
└── start.sh                 # 一键启动脚本
```

## 📚 文档

| 文档 | 内容 |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 架构规范（模块边界、依赖规则、数据流） |
| [docs/product-spec.md](docs/product-spec.md) | 功能规格（按功能域） |
| [docs/progress.md](docs/progress.md) | 开发进度与修改记录 |
| [docs/ai-development.md](docs/ai-development.md) | AI 开发流程规范 |
| [docs/engineering-principles.md](docs/engineering-principles.md) | 设计哲学 |
| [docs/image-recognition.md](docs/image-recognition.md) | 模型无法识图时如何调用 pi + MiMo 识图 |
| [docs/model-config.md](docs/model-config.md) | 模型配置（⚠️ 已废弃，历史参考） |
| [docs/models-management.md](docs/models-management.md) | 模型管理（多 Provider/Model、目录同步、热切换） |

## 🧰 内置工具

| 工具 | 说明 | 权限 |
|---|---|---|
| `bash_execute` | 执行 shell 命令 | 需审批 |
| `read_file` | 读取文件 | 需审批 |
| `write_file` | 写入文件 | 需审批 |
| `read_memory` | 读取长期记忆 | 允许 |
| `write_memory` | 写入长期记忆 | 允许 |
| `search_memory` | 搜索记忆与历史 | 允许 |

## 🔒 安全

- 敏感操作（命令执行、文件写入等）默认 **需人工审批**
- 权限规则持久化存储，可通过 API 管理
- 过期审批自动清理（每 10 分钟）
- 审批拒绝后工具不会被执行

## 📄 License

Private / 内部项目
