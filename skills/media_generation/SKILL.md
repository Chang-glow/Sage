# Skill: 伪富媒体生成 (media_generation)

## 触发条件
将内容生成 Skill 输出中的占位符 `{{media: ...}}` 转换为伪富媒体标签 `[img: ...]` / `[emj: ...]`。在帖子/回复/总结帖入库前调用。

## 模型
- 类型：便宜
- 推荐：inclusionAI/Ling-mini-2.0

## 输入
| 变量 | 说明 |
|------|------|
| {raw_text} | 带占位符的原始文本 |

## 输出格式
JSON
{{
  "processed_text": "完整的替换后文本",
  "placeholders_found": 0,
  "placeholders_replaced": 0
}}

## Prompt 模板
请将以下文本中的占位符转换为伪富媒体标签。

输入文本：
{raw_text}

占位符格式：{{{{media: 类型, 描述文字}}}}
- 类型为 image → 转换为 `[img: 润色后的描述]`
- 类型为 emoji → 转换为 `[emj: 润色后的描述]`

转换要求：
- 图片描述扩展为 20-80 字，细节丰富但不啰嗦，中性客观语气
- 表情包描述 2-10 字，口语化，捕捉核心情绪或梗
- 保留文本中所有非占位符内容不变

严格按 JSON 格式输出，processed_text 为替换后的完整文本。
