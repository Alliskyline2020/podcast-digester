#!/bin/bash
# 验证架构修复的脚本

echo "=================================================="
echo "验证 Podcast Digester 架构修复"
echo "=================================================="
echo ""

# 检查Python版本
echo "1. 检查Python版本..."
python3 --version | head -1
echo ""

# 运行语法检查
echo "2. 运行语法检查..."
python3 test_syntax.py
if [ $? -ne 0 ]; then
    echo "❌ 语法检查失败"
    exit 1
fi
echo ""

# 运行架构修复测试
echo "3. 运行架构修复测试..."
python3 test_architecture_fixes.py
if [ $? -ne 0 ]; then
    echo "❌ 架构修复测试失败"
    exit 1
fi
echo ""

# 检查关键修复点
echo "4. 检查关键修复点..."
echo "   检查N+1查询修复..."
grep -n "progress_cache" app/main.py > /dev/null
if [ $? -eq 0 ]; then
    echo "   ✅ N+1查询修复已应用"
else
    echo "   ❌ N+1查询修复未找到"
    exit 1
fi

echo "   检查事务装饰器..."
grep -n "def transactional" app/database.py > /dev/null
if [ $? -eq 0 ]; then
    echo "   ✅ 事务装饰器已添加"
else
    echo "   ❌ 事务装饰器未找到"
    exit 1
fi

echo "   检查错误处理改进..."
grep -n "aiosqlite.IntegrityError" app/main.py > /dev/null
if [ $? -eq 0 ]; then
    echo "   ✅ 错误处理改进已应用"
else
    echo "   ❌ 错误处理改进未找到"
    exit 1
fi

echo "   检查输入验证..."
grep -n 'episode_id.startswith("ep_")' app/main.py > /dev/null
if [ $? -eq 0 ]; then
    echo "   ✅ 输入验证已增强"
else
    echo "   ❌ 输入验证未找到"
    exit 1
fi

echo ""
echo "=================================================="
echo "✅ 所有架构修复验证通过！"
echo "=================================================="
echo ""
echo "修复摘要："
echo "1. ✅ 修复N+1查询问题"
echo "2. ✅ 添加事务处理"
echo "3. ✅ 完善错误处理"
echo "4. ✅ 加强输入验证"
echo ""
echo "详细说明请查看: ARCHITECTURE_FIXES_SUMMARY.md"
echo ""
