#!/usr/bin/env python3
"""
持续监控播客处理任务的进度
"""
import asyncio
import sys
import time
from datetime import datetime

sys.path.insert(0, '.')
from app.database import EpisodeRepository, IngestJobRepository

# 阶段权重配置
STAGE_WEIGHTS = {
    "download": 25,
    "transcribe": 25,
    "chapterize": 12,
    "summarize": 20,
    "highlight": 18,
    "translate": 0,
}

# 阶段名称映射
STAGE_NAMES = {
    "download": "下载",
    "transcribe": "转录",
    "chapterize": "分章",
    "summarize": "摘要",
    "highlight": "亮点",
    "translate": "翻译",
    "done": "完成",
    "pending": "等待中",
}

def calculate_progress(job):
    """计算总体进度"""
    if not job or not job.get('stages'):
        return 0

    total = 0
    current_stage = job.get('current_stage', '')

    for stage in job['stages']:
        stage_id = stage.get('name', '')
        progress = stage.get('progress', 0)

        if stage_id in STAGE_WEIGHTS:
            weight = STAGE_WEIGHTS[stage_id]
            if progress >= 1:
                total += weight
            elif stage_id == current_stage:
                total += weight * progress

    return min(total, 100)

def format_progress_bar(progress, width=30):
    """生成进度条"""
    filled = int(width * progress / 100)
    bar = '█' * filled + '░' * (width - filled)
    return f"[{bar}] {progress:.1f}%"

async def check_and_display():
    """检查并显示任务状态"""
    # 清屏（可选）
    # print("\033c", end="")

    print(f"\n{'='*70}")
    print(f"📊 播客处理任务监控 - {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*70}\n")

    # 获取所有任务
    all_episodes = await EpisodeRepository.list_all()
    processing_episodes = [ep for ep in all_episodes if ep['status'] in ['pending', 'downloading', 'asr_running', 'llm_running']]
    ready_episodes = [ep for ep in all_episodes if ep['status'] == 'ready']
    failed_episodes = [ep for ep in all_episodes if ep['status'] == 'failed']

    print(f"📈 统计: 处理中 {len(processing_episodes)} | 已完成 {len(ready_episodes)} | 失败 {len(failed_episodes)}")
    print()

    if not processing_episodes:
        print("⏸️  当前没有正在处理的任务")
        return

    for ep in processing_episodes:
        print(f"🎬 任务: {ep['title']}")
        print(f"   ID: {ep['id']}")
        print(f"   状态: {ep['status']}")
        print(f"   创建: {ep['created_at']}")

        job = await IngestJobRepository.get_by_id(ep['id'])

        if not job or not job.get('stages'):
            print("   ⏳ 等待Worker开始处理...")
            print()
            continue

        current_stage = job.get('current_stage', '')
        progress = calculate_progress(job)

        print(f"   当前阶段: {STAGE_NAMES.get(current_stage, current_stage)}")
        print(f"   总体进度: {format_progress_bar(progress)}")
        print()

        # 显示各阶段状态
        for stage in job['stages']:
            stage_id = stage.get('name', '')
            stage_progress = stage.get('progress', 0) * 100
            status_icon = "🔄" if 0 < stage_progress < 100 else "✅" if stage_progress >= 100 else "⏳"

            is_current = " ← 当前" if stage_id == current_stage else ""
            print(f"      {status_icon} {STAGE_NAMES.get(stage_id, stage_id):8s}: {stage_progress:5.1f}%{is_current}")

        print()

async def monitor_loop(interval=3):
    """持续监控循环"""
    try:
        while True:
            await check_and_display()
            print(f"⏱️  下次更新: {interval}秒后... (Ctrl+C 退出)")
            await asyncio.sleep(interval)
    except KeyboardInterrupt:
        print("\n\n👋 监控已停止")

if __name__ == "__main__":
    print("🚀 启动播客任务进度监控...")
    print("💡 提示: 使用 Ctrl+C 停止监控\n")
    asyncio.run(monitor_loop(3))
