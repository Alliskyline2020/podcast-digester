#!/usr/bin/env python3
"""
前端API测试工具
帮助诊断字幕编辑器问题
"""
import sys
import json
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'app'))

print("\n" + "="*60)
print("🔧 前端API诊断工具")
print("="*60)

# 1. 检查词库API
print("\n1️⃣ 检查词库API")
print("-" * 40)

try:
    import requests
    response = requests.post('http://localhost:8000/api/glossary/entries', timeout=5)
    print(f"   状态码: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        print(f"   返回格式正确: {list(data.keys())}")
        print(f"   词库条目数: {len(data.get('entries', {}))}")

        entries = data.get('entries', {})
        if entries:
            print(f"   前3个条目:")
            for i, (correct, wrong_list) in enumerate(list(entries.items())[:3]):
                print(f"     {i+1}. {correct} ← {', '.join(wrong_list)}")
        else:
            print("   ⚠️  词库为空")
    else:
        print(f"   ❌ API请求失败: {response.text}")
except Exception as e:
    print(f"   ❌ 错误: {e}")

# 2. 检查特定节目的transcript
print("\n2️⃣ 检查transcript文件")
print("-" * 40)

episode_id = "ep_1781109978390"
transcript_file = Path('data') / "media" / episode_id / "transcript.json"

if transcript_file.exists():
    print(f"   ✅ 文件存在: {transcript_file}")

    with open(transcript_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        segments = data.get('segments', [])
        print(f"   总segments数: {len(segments)}")

        if segments:
            print(f"   前3个segments:")
            for i, seg in enumerate(segments[:3]):
                text = seg.get('text_original', '')
                print(f"     [{i+1}] {text}")

            # 检查是否包含错误词
            errors_found = []
            for i, seg in enumerate(segments):
                text = seg.get('text_original', '')
                if '小军' in text or '张小君' in text:
                    errors_found.append(i)
                    if len(errors_found) <= 3:
                        print(f"   ⚠️  Segment {i+1} 包含错误词: {text}")

            if errors_found:
                print(f"\n   🔍 发现 {len(errors_found)} 个包含错误词的segments")
                print(f"   这些将被标记为黄色高亮，并可快速纠错")
            else:
                print(f"   ℹ️  前3个segments中没有发现错误词（'小军', '张小君'）")
        else:
            print("   ⚠️  没有segments")
else:
    print(f"   ❌ 文件不存在: {transcript_file}")

# 3. 测试应用词库API
print("\n3️⃣ 测试应用词库API")
print("-" * 40)

try:
    import requests
    response = requests.post(
        f'http://localhost:8000/api/episodes/{episode_id}/apply-glossary',
        timeout=10
    )
    print(f"   状态码: {response.status_code}")

    if response.status_code == 200:
        result = response.json()
        print(f"   ✅ 纠错成功!")
        print(f"   总segments: {result.get('total_segments')}")
        print(f"   纠正segments: {result.get('corrected_segments')}")
        print(f"   耗时: {result.get('duration_ms')}ms")
    else:
        print(f"   ❌ 纠错失败: {response.text}")
except Exception as e:
    print(f"   ❌ 错误: {e}")

# 4. 检查词库文件
print("\n4️⃣ 检查词库文件")
print("-" * 40)

glossary_file = Path('data') / 'glossary.json'
if glossary_file.exists():
    print(f"   ✅ 词库文件存在: {glossary_file}")

    with open(glossary_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        entries = data.get('entries', {})
        print(f"   词库条目数: {len(entries)}")
else:
    print(f"   ⚠️  词库文件不存在: {glossary_file}")
    print("   (将在首次使用时自动创建)")

print("\n" + "="*60)
print("🔍 诊断完成")
print("="*60 + "\n")

# 5. 提供解决方案建议
print("💡 可能的解决方案:")
print("")
print("如果词库API正常，但前端看不到词库:")
print("  1. 刷新浏览器页面 (Ctrl+Shift+R 强制刷新)")
print("  2. 打开浏览器开发者工具 (F12)")
print("  3. 查看Console标签的调试信息")
print("  4. 检查是否有JavaScript错误")
print("")
print("如果一键纠错不生效:")
print("  1. 检查transcript.json文件是否存在")
print("  2. 检查文件中是否包含词库中的错误词")
print("  3. 查看Console的错误信息")
print("")
print("如果transcript文件不存在:")
print("  - 需要先完成转录才能编辑字幕")
print("  - 检查节目状态是否为'completed'")
