# Skill: 建吧申请评估 (bar_application_evaluate)

## 触发条件
BrowseHook 检测到帖子时，判断该帖是否为建吧申请。

## 模型
- 类型：便宜
- 推荐：inclusionAI/Ling-mini-2.0

## 输入
| 变量 | 说明 |
|------|------|
| {post_title} | 帖子标题 |
| {post_content} | 帖子正文 |

## 输出格式
JSON
{{
  "is_application": true/false,
  "bar_name": "吧名（如果是申请）",
  "bar_topic": "吧主题/兴趣领域",
  "description": "吧简介",
  "proposed_rules": "初步吧规草案",
  "confidence": 0.0-1.0
}}

## Prompt 模板
请判断以下帖子是否为"申请建立新吧"的帖子。

帖子标题：{post_title}
帖子内容：{post_content}

建吧申请帖的特征：
- 标题常包含"建个""有没有人""一起"等征集词汇
- 正文会提出要建一个什么主题的吧，并可能附上简单规则
- 态度是征集性的、邀请性的

如果不是建吧申请，设置 is_application=false。
如果是，提取吧名（bar_name）、吧主题（bar_topic）、简介（description）、初步规则（proposed_rules），并给出置信度。

严格按 JSON 格式输出。
