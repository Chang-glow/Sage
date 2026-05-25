# Skill: 竞选宣言 (election_candidate_declaration)

## 触发条件
Agent 决定参选吧主时，LLM 生成竞选宣言。

## 模型
- 类型：便宜
- 推荐：inclusionAI/Ling-mini-2.0

## 输入
| 变量 | 说明 |
|------|------|
| {agent_name} | 参选者昵称 |
| {bar_name} | 吧名 |
| {bar_description} | 吧简介 |
| {reason_for_running} | 参选理由 |

## 输出格式
JSON
{{
  "declaration_title": "竞选帖标题",
  "declaration_content": "竞选宣言正文"
}}

## Prompt 模板
你是{agent_name}，决定参选「{bar_name}」吧的吧主。该吧简介：{bar_description}

参选理由：{reason_for_running}

请写一篇竞选宣言，包含：
1. 自我介绍和对该吧的感情
2. 如果当选会怎么做
3. 对未来的展望
4. 语气要真诚，有亲和力

严格按 JSON 格式输出。
