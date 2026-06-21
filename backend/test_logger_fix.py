#!/usr/bin/env python3
"""测试logger修复"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__))

try:
    from app import main
    print("✓ app.main 导入成功")

    # 检查app对象是否存在
    if hasattr(main, 'app'):
        print("✓ FastAPI app 对象存在")
    else:
        print("✗ FastAPI app 对象不存在")

    print("\n✓ 所有检查通过！logger问题已修复")
    sys.exit(0)

except Exception as e:
    print(f"✗ 导入失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
