#!/usr/bin/env python3
"""
快速添加词库条目的交互式脚本
"""
import sys
import json
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

def add_glossary_entry():
    """交互式添加词库"""
    print("\n" + "="*60)
    print("📚 添加词库条目")
    print("="*60)

    correct = input("正确的词汇（如：张小珺）: ").strip()
    if not correct:
        print("❌ 正确词汇不能为空")
        return

    wrong_input = input("错误的词汇，多个用逗号分隔（如：小军,张小君）: ").strip()
    wrong_list = [w.strip() for w in wrong_input.split(',') if w.strip()]

    if not wrong_list:
        print("❌ 至少需要一个错误词汇")
        return

    # 显示预览
    print(f"\n预览：")
    print(f"  正确词: {correct}")
    print(f"  错误词: {', '.join(wrong_list)}")

    confirm = input("\n确认添加？(y/n): ").strip().lower()
    if confirm == 'y':
        # 通过API添加
        import subprocess
        import json

        data = {
            "correct": correct,
            "wrong": wrong_list
        }

        try:
            result = subprocess.run(
                ["curl", "-X", "POST", "http://localhost:8000/api/glossary/add",
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps(data)],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                print(f"\n✅ 成功添加词库条目！")
                print(f"\n当前词库：")

                # 显示词库
                result = subprocess.run(
                    ["curl", "-s", "-X", "POST", "http://localhost:8000/api/glossary/entries"],
                    capture_output=True,
                    text=True
                )

                if result.returncode == 0:
                    glossary = json.loads(result.stdout)
                    print(f"\n总共 {len(glossary['entries'])} 个条目：")
                    for correct, wrong_list in glossary['entries'].items():
                        print(f"  • {correct} ← {', '.join(wrong_list)}")
            else:
                print(f"❌ 添加失败: {result.stderr}")
        except Exception as e:
            print(f"❌ 错误: {e}")
    else:
        print("❌ 已取消")

def show_current_glossary():
    """显示当前词库"""
    import subprocess

    print("\n📖 当前词库：")
    print("-" * 40)

    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", "http://localhost:8000/api/glossary/entries"],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            glossary = json.loads(result.stdout)

            if not glossary['entries']:
                print("  （词库为空）")
            else:
                for i, (correct, wrong_list) in enumerate(glossary['entries'].items(), 1):
                    print(f"  {i}. {correct} ← {', '.join(wrong_list)}")
        else:
            print("❌ 无法连接到服务器")
    except Exception as e:
        print(f"❌ 错误: {e}")

def main():
    """主菜单"""
    while True:
        print("\n" + "="*60)
        print("📚 词库管理工具")
        print("="*60)
        print("\n选择操作：")
        print("  1. 查看当前词库")
        print("  2. 添加新词库条目")
        print("  3. 退出")

        choice = input("\n请选择 (1-3): ").strip()

        if choice == '1':
            show_current_glossary()
        elif choice == '2':
            add_glossary_entry()
        elif choice == '3':
            print("\n👋 再见！")
            break
        else:
            print("\n❌ 无效选择，请重试")

if __name__ == "__main__":
    main()
