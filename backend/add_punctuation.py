"""
手动为现有字幕添加标点符号

用法：
    python add_punctuation.py <episode_id>

示例：
    python add_punctuation.py ep_1781977455277
"""
import sys
import asyncio
from pathlib import Path
import json

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from app.services.punctuation_restorer import punctuation_restorer
from app.config import DATA_DIR


async def add_punctuation_to_episode(episode_id: str):
    """为指定节目的字幕添加标点符号"""
    print(f"=== 为 {episode_id} 添加标点符号 ===\n")

    # 读取transcript文件
    transcript_file = DATA_DIR / "media" / episode_id / "transcript.json"

    if not transcript_file.exists():
        print(f"错误：找不到字幕文件 {transcript_file}")
        return

    with open(transcript_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    segments = data.get("segments", [])
    if not segments:
        print("错误：字幕文件中没有段落")
        return

    print(f"读取到 {len(segments)} 个段落")

    # 检查是否已经有标点
    has_punct = sum(
        1 for seg in segments
        if any(c in seg.get("text_original", "") for c in "。！？，、；：,.!?")
    )
    punct_ratio = has_punct / len(segments)

    print(f"当前有标点段落: {has_punct}/{len(segments)} ({punct_ratio*100:.1f}%)")

    if punct_ratio > 0.5:
        confirm = input("\n字幕已经有很多标点符号，是否继续处理？(y/n): ")
        if confirm.lower() != 'y':
            print("已取消")
            return

    print("\n开始添加标点符号...")

    def progress_callback(progress: float):
        """显示进度"""
        percent = int(progress * 100)
        bar_length = 40
        filled = int(bar_length * progress)
        bar = '█' * filled + '░' * (bar_length - filled)
        print(f'\r[{bar}] {percent}%', end='', flush=True)

    try:
        # 处理字幕
        punctuated_segments = await punctuation_restorer.restore_punctuation(
            segments,
            episode_id,
            progress_callback
        )
        print()  # 换行

        # 更新数据
        data["segments"] = punctuated_segments

        # 保存
        with open(transcript_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"\n✅ 完成！已更新 {transcript_file}")

        # 验证
        has_punct_after = sum(
            1 for seg in data["segments"]
            if any(c in seg.get("text_with_punct", "") for c in "。！？，、；：,.!?")
        )
        print(f"处理后有标点段落: {has_punct_after}/{len(data['segments'])}")

        # 显示样本
        print("\n=== 样本对比 ===")
        for i in range(min(3, len(data["segments"]))):
            seg = data["segments"][i]
            original = seg.get("text_original", "")
            with_punct = seg.get("text_with_punct", "")
            print(f"\n段落 {i}:")
            print(f"  原文: {original}")
            print(f"  标点: {with_punct}")

    except Exception as e:
        print(f"\n❌ 处理失败: {e}")
        import traceback
        traceback.print_exc()


async def list_episodes():
    """列出所有可以处理的节目"""
    media_dir = DATA_DIR / "media"

    if not media_dir.exists():
        print("错误：媒体目录不存在")
        return

    episode_dirs = [d for d in media_dir.iterdir() if d.is_dir() and d.name.startswith("ep_")]

    print(f"=== 可处理的节目 ({len(episode_dirs)}) ===\n")

    for ep_dir in sorted(episode_dirs):
        transcript_file = ep_dir / "transcript.json"
        if transcript_file.exists():
            try:
                with open(transcript_file) as f:
                    data = json.load(f)
                segments = data.get("segments", [])
                has_punct = sum(
                    1 for seg in segments
                    if any(c in seg.get("text_original", "") for c in "。！？，、；：,.!?")
                )
                punct_ratio = has_punct / len(segments) if segments else 0
                status = "✓ 有标点" if punct_ratio > 0.5 else "✗ 无标点"
                print(f"{ep_dir.name:30} {len(segments):4} 段落  {status}")
            except Exception as e:
                print(f"{ep_dir.name:30} 读取失败: {e}")


async def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python add_punctuation.py <episode_id>     # 为指定节目添加标点")
        print("  python add_punctuation.py --list            # 列出所有节目")
        print("\n示例:")
        print("  python add_punctuation.py ep_1781977455277")
        print("  python add_punctuation.py --list")
        return

    arg = sys.argv[1]

    if arg == "--list":
        await list_episodes()
    else:
        await add_punctuation_to_episode(arg)


if __name__ == "__main__":
    asyncio.run(main())
