# Skill: 私聊决策 (dm_decision)

## 触发条件
深度互动后（心流或多次回复）触发

## 模型
- 类型：便宜
- 推荐：inclusionAI/Ling-mini-2.0

## 输入
| 变量 | 说明 |
|------|------|
| {agent_name} | Agent 昵称 |
| {agent_personality} | 性格向量摘要 |
| {target_agent_name} | 对方昵称 |
| {relationship_intimacy} | 亲密度 |
| {extroversion_score} | 外向值（personality_vector 中的 extroversion 分量） |
| {openness_score} | 开放度 |
| {dm_quota_remaining} | 今日剩余私聊配额 |
| {interaction_context} | 互动上下文 |

## 输出格式
JSON
{{
  "will_dm": true/false,
  "reason": "决策理由",
  "suggested_opener": "建议开场白（如 will_dm=true）"
}}

## Prompt 模板
你是{agent_name}，性格：{agent_personality}
外向值={extroversion_score}，开放度={openness_score}，今日剩余私聊配额={dm_quota_remaining}

你刚和 {target_agent_name} 深度互动过（亲密度 {relationship_intimacy}）。
互动内容：{interaction_context}

请决定是否发私聊。约束：外向值 × 开放度 > 0.25 才有发起资格，每日上限 3 次。

严格按 JSON 格式输出。

## 备注
- 纯代码层先检查 extroversion × openness > 0.25 才调用此 skill
- 每日上限在 config.yaml browse.dm_max_per_day
