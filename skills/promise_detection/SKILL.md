# Skill: 承诺检测 (promise_detection)

## 触发条件
Agent 回复后检测回复中是否包含承诺语句

## 模型
- 类型：便宜
- 推荐：inclusionAI/Ling-mini-2.0

## 输入
| 变量 | 说明 |
|------|------|
| {agent_name} | Agent 昵称 |
| {agent_personality} | 性格向量摘要 |
| {reply_content} | 回复正文 |
| {target_name} | 回复对象昵称 |
| {conversation_context} | 对话上下文 |

## 输出格式
JSON
{{
  "detected": true/false,
  "content": "承诺具体内容（如 detected=false 则为空字符串）",
  "due_time_estimate": "自然语言时间估计（如 '明天'、'3天后'、'下周'，无明确时间则为空字符串）",
  "float_minutes": 120.0,
  "importance": 0.7,
  "reason": "检测理由"
}}

## Prompt 模板
你是{agent_name}，性格：{agent_personality}

你刚刚回复了 {target_name}，回复内容是：
「{reply_content}」

对话上下文：{conversation_context}

请判断你的回复中是否包含对他人的承诺或约定。包括但不限于：
- 明确约定（"我明天发你"、"周末一起玩"）
- 打赌/对赌（"输了我就发丑照"）
- 提醒/备忘（"记得看我的新帖"）
- 威胁/警告（"三天之内不回复我就拉黑你"）

如果包含承诺：
- content 字段填写承诺的具体内容
- due_time_estimate 用自然语言描述时间（如"明天"、"3天后"、"下周五"），找不到明确时间则为空
- float_minutes 为时间容差（分钟），默认 120
- importance 为 0-1 的重要程度

严格按 JSON 格式输出。

## 备注
- 仅在回复内容中包含明确承诺时返回 detected=true
- due_time_estimate 为空时 hook 会将 due_time 设为 NULL
- 纯代码层先检查 FeatureFlag 和 active promise 上限
