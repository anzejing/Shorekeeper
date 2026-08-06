# 图片识别工具（pi + MiMo）

> 当开发环境中的主模型不支持图片输入（无法识图）时，使用本方法调用 MiMo 视觉模型理解截图。

## 背景

- 开发时通过 `agent-browser` 截图验证 UI，但主模型可能不支持图片输入（图片会被省略）
- MiMo（`xiaomi-token-plan-cn` provider）的 `mimo-v2.5` 支持文本 + 图片输入

## 命令

```bash
pi --model xiaomi-token-plan-cn/mimo-v2.5 -p @<图片绝对路径> "<识图需求>"
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--model xiaomi-token-plan-cn/mimo-v2.5` | 指定 MiMo 视觉模型。**注意 provider 名为 `xiaomi-token-plan-cn`，不是 `mimo`** |
| `-p` | prompt 模式 |
| `@<图片绝对路径>` | 图片路径（用 `@` 前缀标记为附件） |
| `"<识图需求>"` | 中文描述需要识别的重点 |

## 使用示例

### 1. 整体界面检查

```bash
pi --model xiaomi-token-plan-cn/mimo-v2.5 -p @/tmp/shots/screenshot.png \
  "这是 AI 助手前端界面截图。请描述：1)整体布局 2)侧边栏内容 3)主区域显示什么 4)是否有异常（空白、错位、样式问题）。用中文回答。"
```

### 2. 局部元素验证（如按钮、图标）

```bash
pi --model xiaomi-token-plan-cn/mimo-v2.5 -p @/tmp/shots/screenshot.png \
  "重点检查左侧边栏顶部的新对话按钮：样式、图标、对齐是否正常。用中文简洁回答。"
```

### 3. 与 agent-browser 组合使用（推荐流程）

```bash
# 1. 截图
agent-browser screenshot --screenshot-dir /tmp/shots

# 2. 取最新截图交给 mimo 识图
LATEST=$(ls -t /tmp/shots/*.png | head -1)
pi --model xiaomi-token-plan-cn/mimo-v2.5 -p @$LATEST "<识图需求>"
```

## 注意事项

1. **provider 名称**：命令中的模型是 `xiaomi-token-plan-cn/mimo-v2.5`。写成 `mimo/mimo-v2.5` 会报 "No API key found for huggingface"
2. **API Key**：需要 `~/.pi/agent/auth.json` 中已配置 `xiaomi-token-plan-cn` 的 key（或已登录对应 provider）
3. **超时**：识图请求较慢（图片上传 + 生成），bash 命令建议设置 `timeout 120`
4. **输出**：模型可能输出较长，用 `tail -N` 截取关键部分
