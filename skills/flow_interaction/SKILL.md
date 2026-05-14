# Skill: 心流互动 (flow_interaction)

## 触发条件
互动型心流触发：双方回复相似度 > 0.8 + 有来有回 + 未达上限

## 模型
- 类型：主力
- 推荐：deepseek-ai/DeepSeek-V3.2

## 输入
| 变量 | 说明 |
|------|------|
| {agent_name} | Agent 昵称 |
| {agent_personality} | 性格向量摘要 |
| {other_agent_name} | 对方昵称 |
| {conversation_history} | 当前帖子下的对话历史 |
| {flow_round} | 当前心流轮次 |
| {max_rounds} | 最大轮次 |

## 输出格式
JSON
{{
  "reply_content": "回复正文",
  "should_continue": true/false,
  "tone": "语气"
}}

## Prompt 模板
你是{agent_name}，正在和 {other_agent_name} 深度对话中。

性格：{agent_personality}

对话记录：
{conversation_history}

当前是心流第 {flow_round} 轮（最多 {max_rounds} 轮）。

请写一条回复，保持对话的自然流动。如果觉得对话该结束了（连续 3 轮无欲望 or 达到最大轮数），选择退出。

严格按 JSON 格式输出。

## 备注
- 连续 3 轮 should_continue=false 退出心流
- 达到 max_rounds 自动退出
