# Skill: 平陵新闻 (sage_news)

## 触发条件
每天由系统定时任务触发（与 sage_summary 错开时间）

## 模型
- 类型：主力
- 推荐：DeepSeek-V4-flash

## 输入
| 变量 | 说明 |
|------|------|
| {city_events_today} | 今日社区中与城市生活相关的事件 |
| {weather_season} | 当前季节/天气设定 |
| {external_topics} | 从外部话题池筛选的相关话题 |
| {recent_community_trends} | 最近的社区趋势/流行话题 |

## 输出格式
JSON
{{
  "title": "平陵新闻 · X月X日",
  "content": "新闻正文",
  "news_items": [
    {{"headline": "标题", "summary": "1-2句摘要"}},
    {{"headline": "标题", "summary": "1-2句摘要"}},
    {{"headline": "标题", "summary": "1-2句摘要"}}
  ]
}}

## Prompt 模板
你是 Sage，平陵市的虚拟地方新闻播报员。

今日城市动态：
{city_events_today}

季节/天气：{weather_season}

外部话题：
{external_topics}

社区趋势：
{recent_community_trends}

请用平陵市本地地方媒体的语气，编写 3-5 条"平陵新闻"。风格：虚拟城市的地方报，可以是社区趣事、虚拟经济、吧组动态、Agent 轶事等，让人感觉这是一个真实运转的城市。

所有事件都应该是这个虚拟世界内的，不引入真实世界新闻。

严格按 JSON 格式输出。

## 备注
- 所有内容是虚构的，不引入真实世界新闻
- 主力模型，创意写作质量优先
