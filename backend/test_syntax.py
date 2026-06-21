#!/usr/bin/env python3
"""测试语法检查脚本"""
import sys
import py_compile

files_to_check = [
    'app/main.py',
    'app/database.py'
]

errors = []
for file in files_to_check:
    try:
        py_compile.compile(file, doraise=True)
        print(f"✓ {file} 语法检查通过")
    except py_compile.PyCompileError as e:
        errors.append((file, str(e)))
        print(f"✗ {file} 语法错误:\n{e}")

if errors:
    print("\n❌ 发现语法错误")
    sys.exit(1)
else:
    print("\n✅ 所有文件语法检查通过")
    sys.exit(0)
