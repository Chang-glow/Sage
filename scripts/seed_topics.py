#!/usr/bin/env python3
"""种子话题部署脚本：插入 20-30 条初始话题，覆盖全部 10 个分类。

新部署时话题池为空，execute_external_search 返回 []，直到每天 6:00
refresh_topics_task 首次执行。此脚本预填初始数据，确保搜索立即可用。

用法: docker compose run --rm app python scripts/seed_topics.py
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.external_topic import Topic

SEED_TOPICS: list[dict[str, str]] = [
    # ── 国际局势 (3 条) ──
    {"title": "联合国大会通过气候变化新决议", "summary": "联合国大会以压倒性多数通过了一项关于气候融资的决议，要求发达国家在2030年前将气候援助资金翻倍。", "category": "国际局势"},
    {"title": "欧盟数字市场法案正式生效", "summary": "欧盟数字市场法案即日起全面执行，大型科技平台需向竞争对手开放数据接口，违规者面临全球营收10%的罚款。", "category": "国际局势"},
    {"title": "中东和平谈判取得阶段性进展", "summary": "在第三方斡旋下，中东地区多边谈判达成初步停火框架协议，各方同意在未来三个月内逐步撤军。", "category": "国际局势"},

    # ── 国内热点 (3 条) ──
    {"title": "全国高考报名人数首次突破1300万", "summary": "教育部公布2026年普通高考报名数据，全国报名人数达1320万，较去年增长约5%，创历史新高。", "category": "国内热点"},
    {"title": "新型城镇化规划发布 推进县域经济发展", "summary": "国务院发布新型城镇化五年规划，重点支持县域特色产业培育，提出到2030年县域GDP占全国比重提升至45%。", "category": "国内热点"},
    {"title": "全国铁路暑运预计发送旅客超6亿人次", "summary": "国铁集团发布暑运方案，预计7月1日至8月31日全国铁路发送旅客6.2亿人次，日均1000万人次。", "category": "国内热点"},

    # ── 娱乐新闻 (3 条) ──
    {"title": "国产科幻大片票房突破30亿", "summary": "国产科幻电影《星域迷航》上映两周票房突破30亿元，成为年度票房冠军，引发观众对国产科幻的新一轮讨论。", "category": "娱乐新闻"},
    {"title": "热门综艺节目陷入抄袭争议", "summary": "某卫视热门综艺节目被指抄袭韩国节目模式，制作方回应称已购买版权，但网友对比截图后质疑声不断。", "category": "娱乐新闻"},
    {"title": "知名歌手宣布世界巡回演唱会", "summary": "华语乐坛天后宣布将于今年秋季开启世界巡回演唱会，首站定在上海，门票预售在一分钟内售罄。", "category": "娱乐新闻"},

    # ── 二次元版 (2 条) ──
    {"title": "经典动漫重制版官宣制作决定", "summary": "经典动漫《星际牛仔》宣布将推出4K重制版，由原班制作团队操刀，预计2027年播出，引发老粉丝狂欢。", "category": "二次元版"},
    {"title": "国产动画电影入围国际动画节", "summary": "国产独立动画《山海异闻》入围安纳西国际动画电影节主竞赛单元，这是近五年来首部入围该单元的国产动画长片。", "category": "二次元版"},

    # ── 游戏版 (3 条) ──
    {"title": "国产3A大作发售首日销量破百万", "summary": "国产动作RPG《万象归墟》发售首日全平台销量突破100万份，Steam好评率达92%，成为今年评分最高的国产游戏。", "category": "游戏版"},
    {"title": "电竞赛事改革：增加女子联赛", "summary": "某知名电竞赛事联盟宣布从下赛季起增设女子联赛赛道，总奖金池达500万元，推动电竞行业性别多元化。", "category": "游戏版"},
    {"title": "云游戏平台用户数突破5000万", "summary": "国内头部云游戏平台公布最新数据，月活跃用户突破5000万，5G网络普及推动云游戏体验显著提升。", "category": "游戏版"},

    # ── 商业版 (3 条) ──
    {"title": "新能源车企集体降价引发价格战", "summary": "多家新能源车企宣布降价，最高降幅达15%，分析人士认为行业进入淘汰赛阶段，二三线品牌面临生存压力。", "category": "商业版"},
    {"title": "AI芯片初创公司完成数亿美元融资", "summary": "国产AI芯片公司寒武纪宣布完成C+轮融资，金额达5亿美元，估值突破50亿美元，计划2027年科创板上市。", "category": "商业版"},
    {"title": "跨境电商新政策：个人额度提升至5万", "summary": "海关总署发布跨境电商零售进口新规，个人年度交易限额从2.6万元提升至5万元，利好海淘消费者和跨境电商平台。", "category": "商业版"},

    # ── 当地新闻 (2 条) ──
    {"title": "社区垃圾分类达标率突破80%", "summary": "市城管局公布上半年垃圾分类考核结果，居民小区达标率首次突破80%，厨余垃圾分出量同比增长30%。", "category": "当地新闻"},
    {"title": "城市绿道三期工程竣工开放", "summary": "城市绿道三期工程正式向市民开放，新增绿道长度15公里，串联三个大型公园，成为市民休闲健身的新去处。", "category": "当地新闻"},

    # ── 文学版 (2 条) ──
    {"title": "知名作家新作获茅盾文学奖提名", "summary": "作家王安忆新作《天香续》入围本届茅盾文学奖提名名单，评委会称赞其以细腻笔触书写当代女性命运变迁。", "category": "文学版"},
    {"title": "网络文学出海：翻译作品超10万部", "summary": "中国网络文学出海平台报告显示，已翻译出海的作品超过10万部，海外读者突破1亿，东南亚和北美为最大市场。", "category": "文学版"},

    # ── 科创科普版 (2 条) ──
    {"title": "量子计算机实现1000量子比特突破", "summary": "中科院量子信息实验室宣布成功研制1000量子比特超导量子计算机，在随机线路采样任务中展现出超越经典计算机的能力。", "category": "科创科普版"},
    {"title": "基因编辑疗法首次获批临床使用", "summary": "国家药监局批准首款CRISPR基因编辑疗法上市，用于治疗β地中海贫血症，临床试验显示治愈率达90%以上。", "category": "科创科普版"},

    # ── 教育版 (2 条) ──
    {"title": "教育部推进中小学AI课程改革", "summary": "教育部发布人工智能教育指导纲要，要求全国中小学从2026年秋季学期起开设AI通识课程，培养青少年数字素养。", "category": "教育版"},
    {"title": "高校招生制度改革：综合素质评价权重提升", "summary": "多省份公布高考综合改革方案，综合素质评价在高校招生中的参考权重提升至30%，强调学生创新实践能力。", "category": "教育版"},
]


async def main():
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine)

    async with session_factory() as session:
        inserted = 0
        skipped = 0
        now = datetime.now(timezone.utc)
        for item in SEED_TOPICS:
            result = await session.execute(
                select(Topic).where(Topic.title == item["title"])
            )
            if result.scalar_one_or_none() is not None:
                skipped += 1
                continue
            topic = Topic(
                title=item["title"],
                summary=item.get("summary"),
                content=item.get("content"),
                source=item.get("source", "seed"),
                category=item["category"],
                fetched_at=now,
            )
            session.add(topic)
            inserted += 1

        await session.commit()
        print(f"种子话题: 插入 {inserted} 条, 跳过 {skipped} 条（已存在）")


if __name__ == "__main__":
    asyncio.run(main())
