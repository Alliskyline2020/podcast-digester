#!/usr/bin/env python3
"""
测试词库纠错功能

演示如何使用专业词库进行字幕纠错
"""
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from app.services.glossary import Glossary, get_glossary
from app.utils.io import safe_read_json, atomic_write_json


def test_glossary():
    """测试词库功能"""
    print("\n" + "="*60)
    print("📚 词库纠错系统测试")
    print("="*60 + "\n")

    # 1. 初始化词库
    data_dir = Path("../data")
    glossary = Glossary(data_dir)

    print("1️⃣  当前词库内容:")
    print("-" * 40)
    entries = glossary.get_all_entries()
    for correct, wrong_list in entries.items():
        print(f"   {correct} ← {', '.join(wrong_list)}")

    # 2. 测试文本纠错
    print("\n2️⃣  测试文本纠错:")
    print("-" * 40)

    test_cases = [
        "大家好，我是小军。",
        "今天我们来到了妞约。",
        "讨论人工只能的发展。",
        "这是赛宁教授。"
    ]

    for text in test_cases:
        corrected = glossary.correct_text(text)
        if corrected != text:
            print(f"   ✏️  {text}")
            print(f"   →   {corrected}")
        else:
            print(f"   ✓   {text}")

    # 3. 查找错误
    print("\n3️⃣  在文本中查找错误:")
    print("-" * 40)

    sample_text = "小军今天来到妞约，和赛宁讨论人工只能。"
    mistakes = glossary.find_mistakes(sample_text)

    print(f"   文本: {sample_text}")
    if mistakes:
        print(f"   发现 {len(mistakes)} 个错误:")
        for m in mistakes:
            print(f"   - 位置 {m['position']}: '{m['wrong']}' → '{m['correct']}'")
    else:
        print("   ✓ 未发现错误")

    # 4. 添加新词库条目
    print("\n4️⃣  添加新词库条目:")
    print("-" * 40)

    print("   添加: 李开复 ← ['开复', '凯富']")
    glossary.add_entry("李开复", ["开复", "凯富"])

    # 验证添加
    test_text = "今天和凯富讨论AI"
    corrected = glossary.correct_text(test_text)
    print(f"   测试: {test_text}")
    print(f"   纠正: {corrected}")

    # 5. 纠正完整字幕文件
    print("\n5️⃣  纠正完整字幕文件:")
    print("-" * 40)

    episode_id = "ep_1781109978390"
    transcript_file = data_dir / "media" / episode_id / "transcript.json"

    if transcript_file.exists():
        transcript_data = safe_read_json(transcript_file)

        if transcript_data:
            segments = transcript_data.get("segments", [])
            print(f"   节目: {episode_id}")
            print(f"   总segments: {len(segments)}")

            # 纠正
            corrected_data, corrected_count = glossary.correct_transcript(transcript_data)

            print(f"   纠正了: {corrected_count} 条")

            # 显示前5条纠正
            corrections = []
            for i, seg in enumerate(corrected_data["segments"][:20]):
                if seg.get("text_corrected"):
                    original = segments[i].get("text_original", "")
                    corrected = seg.get("text_original", "")
                    corrections.append({
                        "index": i,
                        "original": original,
                        "corrected": corrected
                    })

            if corrections:
                print("\n   纠正示例:")
                for c in corrections[:5]:
                    print(f"   [{c['index']}] {c['original']}")
                    print(f"        → {c['corrected']}")

            # 可选：保存纠正后的文件（注释掉以防覆盖）
            # atomic_write_json(transcript_file, corrected_data)
            # print(f"\n   💾 已保存到: {transcript_file}")
    else:
        print(f"   ⚠️  未找到字幕文件: {transcript_file}")

    print("\n" + "="*60)
    print("✅ 测试完成")
    print("="*60 + "\n")


if __name__ == "__main__":
    test_glossary()
