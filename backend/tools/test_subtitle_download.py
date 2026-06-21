#!/usr/bin/env python3
"""
实际下载字幕并验证内容
"""
import subprocess
import tempfile
import json
from pathlib import Path

TEST_URL = "https://www.youtube.com/watch?v=a93FT2340c0"

def test_download_subtitles(method: str, use_cookies: bool = False):
    """测试下载字幕"""
    print(f"\n{'='*60}")
    print(f"测试: {method}")
    print(f"{'='*60}")

    # 创建临时目录
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # 构建命令
        cmd = [
            "yt-dlp",
            "--write-subs",
            "--write-auto-subs",
            "--sub-lang", "zh-Hans,en,zh",
            "--sub-format", "json3",  # JSON格式便于解析
            "--skip-download",
            "-o", str(tmpdir / "%(title)s.%(ext)s"),
            TEST_URL
        ]

        if use_cookies:
            cmd.insert(1, "--cookies-from-browser")
            cmd.insert(2, "chrome")

        print(f"命令: {' '.join(cmd)}")

        # 执行
        result = subprocess.run(cmd, capture_output=True, text=True)

        print(f"\n返回码: {result.returncode}")

        # 查找生成的字幕文件
        sub_files = list(tmpdir.glob("*.zh-Hans.json3")) + list(tmpdir.glob("*.en.json3"))

        print(f"\n找到字幕文件: {len(sub_files)}")

        for f in sub_files:
            print(f"  - {f.name}")
            size_kb = f.stat().st_size / 1024
            print(f"    大小: {size_kb:.2f} KB")

            # 读取并解析内容
            try:
                with open(f, 'r', encoding='utf-8') as fp:
                    data = json.load(fp)

                events = data.get('events', [])
                print(f"    事件数: {len(events)}")

                if events:
                    # 获取第一句和最后一句
                    first_text = events[0].get('segs', [{}])[0].get('utf8', '')
                    last_text = events[-1].get('segs', [{}])[0].get('utf8', '')

                    print(f"    首句: {first_text[:50]}...")
                    print(f"    尾句: {last_text[:50]}...")

            except Exception as e:
                print(f"    解析错误: {e}")

        print(f"\nSTDOUT (前500字符):")
        print(result.stdout[:500])

        if result.stderr:
            print(f"\nSTDERR (前500字符):")
            print(result.stderr[:500])

        return len(sub_files) > 0

def main():
    print("🎬 实际下载字幕测试")
    print(f"视频: {TEST_URL}\n")

    # 测试无cookie
    no_cookie_success = test_download_subtitles("无Cookie (Baseline)", use_cookies=False)

    # 测试Chrome cookie
    chrome_success = test_download_subtitles("Chrome Cookies", use_cookies=True)

    # 总结
    print("\n" + "="*60)
    print("📊 总结")
    print("="*60)
    print(f"无Cookie: {'✅ 成功' if no_cookie_success else '❌ 失败'}")
    print(f"Chrome Cookies: {'✅ 成功' if chrome_success else '❌ 失败'}")

    if chrome_success:
        print("\n🏆 推荐使用 Chrome Cookies 方案")
    elif no_cookie_success:
        print("\n⚠️ Cookie方案失败，回退到无Cookie方案")

if __name__ == "__main__":
    main()
