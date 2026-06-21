#!/usr/bin/env python3
"""
测试运行脚本

快速运行不同类型的测试
"""
import sys
import subprocess
from pathlib import Path


def run_pytest(args: list) -> int:
    """运行pytest"""
    cmd = ["python", "-m", "pytest"] + args
    print(f"运行: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=Path(__file__).parent)
    return result.returncode


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python run_tests.py <test_type>")
        print("")
        print("测试类型:")
        print("  unit      - 运行单元测试")
        print("  database  - 运行数据库测试")
        print("  all       - 运行所有测试")
        print("  coverage  - 运行测试并生成覆盖率报告")
        print("  fast      - 运行快速测试（排除慢速测试）")
        return 1

    test_type = sys.argv[1]

    if test_type == "unit":
        return run_pytest(["-m", "unit", "-v"])

    elif test_type == "database":
        return run_pytest(["-m", "database", "-v"])

    elif test_type == "all":
        return run_pytest(["-v"])

    elif test_type == "coverage":
        return run_pytest([
            "--cov=app",
            "--cov-report=html",
            "--cov-report=term-missing",
            "-v"
        ])

    elif test_type == "fast":
        return run_pytest([
            "-v",
            "-m", "not slow"
        ])

    else:
        print(f"未知的测试类型: {test_type}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
