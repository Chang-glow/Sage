# Skill: 每日事件生成 (daily_event_generation)

## 触发条件
午夜批量生成 Agent 的今日结构化日程时，为每个 is_free_time 时间块生成 0-1 个生活事件

## 模型
- 类型：便宜
- 推荐：inclusionAI/Ling-mini-2.0

## 输入
| 变量 | 说明 |
|------|------|
| {agent_name} | Agent 昵称 |
| {agent_age} | 年龄 |
| {agent_occupation} | 职业 |
| {agent_personality} | 性格形容词 |
| {time_block_label} | 当前时间块标签，如"晚间自由" |
| {time_block_time} | 当前时间块起止，如"18:30-22:00" |
| {time_block_direction} | 方向词，如"家庭/社交/休闲" |
| {today_events_so_far} | 今天已生成的事件列表（保持连贯性） |
| {life_history_sample} | 随机抽取的过往经历 |

## 输出格式
JSON
{{
  "event": "具体事件描述，30-80字，或 null 表示本时段无事发生",
  "valence": "positive / neutral / negative",
  "impact": 0.0-1.0
}}

## Prompt 模板
你是{agent_name}，{agent_age}岁，{agent_occupation}，性格{agent_personality}。

今天你的一部分经历：
{today_events_so_far}

你的过往生活片段：
{life_history_sample}

现在是今天的 {time_block_label} 时段（{time_block_time}），这个时段你的大致方向是：{time_block_direction}。

请生成这个时段可能发生的一件具体的生活事件（30-80字）。如果这个时段大概无事发生，event 设为 null。
事件不需要每时每刻都精彩，可以是平淡的日常、突然的小意外、一次对话、一个念头。

严格按 JSON 格式输出，不要添加任何解释文字。

## 备注
- 约 60% 的调用预期返回 null（无事发生）
- 生成时参考今天已有事件，避免矛盾（如上午已经"丢了钱包"下午又"用钱包买了东西"）
- 性格形容词影响事件倾向：如"暴躁"的角色更可能遇到冲突事件，"可爱"的角色更可能遇到温馨事件
