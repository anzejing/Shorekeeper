# 会话 URL 路由设计（Session URL Routing）

> 状态：已确认实施（2026-08-06）
> 目标：仿豆包模式，会话地址带 session id，刷新不丢失会话。

## 1. 背景与问题

现状：
- 路由为 `/chat`，无参数，所有会话共用同一 URL
- 会话 id 仅存在 Pinia store（内存），刷新后丢失，回到空白新会话

目标（豆包模式）：

```
新建会话     → /chat
发送消息后   → /chat/{session_id}
点击历史会话 → /chat/{session_id}
刷新         → 从 URL 读取 session_id → 加载该会话，不丢失
```

## 2. 设计原则

**URL 是会话状态的唯一来源**：

- `/chat` → 新会话（空白）
- `/chat/{sessionId}` → 指定会话
- 单向驱动：URL 变化 → store 加载会话；store 不回写 URL
- URL 更新由操作点显式触发（组件层调用 router）

## 3. 路由设计

```ts
// main.ts
{
  path: '/chat/:sessionId?',   // 可选参数，兼容 /chat 与 /chat/{id}
  name: 'chat',
  component: () => import('./views/ChatView.vue'),
}
```

## 4. 数据流

### 4.1 点击历史会话（push，可后退）

```
用户点击会话 → router.push('/chat/{id}')
                    ↓
        route.params.sessionId 变化
                    ↓
    ChatView watch → store.loadSession(id)
                    ↓
        fetchMessages → 消息渲染
```

### 4.2 发送首条消息（replace，避免历史堆栈膨胀）

```
用户发送消息 → chat_stream 返回 session_id
                    ↓
        store.currentSessionId = session_id
        ChatView 收到返回值 → router.replace('/chat/{id}')
```

### 4.3 刷新页面

```
浏览器刷新 /chat/{id}
    ↓
ChatView onMounted / watch(immediate)
    ↓
store.loadSession(id) → fetchMessages → 恢复会话
```

### 4.4 删除当前会话

```
删除会话成功 → 若为当前会话 → router.push('/chat')
```

## 5. 改动清单（全部前端）

| 文件 | 改动 |
|---|---|
| `src/main.ts` | 路由改为 `/chat/:sessionId?` |
| `src/stores/chat.ts` | 新增 `loadSession(sessionId)`；`sendMessage` 返回 session_id |
| `src/views/ChatView.vue` | watch 路由参数 → `loadSession`；`handleSend` 后更新 URL |
| `src/components/AppSidebar.vue` | 新对话 `push('/chat')`；选会话 `push('/chat/{id}')`；删除当前会话后跳 `/chat` |

## 6. 边界处理

| 场景 | 处理 |
|---|---|
| 刷新后 URL 带无效/已删除 sessionId | `loadSession` 404 → 显示错误，URL 回退 `/chat` |
| URL 与 store 双向同步死循环 | 单向驱动：URL → store；URL 由操作点显式更新 |
| 发送首条消息 URL 更新 | `router.replace`（同一对话延续，不产生历史） |
| 切会话 | `router.push`（保留后退历史，与豆包一致） |
| 侧边栏导航高亮 | 无 `/chat` 导航项（已二合一），不受影响 |
| 重复加载同会话 | `loadSession` 内判断 `sessionId === currentSessionId` 直接跳过 |

## 7. 测试方案

- [ ] 新建对话 → 发消息 → URL 变为 `/chat/{id}` → 刷新保持会话
- [ ] 点击历史会话 → URL 变为 `/chat/{id}` → 消息正确加载
- [ ] 后退/前进按钮 → 会话正确切换
- [ ] 删除当前会话 → 回退新会话 `/chat`
- [ ] 手工输入无效 id → 优雅降级（错误提示 + 回退）
- [ ] 前端 `pnpm build` 通过

## 8. 决策记录

| 决策点 | 选择 | 理由 |
|---|---|---|
| 切会话 URL 方式 | `push` | 保留浏览器后退历史，与豆包一致 |
| 首条消息 URL 方式 | `replace` | 同一对话延续，避免历史堆栈膨胀 |
| 状态源 | URL（路由参数） | 刷新/后退/前进天然一致 |
