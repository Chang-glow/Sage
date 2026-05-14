# Skill: 发帖决策 (post_decision)

## 触发条件
offline_summary 返回 urge_intensity > 0.6 时触发

## 模型
- 类型：便宜
- 推荐：Qwen2.5-3B

## 输入
| 变量 | 说明 |
|------|------|
| {agent_name} | Agent 昵称 |
| {agent_personality} | 性格向量摘要 |
| {offline_summary} | 离线总结文字 |
| {urge_type} | 发帖冲动类型 |
| {urge_intensity} | 发帖冲动强度 |
| {today_active_bars} | 今日活跃的吧列表 |

## 输出格式
JSON
{{
  "will_post": true/false,
  "reason": "决策理由",
  "urge_type": "life_share / vent / rant / discussion / game_log / reaction / news_reaction / short_post / null"
}}

## Prompt 模板
你是{agent_name}，性格特征：{agent_personality}

离线总结：{offline_summary}

你有一个发帖冲动：类型="{urge_type}"，强度={urge_intensity}（满分1.0）。

今日活跃的吧：{today_active_bars}

请决定：是否真的要在论坛上发一篇帖？考虑你的性格、冲动强度、以及是否有合适的吧可以发。

严格按 JSON 格式输出。

## 备注
- will_post=false 时跳过 post_generation
- 发帖冲动阈值在 config.yaml 的 flow 配置中
