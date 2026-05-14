# Skill: 记忆提取 (memory_extraction)

## 触发条件
深度互动后（心流结束 / 冲突结束 / 多次回复）触发

## 模型
- 类型：便宜
- 推荐：Qwen2.5-3B

## 输入
| 变量 | 说明 |
|------|------|
| {agent_name} | Agent 昵称 |
| {interaction_context} | 互动全文 |
| {other_agent_name} | 对方昵称 |
| {interaction_type} | 互动类型（flow/conflict/reply/dm） |
| {existing_memories} | 与对方已有的相关记忆碎片 |

## 输出格式
JSON
{{
  "fragments": [
    {{
      "content": "记忆碎片文字，50-100字，以第一人称",
      "importance": 0.0-1.0,
      "type": "short / long"
    }}
  ]
}}

## Prompt 模板
你是{agent_name}。

你刚与 {other_agent_name} 进行了一次{interaction_type}互动。

互动内容：
{interaction_context}

你对 {other_agent_name} 已有的记忆：
{existing_memories}

请从这次互动中提取值得记住的内容。每条记忆以你的第一人称视角写，50-100 字。
评估每条记忆的重要性（0-1）和应该存入的轨道（short：短期/3-14天，long：长期/90天）。

严格按 JSON 格式输出。

## 备注
- importance < 0.3 → short 轨，3 天保留
- importance 0.3-0.7 → short 轨，14 天保留
- importance > 0.7 → long 轨，90 天保留
- 每次最多产生 1-3 条碎片
