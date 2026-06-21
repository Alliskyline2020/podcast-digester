#!/usr/bin/env python3
"""
API验证示例
展示修复后的API行为
"""
from typing import Dict, Any, List
import json

# 模拟API请求验证示例


class APIValidator:
    """API验证器"""

    def __init__(self):
        self.errors = []
        self.warnings = []

    def validate_episode_id(self, episode_id: str) -> bool:
        """验证episode_id格式"""
        if not episode_id or not isinstance(episode_id, str):
            self.errors.append("episode_id不能为空且必须是字符串")
            return False

        if not episode_id.startswith("ep_"):
            self.errors.append("episode_id必须以'ep_'开头")
            return False

        return True

    def validate_segment_update(self, segment_index: int, text: str, max_segments: int) -> bool:
        """验证segment更新请求"""
        if segment_index < 0:
            self.errors.append("segment_index不能为负数")
            return False

        if segment_index >= max_segments:
            self.errors.append(f"segment_index超出范围: {segment_index} >= {max_segments}")
            return False

        if not text or not text.strip():
            self.errors.append("text_original不能为空")
            return False

        if len(text) > 10000:
            self.errors.append("text_original过长（最多10000字符）")
            return False

        return True

    def validate_batch_operation(self, episode_ids: List[str]) -> bool:
        """验证批量操作"""
        if not episode_ids:
            self.errors.append("episode_ids列表不能为空")
            return False

        if not isinstance(episode_ids, list):
            self.errors.append("episode_ids必须是列表")
            return False

        if len(episode_ids) > 100:
            self.errors.append("单次批量操作不能超过100个节目")
            return False

        for ep_id in episode_ids:
            if not isinstance(ep_id, str) or not ep_id.startswith("ep_"):
                self.errors.append(f"无效的episode_id格式: {ep_id}")
                return False

        return True

    def get_validation_result(self) -> Dict[str, Any]:
        """获取验证结果"""
        return {
            "valid": len(self.errors) == 0,
            "errors": self.errors,
            "warnings": self.warnings
        }


def demonstrate_fixes():
    """演示修复后的API行为"""
    print("=" * 60)
    print("API验证示例")
    print("=" * 60)
    print()

    # 创建验证器
    validator = APIValidator()

    # 示例1: 验证episode_id
    print("1. episode_id格式验证")
    print("-" * 40)

    test_cases = [
        ("ep_12345", True),
        ("invalid", False),
        ("", False),
        (None, False),
        ("ep_test", True),
    ]

    for episode_id, should_pass in test_cases:
        validator.errors = []
        result = validator.validate_episode_id(episode_id)
        status = "✅" if result == should_pass else "❌"
        print(f"{status} episode_id={episode_id!r}: result={result}")

    print()

    # 示例2: 验证segment更新
    print("2. segment更新验证")
    print("-" * 40)

    test_cases = [
        (0, "Hello World", 10, True),
        (-1, "Test", 10, False),
        (10, "Test", 10, False),  # 等于max_segments
        (5, "", 10, False),  # 空文本
        (5, "x" * 10001, 10, False),  # 过长文本
        (5, "Valid text", 10, True),
    ]

    for segment_index, text, max_segments, should_pass in test_cases:
        validator.errors = []
        result = validator.validate_segment_update(segment_index, text, max_segments)
        status = "✅" if result == should_pass else "❌"
        print(f"{status} segment_index={segment_index}, text_len={len(text)}, max={max_segments}: result={result}")

    print()

    # 示例3: 验证批量操作
    print("3. 批量操作验证")
    print("-" * 40)

    test_cases = [
        (["ep_1", "ep_2", "ep_3"], True),
        ([], False),  # 空列表
        (["ep_1"] * 101, False),  # 超过100个
        (["ep_1", "invalid", "ep_2"], False),  # 无效ID
        (["ep_1", "ep_2"], True),
    ]

    for episode_ids, should_pass in test_cases:
        validator.errors = []
        result = validator.validate_batch_operation(episode_ids)
        status = "✅" if result == should_pass else "❌"
        print(f"{status} count={len(episode_ids)}: result={result}")
        if validator.errors:
            for error in validator.errors:
                print(f"   Error: {error}")

    print()

    # 示例4: 展示N+1查询修复
    print("4. N+1查询修复效果")
    print("-" * 40)

    episodes = [
        {"id": "ep_1", "status": "ready"},
        {"id": "ep_2", "status": "pending"},
        {"id": "ep_3", "status": "downloading"},
        {"id": "ep_4", "status": "ready"},
    ]

    # 修复前：N+1查询
    print("修复前（N+1查询）:")
    progress_queries = 0
    for ep in episodes:
        if ep["status"] in ["pending", "downloading", "asr_running", "llm_running"]:
            progress_queries += 1
            print(f"  查询进度: episode_id={ep['id']}")
    print(f"  总查询数: {len(episodes)} + {progress_queries} = {len(episodes) + progress_queries}")

    print()

    # 修复后：批量加载
    print("修复后（批量加载）:")
    progress_episode_ids = [
        ep["id"] for ep in episodes
        if ep["status"] in ["pending", "downloading", "asr_running", "llm_running"]
    ]
    print(f"  批量加载: {progress_episode_ids}")
    print(f"  总查询数: {len(episodes)} + 1 (批量) = {len(episodes) + 1}")

    print()

    # 示例5: 展示事务保护
    print("5. 事务保护示例")
    print("-" * 40)
    print("创建episode操作（事务保护）:")
    print("  BEGIN")
    print("  INSERT INTO episode ...")
    print("  INSERT INTO usage_log ...")
    print("  COMMIT")
    print()
    print("如果任何步骤失败:")
    print("  ROLLBACK")
    print("  → 确保数据一致性")

    print()

    # 示例6: 展示错误处理改进
    print("6. 错误处理改进")
    print("-" * 40)

    error_cases = [
        ("aiosqlite.IntegrityError", "409 Conflict", "节目ID冲突"),
        ("aiosqlite.DatabaseError", "500 Internal Error", "数据库错误"),
        ("ValueError", "400 Bad Request", "参数错误"),
        ("JSONDecodeError", "200 OK", "记录日志，使用默认值"),
    ]

    for error_type, http_status, handling in error_cases:
        print(f"  {error_type}:")
        print(f"    HTTP状态: {http_status}")
        print(f"    处理方式: {handling}")
        print()

    print("=" * 60)
    print("✅ 所有API验证示例完成")
    print("=" * 60)


if __name__ == "__main__":
    demonstrate_fixes()
