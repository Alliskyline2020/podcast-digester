#!/usr/bin/env python3
"""
完整链路测试脚本
测试从 URL 提交到处理完成的全流程
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from app.database import init_db, EpisodeRepository, IngestJobRepository
from app.ingest import pipeline
from app.models import EpisodeStatus


async def test_full_chain():
    """测试完整链路"""
    print("\n" + "="*60)
    print("🧪 完整链路测试")
    print("="*60)

    # 1. 初始化数据库
    print("\n1️⃣ 初始化数据库...")
    await init_db()
    print("   ✅ 数据库初始化完成")

    # 2. 提交测试任务
    test_cases = [
        {
            "name": "YouTube",
            "url": "https://www.youtube.com/watch?v=rIwgZWzUKm8",
            "expected_title": "YouTube视频",
        },
        {
            "name": "小宇宙",
            "url": "https://www.xiaoyuzhoufm.com/episode/6a1ed39db30e1571ae9f85ee",
            "expected_title": "小宇宙播客",
        },
        {
            "name": "Bilibili",
            "url": "https://bilibili.com/video/BV1dyE86bENz",
            "expected_title": "Bilibili视频",
        },
    ]

    results = []

    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{i}. 测试 {test_case['name']}")
        print(f"   URL: {test_case['url']}")

        episode_id = f"test_{test_case['name'].lower()}_{i}"

        # 创建 episode 记录
        await EpisodeRepository.create({
            "id": episode_id,
            "title": f"处理中... - {test_case['name']}",
            "status": EpisodeStatus.PENDING.value,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        })

        # 创建 ingest_job
        await IngestJobRepository.create(episode_id)

        print(f"   ✅ 任务已创建: {episode_id}")

        # 运行 ingest（设置超时）
        try:
            # 设置5分钟超时
            await asyncio.wait_for(
                pipeline.run_ingest(episode_id, test_case['url']),
                timeout=300.0
            )

            # 检查结果
            ep = await EpisodeRepository.get_by_id(episode_id)

            if ep['status'] == EpisodeStatus.READY.value:
                print(f"   ✅ 处理成功!")
                print(f"   标题: {ep['title']}")
                print(f"   语言: {ep.get('language', 'N/A')}")

                # 检查生成的文件
                media_dir = Path(__file__).parent.parent / "data" / "media" / episode_id
                files = list(media_dir.glob("*.json"))
                print(f"   生成文件: {len(files)} 个")

                results.append({
                    "name": test_case['name'],
                    "status": "SUCCESS",
                    "episode_id": episode_id,
                    "title": ep['title'],
                })

            elif ep['status'] == EpisodeStatus.FAILED.value:
                print(f"   ❌ 处理失败")
                print(f"   错误: {ep.get('error_msg', 'N/A')}")

                results.append({
                    "name": test_case['name'],
                    "status": "FAILED",
                    "episode_id": episode_id,
                    "error": ep.get('error_msg', 'Unknown error'),
                })

        except asyncio.TimeoutError:
            print(f"   ⏱️ 处理超时（5分钟）")
            results.append({
                "name": test_case['name'],
                "status": "TIMEOUT",
                "episode_id": episode_id,
            })

        except Exception as e:
            print(f"   ❌ 异常: {e}")
            import traceback
            traceback.print_exc()

            results.append({
                "name": test_case['name'],
                "status": "ERROR",
                "episode_id": episode_id,
                "error": str(e),
            })

    # 3. 输出测试总结
    print("\n" + "="*60)
    print("📊 测试总结")
    print("="*60)

    for result in results:
        status_emoji = {
            "SUCCESS": "✅",
            "FAILED": "❌",
            "TIMEOUT": "⏱️",
            "ERROR": "💥",
        }.get(result['status'], "❓")

        print(f"{status_emoji} {result['name']}: {result['status']}")
        if 'error' in result:
            print(f"   错误: {result['error']}")
        if 'title' in result:
            print(f"   标题: {result['title']}")

    success_count = sum(1 for r in results if r['status'] == 'SUCCESS')
    print(f"\n成功率: {success_count}/{len(results)} ({success_count*100//len(results)}%)")


if __name__ == "__main__":
    try:
        asyncio.run(test_full_chain())
    except KeyboardInterrupt:
        print("\n\n⚠️ 测试被用户中断")
    except Exception as e:
        print(f"\n\n💥 测试脚本异常: {e}")
        import traceback
        traceback.print_exc()
