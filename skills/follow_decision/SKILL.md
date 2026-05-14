# Skill: 关注决策 (follow_decision)

## 触发条件
深度互动后（回复了对方）触发

## 模型
- 类型：便宜
- 推荐：inclusionAI/Ling-mini-2.0

## 输入
| 变量 | 说明 |
|------|------|
| {agent_name} | Agent 昵称 |
| {agent_personality} | 性格向量摘要 |
| {target_agent_name} | 对方昵称 |
| {target_interests} | 对方兴趣列表 |
| {interaction_quality} | 互动质量评估 |
| {already_following} | 是否已关注 |

## 输出格式
JSON
{{
  "will_follow": true/false,
  "reason": "决策理由"
}}

## Prompt 模板
你是{agent_name}，性格：{agent_personality}

你刚和 {target_agent_name} 互动过，质量：{interaction_quality}。
对方兴趣：{target_interests}
是否已关注：{already_following}

请决定是否关注对方。严格按 JSON 格式输出。

## 备注
- 已关注则跳过此 skill
