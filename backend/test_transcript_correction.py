#!/usr/bin/env python3
"""
测试字幕纠错功能

用法:
1. 启动后端服务
2. 运行此脚本: python test_transcript_correction.py
"""
import asyncio
import sys
import os
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

import httpx


async def test_correction(episode_id: str):
    """测试字幕纠错"""
    base_url = "http://localhost:8000"

    print(f"\n{'='*60}")
    print(f"测试字幕纠错功能 - Episode: {episode_id}")
    print(f"{'='*60}\n")

    async with httpx.AsyncClient() as client:
        # 1. 调用纠错API
        print("📝 调用字幕纠错API...")
        response = await client.post(
            f"{base_url}/api/episodes/{episode_id}/correct-transcript"
        )

        if response.status_code == 200:
            result = response.json()
            print(f"✅ 纠错完成！")
            print(f"   - 总segments: {result['total_segments']}")
            print(f"   - 纠错segments: {result['corrected_segments']}")
            print(f"   - 耗时: {result['duration_ms']}ms")
        else:
            print(f"❌ 纠错失败: {response.status_code}")
            print(f"   错误信息: {response.text}")
            return

        # 2. 读取纠正后的transcript查看效果
        print(f"\n📖 查看纠正后的字幕（前10条）:")
        transcript_file = Path("../data/media") / episode_id / "transcript.json"
        if transcript_file.exists():
            import json
            with open(transcript_file, 'r', encoding='utf-8') as f:
                transcript = json.load(f)

            segments = transcript.get('segments', [])[:10]
            for i, seg in enumerate(segments, 1):
                text = seg.get('text_original', '')
                corrected = seg.get('text_corrected', False)
                mark = '✨' if corrected else '  '
                print(f"   {mark} {i}. {text}")

        print(f"\n✨ 完成！完整的纠错结果已保存到: {transcript_file}")


if __name__ == "__main__":
    # 使用张小珺的节目测试
    episode_id = "ep_1781109978390"

    print("字幕纠错测试工具")
    print(f"测试节目ID: {episode_id}")
    print("\n提示：确保后端服务已启动 (uvicorn app.main:app --reload)")

    input("\n按Enter键开始测试...")

    asyncio.run(test_correction(episode_id))
