# Skill: 记忆固化评估 (memory_consolidation)

## 触发条件
每日清理任务时触发（每天一次）

## 模型
- 类型：便宜
- 推荐：Qwen2.5-3B

## 输入
| 变量 | 说明 |
|------|------|
| {agent_name} | Agent 昵称 |
| {short_term_memories} | 短期记忆碎片列表 |
| {long_term_memories} | 长期记忆碎片列表 |
| {core_memories} | 核心身份记忆 |
| {recent_events} | 近期重要事件 |

## 输出格式
JSON
{{
  "to_consolidate": ["应升级为长期或固化为核心的碎片 ID 列表"],
  "to_discard": ["应丢弃的碎片 ID 列表"],
  "notes": "评估备注"
}}

## Prompt 模板
你是{agent_name}的记忆管理模块。

短期记忆：
{short_term_memories}

长期记忆：
{long_term_memories}

核心记忆：
{core_memories}

近期事件：
{recent_events}

评估：
- 哪些短期记忆应升级为长期？（检索 ≥ 3 次 or 重大事件 or 关系剧变）
- 哪些长期记忆应固化为核心？（存在 > 180 天 + 检索 ≥ 10 次 + importance > 0.85）
- 哪些记忆可以丢弃？

严格按 JSON 格式输出。

## 备注
- 容量限制：short ≤ 150，long ≤ 50
- 超容量时按评分淘汰最低分
