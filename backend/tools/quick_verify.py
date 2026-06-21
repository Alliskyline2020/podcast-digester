#!/usr/bin/env python3
"""
快速验证完整降级策略实现
"""
import asyncio
import sys
sys.path.insert(0, '/Users/alli/podcast-digester/backend')

print("="*80)
print("🎯 YouTube字幕降级策略 - 快速验证")
print("="*80)

from app.sources.ytdlp_runner import fetch_youtube_subtitles
from app.utils.cookie_helper import get_available_browsers

TEST_URL = "https://www.youtube.com/watch?v=a93FT2340c0"

async def quick_test():
    # 检查可用浏览器
    browsers = get_available_browsers()
    print(f"✅ 可用浏览器: {browsers}")

    # 测试字幕获取
    print(f"\n🎬 测试URL: {TEST_URL}")
    print("-"*80)

    result = await fetch_youtube_subtitles(TEST_URL)

    print("-"*80)
    print(f"结果: {'✅ 成功' if result else '❌ 失败'}")

    if result:
        print(f"  语言: {result.language}")
        print(f"  字幕段数: {len(result.segments)}")
        print(f"  首条: {result.segments[0].text_original[:50]}...")
        print(f"  尾条: {result.segments[-1].text_original[:50]}...")

        print("\n🏆 降级策略工作正常！")
        return True
    else:
        print("\n⚠️ 所有策略都失败（将使用AFM 3 ASR）")
        return False

asyncio.run(quick_test())
