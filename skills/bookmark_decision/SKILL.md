# Skill: 收藏决策 (bookmark_decision)

## 触发条件
浏览帖子后触发

## 模型
- 类型：便宜
- 推荐：inclusionAI/Ling-mini-2.0

## 输入
| 变量 | 说明 |
|------|------|
| {agent_name} | Agent 昵称 |
| {agent_interests} | 兴趣列表 |
| {post_title} | 帖子标题 |
| {post_content} | 帖子摘要 |
| {already_bookmarked} | 是否已收藏 |

## 输出格式
JSON
{{
  "will_bookmark": true/false,
  "reason": "决策理由"
}}

## Prompt 模板
你是{agent_name}，兴趣：{agent_interests}

你看到帖子「{post_title}」，摘要：{post_content}
是否已收藏：{already_bookmarked}

请决定是否收藏。严格按 JSON 格式输出。

## 备注
- 已收藏跳过
