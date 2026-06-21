#!/usr/bin/env python3
"""
测试YouTube字幕获取的完整降级策略
验证6个策略的降级链是否正常工作
"""
import asyncio
import sys
sys.path.insert(0, '/Users/alli/podcast-digester/backend')

from app.sources.ytdlp_runner import fetch_youtube_subtitles
from app.utils.cookie_helper import get_available_browsers

TEST_URL = "https://www.youtube.com/watch?v=a93FT2340c0"

async def test():
    print("=" * 80)
    print("🎬 YouTube字幕获取 - 完整降级策略测试")
    print("=" * 80)

    print(f"\n测试URL: {TEST_URL}")

    # 显示可用浏览器
    browsers = get_available_browsers()
    print(f"\n📊 可用浏览器: {browsers}")

    print("\n" + "=" * 80)
    print("开始执行降级策略测试...")
    print("=" * 80)

    result = await fetch_youtube_subtitles(TEST_URL)

    print("\n" + "=" * 80)
    print("📊 最终结果")
    print("=" * 80)

    if result:
        print(f"✅ 成功获取字幕！")
        print(f"   语言: {result.language}")
        print(f"   字幕段数: {len(result.segments)}")

        # 显示字幕样本
        if result.segments:
            print(f"\n📝 字幕样本:")
            print(f"   首条: [{result.segments[0].text_original[:60]}...")
            print(f"   尾条: [{result.segments[-1].text_original[:60]}...")

        print(f"\n🏆 使用的策略: 查看上方日志中的 '✅ 策略X成功' 消息")
    else:
        print("❌ 所有策略都失败")
        print("💡 系统将使用 AFM 3 ASR 进行转录")

    print("\n" + "=" * 80)
    print("降级策略说明:")
    print("=" * 80)
    print("""
策略1 (最优): Chrome Cookies - 成功率100%
    ↓ 失败
策略2 (备用): Edge Cookies - 备用浏览器
    ↓ 失败
策略3 (备用): Safari Cookies - 需Full Disk Access
    ↓ 失败
策略4 (手动): Cookies.txt文件 - 需手动导出
    ↓ 失败
策略5 (降级): No Cookies - Web客户端
    ↓ 失败
策略6 (最后): No Cookies - 移动端客户端
    ↓ 全部失败
返回None → 使用AFM 3 ASR
    """)

if __name__ == "__main__":
    asyncio.run(test())
