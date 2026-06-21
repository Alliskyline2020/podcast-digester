#!/usr/bin/env python3
"""测试新的日志格式"""
import asyncio
import sys
import logging
sys.path.insert(0, '/Users/alli/podcast-digester/backend')

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'  # 简洁格式
)

from app.sources.ytdlp_runner import fetch_youtube_subtitles

TEST_URL = "https://www.youtube.com/watch?v=a93FT2340c0"

async def test():
    print("="*60)
    print("测试新的日志格式")
    print("="*60)
    print()

    result = await fetch_youtube_subtitles(TEST_URL)

    print()
    print("="*60)
    if result:
        print(f"✅ 获取成功: {len(result.segments)} segments")
    else:
        print("❌ 获取失败")
    print("="*60)

asyncio.run(test())
