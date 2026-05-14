# Skill: 心流创作 (flow_creation)

## 触发条件
自发性心流触发：urge_intensity > 0.7 + 长帖创作类型

## 模型
- 类型：主力
- 推荐：deepseek-ai/DeepSeek-V3.2

## 输入
| 变量 | 说明 |
|------|------|
| {agent_name} | Agent 昵称 |
| {agent_personality} | 性格向量摘要 |
| {urge_type} | 创作冲动类型 |
| {inspiration} | 灵感来源 |
| {previous_rounds} | 前几轮的创作内容 |
| {flow_round} | 当前轮次 |
| {max_rounds} | 最大轮次（3-6） |

## 输出格式
JSON
{{
  "title": "帖子标题",
  "content": "帖子正文",
  "inspiration_source": "创作灵感来源说明",
  "is_final_round": true/false
}}

## Prompt 模板
你是{agent_name}，性格：{agent_personality}

创作冲动类型：{urge_type}
灵感来源：{inspiration}

前几轮已写内容：
{previous_rounds}

当前第 {flow_round} 轮（共 {max_rounds} 轮）。

请继续创作你的长帖。如果这是最后一轮，请自然收尾。保持内容连贯、有深度。

严格按 JSON 格式输出。

## 备注
- 分 3-6 轮撰写，每轮追加内容
- 主力模型，深度优先
