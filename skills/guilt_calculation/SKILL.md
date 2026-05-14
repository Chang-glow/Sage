# Skill: 内疚值计算 (guilt_calculation)

## 触发条件
冲突结束后，在 reflection 之前触发

## 模型
- 类型：便宜
- 推荐：inclusionAI/Ling-mini-2.0

## 输入
| 变量 | 说明 |
|------|------|
| {agent_name} | Agent 昵称 |
| {agent_personality} | 性格向量摘要 |
| {conflict_exchange} | 冲突对话记录 |
| {aggression_score} | 攻击性分量 |
| {other_perceived_hurt} | 对方表现出的受伤程度 |
| {relationship_loss} | 关系损失评估 |

## 输出格式
JSON
{{
  "guilt_delta": -1.0 到 1.0 之间的值,
  "reason": "计算理由"
}}

## Prompt 模板
你是{agent_name}，性格：{agent_personality}

冲突对话：
{conflict_exchange}

你的攻击性水平：{aggression_score}
对方受伤程度：{other_perceived_hurt}
关系损失：{relationship_loss}

请评估你应该感到的内疚程度。正=自己错了，负=对方问题。考虑：你的攻击性权重、对方受伤程度、关系损失、性格修正。

严格按 JSON 格式输出。

## 备注
- guilt_delta 被 reflection 用作输入
