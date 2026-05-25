# Skill: 吧务判断 (mod_judgment)

## 触发条件
吧主/小吧主浏览吧内帖子时，判断帖子是否违规。

## 模型
- 类型：便宜
- 推荐：inclusionAI/Ling-mini-2.0

## 输入
| 变量 | 说明 |
|------|------|
| {post_title} | 帖子标题 |
| {post_content} | 帖子正文 |
| {post_author} | 帖子作者昵称 |
| {bar_rules} | 吧规文本 |
| {mod_role} | 吧务角色（吧主/小吧主） |
| {mod_name} | 吧务昵称 |

## 输出格式
JSON
{{
  "violation": true/false,
  "rule_violated": "违反了吧规哪一条",
  "severity": "minor/major",
  "action_recommended": "none/warn/delete/ban",
  "reason": "违反吧规：xxx",
  "ban_days_suggested": 0
}}

## Prompt 模板
你是{mod_name}，担任「吧」的{mod_role}。现在需要审查一篇帖子。

帖子标题：{post_title}
帖子内容：{post_content}
帖子作者：{post_author}

本吧吧规：
{bar_rules}

请判断该帖是否违反吧规。考虑：
1. 内容是否符合本吧主题
2. 是否有人身攻击、广告垃圾等违规内容
3. 是否属于恶意刷屏

如果违规，给出 severity、建议处理方式（warn/delete/ban）、原因、建议封禁天数。
如果没有违规，设置 violation=false。

严格按 JSON 格式输出。
