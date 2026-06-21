#!/usr/bin/env python3
"""
数据库迁移脚本：添加 paragraph_mappings 字段

运行方式：
    python3 migrations/add_paragraph_mappings.py
"""
import sys
import sqlite3
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import DB_PATH


def migrate():
    """执行数据库迁移"""
    print(f"正在迁移数据库: {DB_PATH}")

    if not DB_PATH.exists():
        print(f"错误: 数据库文件不存在: {DB_PATH}")
        return False

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()

            # 检查列是否已存在
            cursor.execute("PRAGMA table_info(episode)")
            columns = [col[1] for col in cursor.fetchall()]

            if "paragraph_mappings" in columns:
                print("paragraph_mappings 字段已存在，无需迁移")
                return True

            # 添加新列
            print("正在添加 paragraph_mappings 列...")
            cursor.execute("""
                ALTER TABLE episode
                ADD COLUMN paragraph_mappings TEXT
            """)

            conn.commit()
            print("✓ 迁移成功完成")
            return True

    except Exception as e:
        print(f"✗ 迁移失败: {e}")
        return False


def rollback():
    """回滚迁移（删除 paragraph_mappings 字段）"""
    print(f"正在回滚数据库: {DB_PATH}")

    if not DB_PATH.exists():
        print(f"错误: 数据库文件不存在: {DB_PATH}")
        return False

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()

            # 检查列是否存在
            cursor.execute("PRAGMA table_info(episode)")
            columns = [col[1] for col in cursor.fetchall()]

            if "paragraph_mappings" not in columns:
                print("paragraph_mappings 字段不存在，无需回滚")
                return True

            # SQLite 不支持直接删除列，需要重建表
            print("警告: SQLite 不支持 ALTER TABLE DROP COLUMN")
            print("需要手动重建数据库或保留该字段")
            return False

    except Exception as e:
        print(f"✗ 回滚失败: {e}")
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="数据库迁移: 添加 paragraph_mappings 字段")
    parser.add_argument("--rollback", action="store_true", help="回滚迁移")
    args = parser.parse_args()

    if args.rollback:
        success = rollback()
    else:
        success = migrate()

    sys.exit(0 if success else 1)
