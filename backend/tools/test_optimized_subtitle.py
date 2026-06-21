#!/usr/bin/env python3
"""
验证优化后的YouTube字幕获取功能
"""
import asyncio
import sys
sys.path.insert(0, '/Users/alli/podcast-digester/backend')

from app.sources.ytdlp_runner import fetch_youtube_subtitles

TEST_URL = "https://www.youtube.com/watch?v=a93FT2340c0"

async def test():
    print("🎬 测试优化后的字幕获取功能")
    print(f"URL: {TEST_URL}\n")

    result = await fetch_youtube_subtitles(TEST_URL)

    if result:
        print(f"\n✅ 成功获取字幕！")
        print(f"   语言: {result.language if hasattr(result, 'language') else 'unknown'}")
        print(f"   字幕段数: {len(result.segments) if hasattr(result, 'segments') else 0}")

        # 显示前3条和最后3条
        if hasattr(result, 'segments') and result.segments:
            segments = result.segments
            print(f"\n   前3条:")
            for seg in segments[:3]:
                text = seg.text_original if hasattr(seg, 'text_original') else ''
                print(f"     [{seg.id if hasattr(seg, 'id') else '?'}] {text[:50]}")

            print(f"\n   最后3条:")
            for seg in segments[-3:]:
                text = seg.text_original if hasattr(seg, 'text_original') else ''
                print(f"     [{seg.id if hasattr(seg, 'id') else '?'}] {text[:50]}")
    else:
        print("\n❌ 未能获取字幕")

if __name__ == "__main__":
    asyncio.run(test())
