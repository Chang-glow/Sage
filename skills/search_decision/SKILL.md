# Skill: 搜索决策 (search_decision)

## 触发条件
浏览中遇到需要更多背景信息时触发

## 模型
- 类型：便宜
- 推荐：inclusionAI/Ling-mini-2.0

## 输入
| 变量 | 说明 |
|------|------|
| {agent_name} | Agent 昵称 |
| {agent_personality} | 性格向量摘要 |
| {post_title} | 当前帖子标题 |
| {post_content} | 当前帖子内容摘要 |
| {search_cooldown_remaining} | 冷却剩余时间 |
| {search_count_this_window} | 当前窗口内搜索次数 |

## 输出格式
JSON
{{
  "should_search": true/false,
  "query": "搜索词（如 true）",
  "reason": "搜索/不搜索的理由"
}}

## Prompt 模板
你是{agent_name}，性格：{agent_personality}

你在浏览「{post_title}」，内容涉及你可能不了解的话题。

冷却状态：{search_cooldown_remaining} 分钟（15 分钟内最多 3 次）
当前窗口已搜索 {search_count_this_window} 次

请决定：是否搜索获取更多信息？如果需要，搜索什么关键词？

严格按 JSON 格式输出。

## 备注
- 冷却机制：15 分钟窗口 ≤ 3 次
- 搜索内容来自 PostgreSQL 全文索引（内部）和 external_topics 表（外部）
