#!/usr/bin/env python3
"""
YouTube字幕下载方案测试
测试4种方法获取中英文字幕的效果
"""
import os
import sys
import tempfile
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional

# 测试URL
TEST_URL = "https://www.youtube.com/watch?v=a93FT2340c0"

class MethodTester:
    """测试不同方法的工具类"""

    def __init__(self, test_url: str):
        self.test_url = test_url
        self.results = {}

    def run_command(self, cmd: list, timeout: int = 60) -> Dict:
        """执行命令并返回结果"""
        print(f"\n{'='*60}")
        print(f"命令: {' '.join(cmd)}")
        print(f"{'='*60}")

        start_time = time.time()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            elapsed = time.time() - start_time

            # 解析输出
            success = result.returncode == 0
            has_subs = False
            lang_count = {}

            if success and result.stdout:
                # 检查字幕信息
                if "subtitles" in result.stdout.lower() or "subtitle" in result.stdout.lower():
                    has_subs = True

                # 统计语言
                for line in result.stdout.split('\n'):
                    if 'zh-Hans' in line or 'zh' in line.lower():
                        lang_count['zh'] = lang_count.get('zh', 0) + 1
                    if 'en' in line.lower():
                        lang_count['en'] = lang_count.get('en', 0) + 1

            return {
                'success': success,
                'elapsed': elapsed,
                'has_subs': has_subs,
                'lang_count': lang_count,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode
            }

        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'elapsed': timeout,
                'error': '超时',
                'has_subs': False
            }
        except Exception as e:
            return {
                'success': False,
                'elapsed': time.time() - start_time,
                'error': str(e),
                'has_subs': False
            }

    def test_method_1_chrome_cookies(self) -> Dict:
        """方案1：Chrome Cookies From Browser"""
        print("\n🌟 方案1：Chrome Cookies From Browser")

        cmd = [
            "yt-dlp",
            "--cookies-from-browser", "chrome",
            "--write-subs",
            "--write-auto-subs",
            "--sub-lang", "zh-Hans,en,zh",
            "--skip-download",
            "--list-subs",
            self.test_url
        ]

        result = self.run_command(cmd, timeout=30)
        result['method'] = 'Chrome Cookies'
        result['po_token_issue'] = 'PO token' in result.get('stderr', '') or 'missing subtitle' in result.get('stderr', '').lower()

        return result

    def test_method_2_safari_cookies(self) -> Dict:
        """方案1b：Safari Cookies From Browser"""
        print("\n🌟 方案1b：Safari Cookies From Browser")

        cmd = [
            "yt-dlp",
            "--cookies-from-browser", "safari",
            "--write-subs",
            "--write-auto-subs",
            "--sub-lang", "zh-Hans,en,zh",
            "--skip-download",
            "--list-subs",
            self.test_url
        ]

        result = self.run_command(cmd, timeout=30)
        result['method'] = 'Safari Cookies'
        result['po_token_issue'] = 'PO token' in result.get('stderr', '') or 'missing subtitle' in result.get('stderr', '').lower()

        return result

    def test_method_3_manual_cookies(self) -> Dict:
        """方案2：手动导出Cookie文件"""
        print("\n🌟 方案2：手动Cookie文件")

        # 检查是否有cookie文件
        cookie_paths = [
            Path.home() / ".config" / "podcast-digester" / "youtube_cookies.txt",
            Path.home() / "Downloads" / "cookies.txt",
            Path("cookies.txt")
        ]

        cookie_file = None
        for path in cookie_paths:
            if path.exists():
                cookie_file = path
                print(f"找到cookie文件: {cookie_file}")
                break

        if not cookie_file:
            print("❌ 未找到cookie文件，跳过此测试")
            return {
                'method': 'Manual Cookies',
                'success': False,
                'error': '未找到cookie文件',
                'has_subs': False
            }

        cmd = [
            "yt-dlp",
            "--cookies", str(cookie_file),
            "--write-subs",
            "--write-auto-subs",
            "--sub-lang", "zh-Hans,en,zh",
            "--skip-download",
            "--list-subs",
            self.test_url
        ]

        result = self.run_command(cmd, timeout=30)
        result['method'] = 'Manual Cookies'
        result['cookie_file'] = str(cookie_file)

        return result

    def test_method_4_no_cookies(self) -> Dict:
        """方案0：无Cookie（基线对比）"""
        print("\n🌟 方案0：无Cookie（基线）")

        cmd = [
            "yt-dlp",
            "--write-subs",
            "--write-auto-subs",
            "--sub-lang", "zh-Hans,en,zh",
            "--skip-download",
            "--list-subs",
            self.test_url
        ]

        result = self.run_command(cmd, timeout=30)
        result['method'] = 'No Cookies (Baseline)'
        result['po_token_issue'] = 'PO token' in result.get('stderr', '') or 'missing subtitle' in result.get('stderr', '').lower()

        return result

    def print_results(self, results: list):
        """打印测试结果对比"""
        print("\n" + "="*80)
        print("📊 测试结果对比")
        print("="*80)

        headers = ["方案", "成功", "耗时", "有字幕", "中文字幕", "英文字幕", "PO Token问题", "错误信息"]
        rows = []

        for r in results:
            method = r.get('method', 'Unknown')
            success = "✅" if r.get('success') else "❌"
            elapsed = f"{r.get('elapsed', 0):.2f}s"
            has_subs = "✅" if r.get('has_subs') else "❌"
            zh_count = r.get('lang_count', {}).get('zh', 0)
            en_count = r.get('lang_count', {}).get('en', 0)
            po_issue = "⚠️" if r.get('po_token_issue') else "✅"
            error = (r.get('stderr', '') or r.get('error', ''))[:50]

            rows.append([
                method, success, elapsed, has_subs,
                f"{'✅' if zh_count > 0 else '❌'}",
                f"{'✅' if en_count > 0 else '❌'}",
                po_issue, error
            ])

        # 打印表格
        col_widths = [25, 8, 10, 8, 12, 12, 15, 30]

        # 表头
        header_row = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))
        print(header_row)
        print("-" * len(header_row))

        # 数据行
        for row in rows:
            print("  ".join(str(str(r).ljust(w)) for r, w in zip(row, col_widths)))

        print("="*80)

        # 推荐方案
        print("\n🏆 推荐方案:")
        successful = [r for r in results if r.get('success') and r.get('has_subs')]

        if successful:
            fastest = min(successful, key=lambda x: x.get('elapsed', 999))
            print(f"  ⭐ 最快: {fastest.get('method')} ({fastest.get('elapsed', 0):.2f}s)")

            # 检查中英文字幕
            for r in successful:
                langs = r.get('lang_count', {})
                has_zh = langs.get('zh', 0) > 0
                has_en = langs.get('en', 0) > 0
                if has_zh and has_en:
                    print(f"  ✅ 完整支持: {r.get('method')} (中英文字幕都有)")
        else:
            print("  ❌ 所有方案都失败了，需要PO token或其他认证")

        print("\n")


def main():
    """主函数"""
    print("🎬 YouTube字幕下载方案测试")
    print(f"测试视频: {TEST_URL}")

    tester = MethodTester(TEST_URL)

    # 运行所有测试
    results = []

    # 基线测试
    results.append(tester.test_method_4_no_cookies())

    # Chrome cookies
    results.append(tester.test_method_1_chrome_cookies())

    # Safari cookies
    results.append(tester.test_method_2_safari_cookies())

    # 手动cookie
    results.append(tester.test_method_3_manual_cookies())

    # 打印结果
    tester.print_results(results)

    # 详细输出
    print("\n📝 详细输出:")
    for r in results:
        print(f"\n{'='*60}")
        print(f"方案: {r.get('method')}")
        print(f"{'='*60}")
        if r.get('stdout'):
            print("STDOUT:")
            print(r.get('stdout', '')[:500])
        if r.get('stderr'):
            print("\nSTDERR:")
            print(r.get('stderr', '')[:500])


if __name__ == "__main__":
    main()
