# AGENTS.md

> **优先级：本文档为入口文件。在开始任何工作之前，AI 必须先阅读以下两份规范文档。**

## 必读文档

| 顺序 | 文档 | 内容 |
|---|---|---|
| 1 | `docs/architecture.md` | 项目架构规范——模块边界、依赖规则、数据流。**人和 AI 都必须遵守。** |
| 2 | `docs/ai-development.md` | AI 开发流程规范——开发流程、Review 机制、测试标准、Merge 条件。 |

## 补充文档

| 文档 | 内容 |
|---|---|
| `docs/engineering-principles.md` | 项目长期设计哲学 |
| `docs/product-spec.md` | 功能规格（按需补充） |
| `docs/kun-ui-llms-full.txt` | KunUI 完整 LLM 文档——组件参考、集成指南、API 详情。**前端开发时必读。** |

## KunUI (@kungal/ui-vue) 前端开发指引

> 本项目使用 plain Vue (Vite) 模式集成 KunUI，不依赖 Nuxt。

- **HTML 从不净化。** KunUI 不内置 sanitizer。将用户/不可信 HTML 传入 `KunContent` 或 `useKunMessage(..., richText=true)` 前，必须自行净化（如 DOMPurify）。
- **图标内置，不运行时请求。** 使用 `<KunIcon>` + 内置名称（如 `lucide:check`）；自定义图标用 `registerKunIcon(s)` 从 `@kungal/ui-core` 注册。不要依赖运行时 Iconify 请求。
- **应用拥有 Tailwind v4 入口样式表。** 必须按顺序包含：`@import 'tailwindcss';` → `@import '@kungal/ui-tokens';` → `@import '@kungal/ui-vue/style.css';`，以及指向 `@kungal/ui-vue` 和 `@kungal/ui-core` 的 `@source` 指令。两者必须作为 pnpm 直接依赖安装。
- **Dark Mode** = 切换 `<html>` 上的 `kun-dark-mode` class。
- 如果使用 toast / 确认对话框，在应用根组件挂载 `<KunMessageProvider />` / `<KunAlertProvider />`。
- 完整集成指南：`docs/kun-ui-llms-full.txt`（本地）或 [GitHub INTEGRATION.md](https://github.com/kungal/kun-ui/blob/main/docs/INTEGRATION.md)。

## AI 核心约束

- AI 是项目工程师，不是架构师，不是产品经理
- **所有涉及架构层面的决策，必须与用户确认后方可执行**
- 禁止跳过 `ai-development.md` 中定义的开发流程直接写代码
