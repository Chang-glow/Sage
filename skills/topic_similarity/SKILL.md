# Skill: 话题相似度判断 (topic_similarity)

## 触发条件
判断两段文本是否为同一话题。调用场景：
- 浏览筛选：判断帖子内容是否与 Agent 兴趣相关
- 心流检测：判断两条回复是否在聊同一件事

## 模型
- 类型：便宜
- 推荐：inclusionAI/Ling-mini-2.0

## 输入
| 变量 | 说明 |
|------|------|
| {text_a} | 第一段文本 |
| {text_b} | 第二段文本 |
| {comparison_context} | 判断场景：post_vs_interests（帖子与兴趣）或 reply_vs_reply（回复之间） |

## 输出格式
JSON
{{
  "is_same_topic": true/false,
  "similarity_score": 0.0-1.0,
  "topic_summary": "3-6词简短话题描述",
  "reason": "一句话判据"
}}

## Prompt 模板
请判断以下两段文本是否在讨论同一话题。

文本A：
{text_a}

文本B：
{text_b}

判断场景：{comparison_context}

要求：
- 关注核心主题，忽略细枝末节
- 语义相关（不同用词但说同一件事）视为同一话题
- similarity_score：0.0 完全无关，0.3 略有交集，0.6 明显相关，0.9+ 高度一致

严格按 JSON 格式输出，不要添加任何解释文字。
