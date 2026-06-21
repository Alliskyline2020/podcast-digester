#!/usr/bin/env python3
"""
持续监控播客处理任务
"""
import asyncio
import sys
import time
from datetime import datetime

sys.path.insert(0, '.')
from app.database import EpisodeRepository, IngestJobRepository

EPISODE_ID = 'ep_1781067085814'

def get_progress_bar(progress):
    """生成进度条"""
    filled = int(30 * progress)
    bar = '█' * filled + '░' * (30 - filled)
    return f"[{bar}] {progress*100:.1f}%"

async def monitor():
    last_stages = None

    while True:
        try:
            ep = await EpisodeRepository.get_by_id(EPISODE_ID)
            if not ep:
                print("❌ 任务不存在")
                break

            job = await IngestJobRepository.get_by_id(EPISODE_ID)

            # 清屏并显示状态
            print("\033c", end="")
            print(f"📊 监控任务: {ep['title']} ({EPISODE_ID})")
            print(f"⏰ 时间: {datetime.now().strftime('%H:%M:%S')}")
            print(f"⚡ 状态: {ep['status']}")

            if job and job.get('stages'):
                current = job.get('current_stage', 'unknown')
                print(f"📍 当前阶段: {current}")

                # 检查是否有变化
                if job['stages'] != last_stages:
                    print("\n📈 阶段进度:")
                    for stage in job['stages']:
                        prog = stage.get('progress', 0)
                        icon = "🔄" if 0 < prog < 1 else "✅" if prog >= 1 else "⏳"
                        is_curr = " ← 当前" if stage['name'] == current else ""
                        print(f"  {icon} {stage['name']}: {prog*100:5.1f}%{is_curr}")
                    last_stages = job['stages']

                    # 计算总体进度
                    weights = {'download': 25, 'transcribe': 25, 'chapterize': 12, 'summarize': 20, 'highlight': 18}
                    total = 0
                    for s in job['stages']:
                        sid = s['name']
                        if sid in weights:
                            if s['progress'] >= 1:
                                total += weights[sid]
                            elif sid == current and s['progress'] > 0:
                                total += weights[sid] * s['progress']
                    print(f"\n📊 总体进度: {get_progress_bar(min(total/100, 1))}")
                else:
                    print("\n✨ 进度未变化")
            else:
                print("⏳ 等待ingest_job创建...")

            print("\n⏱️  5秒后刷新...")
            await asyncio.sleep(5)

        except Exception as e:
            print(f"❌ 错误: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(monitor())
    except KeyboardInterrupt:
        print("\n👋 监控已停止")
