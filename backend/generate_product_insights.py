#!/usr/bin/env python3
"""
为现有节目手动生成产品洞察数据

用法:
    python generate_product_insights.py <episode_id>

示例:
    python generate_product_insights.py ep_1781977455277
"""
import asyncio
import sys
from pathlib import Path

# 添加 backend 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from app.llm_pipeline.llm_product_insights import run_product_insights_stage
from app.repositories import ProductInsightsRepository
from app.config import DATA_DIR


async def generate_for_episode(episode_id: str):
    """为指定节目生成产品洞察"""
    print(f"\n{'='*60}")
    print(f"为 {episode_id} 生成产品洞察")
    print(f"{'='*60}\n")

    try:
        # 运行产品洞察生成
        print("开始生成产品洞察...")
        product_insights = await run_product_insights_stage(
            episode_id=episode_id,
            data_dir=DATA_DIR,
            on_progress=lambda p: print(f"进度: {p*100:.1f}%"),
        )

        # 保存到数据库
        print("\n保存到数据库...")
        await ProductInsightsRepository.set(episode_id, product_insights.model_dump())

        print(f"\n✅ 成功生成并保存产品洞察！")
        print(f"\n产品洞察:")
        print(f"  - 产品洞察: {len(product_insights.product.items)} 条")
        print(f"  - 技术洞察: {len(product_insights.technical.items)} 条")
        print(f"  - 市场洞察: {len(product_insights.market.items)} 条")

        return product_insights

    except Exception as e:
        print(f"\n❌ 生成失败: {e}")
        import traceback
        traceback.print_exc()
        return None


async def list_episodes_without_insights():
    """列出所有没有产品洞察的节目"""
    import aiosqlite
    from app.config import get_db_path
    from app.database import DB_PATH

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # 获取所有节目
        cursor = await db.execute('SELECT id, title FROM episode ORDER BY created_at DESC')
        episodes = await cursor.fetchall()

        # 获取有产品洞察的节目
        cursor = await db.execute('SELECT episode_id FROM product_insights')
        with_insights = {row[0] for row in await cursor.fetchall()}

        # 找出没有产品洞察的节目
        without_insights = []
        for ep in episodes:
            if ep['id'] not in with_insights:
                without_insights.append(ep)

        if without_insights:
            print("\n缺少产品洞察的节目:")
            for ep in without_insights:
                print(f"  - {ep['id']}: {ep['title'][:50]}...")
        else:
            print("\n所有节目都有产品洞察数据")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python generate_product_insights.py <episode_id>")
        print("\n列出缺少产品洞察的节目:")
        asyncio.run(list_episodes_without_insights())
        sys.exit(1)

    episode_id = sys.argv[1]
    asyncio.run(generate_for_episode(episode_id))
