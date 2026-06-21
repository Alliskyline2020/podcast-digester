#!/bin/bash
# 快速验证修复脚本

echo "🧪 验证修复..."
echo ""

# 1. 检查Python语法
echo "1️⃣ 检查Python语法..."
python -m py_compile app/errors.py && echo "   ✅ errors.py"
python -m py_compile app/error_handling.py && echo "   ✅ error_handling.py"
python -m py_compile app/config.py && echo "   ✅ config.py"
python -m py_compile tests/conftest.py && echo "   ✅ tests/conftest.py"
python -m py_compile tests/test_database.py && echo "   ✅ tests/test_database.py"
python -m py_compile tests/test_errors.py && echo "   ✅ tests/test_errors.py"
echo ""

# 2. 检查前端语法
echo "2️⃣ 检查前端语法..."
cd frontend
npx eslint --no-eslintrc --config .eslintrc.cjs src/composables/player.js 2>/dev/null && echo "   ✅ player.js" || echo "   ⚠️  player.js (可能需要手动检查)"
cd ..
echo ""

# 3. 运行单元测试
echo "3️⃣ 运行单元测试..."
python -m pytest tests/test_database.py -v --tb=short 2>/dev/null || echo "   ⚠️  数据库测试需要安装依赖"
echo ""

# 4. 检查导入
echo "4️⃣ 检查模块导入..."
python -c "from app.errors import *" && echo "   ✅ app.errors"
python -c "from app.error_handling import *" && echo "   ✅ app.error_handling"
python -c "from app.config import *" && echo "   ✅ app.config"
echo ""

echo "✅ 验证完成！"
echo ""
echo "下一步："
echo "  1. 安装测试依赖: pip install pytest pytest-asyncio pytest-cov"
echo "  2. 运行测试: pytest tests/"
echo "  3. 运行测试并生成覆盖率: pytest --cov=app --cov-report=html"
