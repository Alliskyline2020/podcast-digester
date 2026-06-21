#!/usr/bin/env python3
"""
直接测试 YouTube 字幕下载和 Cookie 策略
"""
import asyncio
import sys
import logging

sys.path.insert(0, '.')
from app.sources.ytdlp_runner import fetch_youtube_subtitles
from app.utils.cookie_helper import get_best_browser, find_cookies_txt

# 设置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_subtitle_fetch():
    url = "https://www.youtube.com/watch?v=rIwgZWzUKm8"

    print("=" * 60)
    print("🧪 测试 YouTube 字幕下载 + Cookie 策略")
    print("=" * 60)
    print(f"📺 视频: {url}")
    print()

    # 检测 Cookie 可用性
    print("🔍 Cookie 检测:")
    best_browser = get_best_browser()
    cookies_txt = find_cookies_txt()

    if best_browser:
        print(f"  ✅ 浏览器 Cookies: {best_browser}")
    else:
        print(f"  ❌ 浏览器 Cookies: 无")

    if cookies_txt:
        print(f"  ✅ cookies.txt: {cookies_txt}")
    else:
        print(f"  ❌ cookies.txt: 无")

    print()
    print("🚀 开始测试字幕下载...")
    print("-" * 60)

    # 调用字幕获取函数
    result = await fetch_youtube_subtitles(url)

    print("-" * 60)
    if result:
        print(f"✅ 成功获取字幕!")
        print(f"   语言: {result.language}")
        print(f"   片段数: {len(result.segments)}")
        print(f"   前3个片段:")
        for seg in result.segments[:3]:
            start_sec = seg.start_ms / 1000
            text_preview = seg.text_original[:50] + "..." if len(seg.text_original) > 50 else seg.text_original
            print(f"      [{start_sec:.2f}s] {text_preview}")
    else:
        print("❌ 字幕获取失败")

    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_subtitle_fetch())
