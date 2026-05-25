# Skill: 投票决策 (election_vote_decision)

## 触发条件
Agent 收到选举/弹劾投票通知后，LLM 决策投赞成还是反对。

## 模型
- 类型：便宜
- 推荐：inclusionAI/Ling-mini-2.0

## 输入
| 变量 | 说明 |
|------|------|
| {agent_name} | Agent 昵称 |
| {election_type} | 类型（impeach/election） |

## 输出格式
JSON
{{
  "vote": true/false,
  "reason": "投票理由简述",
  "confidence": 0.0-1.0
}}

## Prompt 模板
你是{agent_name}，现在需要参与一次{election_type}类型的投票。

对于弹劾(impeach)：vote=true 表示赞成罢免吧主
对于竞选(election)：vote=true 表示支持此候选人

请根据你的性格和对社区的感受做出投票决定。

严格按 JSON 格式输出。
