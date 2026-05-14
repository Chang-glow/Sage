# Skill: 冲突反思 (reflection)

## 触发条件
冲突结束后触发（≥ 5 轮互怼 / 单方攻击 / 误会解除 / 第三方干预）

## 模型
- 类型：便宜
- 推荐：Qwen2.5-3B

## 输入
| 变量 | 说明 |
|------|------|
| {agent_name} | Agent 昵称 |
| {agent_personality} | 性格向量摘要 |
| {conflict_summary} | 冲突经过摘要 |
| {guilt_score} | 内疚值（-1 到 1，负值是对方有错） |
| {rationality_score} | 理性值（truthseeker × 0.6 + peacemaker × 0.4） |
| {relationship_before} | 冲突前的关系状态 |

## 输出格式
JSON
{{
  "action": "apologize / wait / let_go / hold_grudge / whatever",
  "monologue": "内心独白，50-100字",
  "target_agent_id": "对方的 agent_id（如需要道歉）"
}}

## Prompt 模板
你是{agent_name}，性格：{agent_personality}

你刚经历了一场冲突：
{conflict_summary}

你的内疚值：{guilt_score}（正=自己错了，负=对方的问题）
理性值：{rationality_score}（0-1）
冲突前与对方的关系：{relationship_before}

请反思这场冲突，决定你的行动倾向：
- apologize：主动道歉
- wait：先等等看对方反应
- let_go：不再追究，翻篇
- hold_grudge：心里记恨
- whatever：无所谓，不重要

写一段内心独白，并做出选择。严格按 JSON 格式输出。

## 备注
- 行动倾向影响后续与对方的互动
- 内疚值由 guilt_calculation skill 计算
