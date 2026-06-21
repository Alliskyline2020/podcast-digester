#!/usr/bin/env python3
"""
项目健康检查脚本

快速验证所有服务是否正常运行
"""
import requests
import json
import sys
from typing import Dict, Any


def print_section(title: str):
    """打印章节标题"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def check_backend() -> bool:
    """检查后端服务"""
    try:
        response = requests.get("http://127.0.0.1:8000/", timeout=5)
        data = response.json()

        print("✅ 后端服务正常运行")
        print(f"   名称: {data.get('name')}")
        print(f"   版本: {data.get('version')}")
        print(f"   状态: {data.get('status')}")
        return True
    except Exception as e:
        print(f"❌ 后端服务异常: {e}")
        return False


def check_frontend() -> bool:
    """检查前端服务"""
    try:
        response = requests.get("http://localhost:5173/", timeout=5)

        if response.status_code == 200 and "html" in response.text.lower():
            print("✅ 前端服务正常运行")
            print("   URL: http://localhost:5173")
            return True
        else:
            print(f"❌ 前端服务响应异常 (状态码: {response.status_code})")
            return False
    except Exception as e:
        print(f"❌ 前端服务异常: {e}")
        return False


def check_api_endpoints() -> Dict[str, Any]:
    """检查API端点"""
    results = {
        "episodes_list": False,
        "paste_endpoint": False,
        "fixture_available": False,
    }

    try:
        # 检查节目列表
        response = requests.get("http://127.0.0.1:8000/api/episodes", timeout=5)
        if response.status_code == 200:
            data = response.json()
            episode_count = len(data.get("episodes", []))
            print(f"✅ /api/episodes 正常 ({episode_count} 个节目)")
            results["episodes_list"] = True
        else:
            print(f"❌ /api/episodes 异常 (状态码: {response.status_code})")
    except Exception as e:
        print(f"❌ /api/episodes 请求失败: {e}")

    try:
        # 检查粘贴功能（使用fixture ID）
        response = requests.post(
            "http://127.0.0.1:8000/api/paste",
            json={"raw_input": "test_check"},
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            episode_id = data.get("episode", {}).get("id")
            print(f"✅ /api/paste 正常 (创建episode: {episode_id})")
            results["paste_endpoint"] = True
        else:
            print(f"❌ /api/paste 异常 (状态码: {response.status_code})")
    except Exception as e:
        print(f"❌ /api/paste 请求失败: {e}")

    return results


def check_data_quality() -> None:
    """检查数据质量"""
    try:
        response = requests.get("http://127.0.0.1:8000/api/episodes", timeout=5)
        data = response.json()
        episodes = data.get("episodes", [])

        if not episodes:
            print("\n📊 数据状态: 无节目记录")
            return

        # 统计状态
        status_count = {}
        for ep in episodes:
            status = ep.get("status", "unknown")
            status_count[status] = status_count.get(status, 0) + 1

        print(f"\n📊 节目状态分布:")
        for status, count in status_count.items():
            print(f"   {status}: {count} 个")

        # 检查ready状态的节目
        ready_count = status_count.get("ready", 0)
        failed_count = status_count.get("failed", 0)

        if ready_count > 0:
            print(f"\n✅ 有 {ready_count} 个节目处理完成，可以正常播放")
        elif failed_count > 0:
            print(f"\n⚠️  有 {failed_count} 个节目处理失败（可能需要检查配置）")
        else:
            print(f"\n📝 正在处理中，无ready节目")

    except Exception as e:
        print(f"\n❌ 无法获取数据质量信息: {e}")


def main():
    """主函数"""
    print_section("🔍 Podcast Digester 健康检查")

    # 检查服务
    backend_ok = check_backend()
    frontend_ok = check_frontend()

    if not (backend_ok and frontend_ok):
        print("\n❌ 服务未正常启动，请先运行 ./start.sh")
        sys.exit(1)

    # 检查API
    api_results = check_api_endpoints()

    # 检查数据质量
    check_data_quality()

    # 总结
    print_section("📋 检查结果")

    all_ok = all(api_results.values()) and backend_ok and frontend_ok

    if all_ok:
        print("✅ 所有检查通过！项目运行正常")
        print("\n🎯 可以访问前端进行测试:")
        print("   http://localhost:5173")
        print("\n📝 建议操作:")
        print("   1. 在前端界面粘贴播客URL测试完整流程")
        print("   2. 检查fixture节目是否需要创建")
        print("   3. 查看测试覆盖率: cd backend && pytest tests/ --cov=app --cov-report=html")
        return 0
    else:
        print("⚠️  部分检查未通过，请检查相关功能")
        return 1


if __name__ == "__main__":
    sys.exit(main())
