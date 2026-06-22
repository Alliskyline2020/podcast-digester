"""
Rate limiter 单元测试。

SlidingWindowLimiter 是纯逻辑，无副作用（除了内部 dict），容易测全。
"""
import asyncio
import pytest

from app.rate_limit import SlidingWindowLimiter, limiter, rate_limit, client_key
from fastapi import HTTPException, Request


@pytest.mark.asyncio
async def test_allows_up_to_max():
    """N 个请求按顺序允许，第 N+1 个被拒"""
    rl = SlidingWindowLimiter()
    for _ in range(5):
        assert await rl.allow("k1", max_requests=5, window_seconds=60) is True
    assert await rl.allow("k1", max_requests=5, window_seconds=60) is False


@pytest.mark.asyncio
async def test_keys_independent():
    """不同 key 的计数互不影响"""
    rl = SlidingWindowLimiter()
    await rl.allow("a", 1, 60)
    await rl.allow("b", 1, 60)
    # a 已满，b 也已满
    assert await rl.allow("a", 1, 60) is False
    assert await rl.allow("b", 1, 60) is False
    # 新 key c 仍可用
    assert await rl.allow("c", 1, 60) is True


@pytest.mark.asyncio
async def test_window_expires(monkeypatch):
    """窗口过期后，旧请求不再计入"""
    rl = SlidingWindowLimiter()
    # 用 monkeypatch 控制 monotonic 返回值
    fake_time = [0.0]
    monkeypatch.setattr("app.rate_limit.time.monotonic", lambda: fake_time[0])

    await rl.allow("k", 2, 60)  # t=0
    await rl.allow("k", 2, 60)  # t=0
    assert await rl.allow("k", 2, 60) is False  # 窗口满

    # 推进时间到窗口外（61s 后）
    fake_time[0] = 61.0
    assert await rl.allow("k", 2, 60) is True  # 旧请求被淘汰


@pytest.mark.asyncio
async def test_partial_window_keeps_only_recent(monkeypatch):
    """窗口滑动时只保留窗口内的请求"""
    rl = SlidingWindowLimiter()
    fake_time = [0.0]
    monkeypatch.setattr("app.rate_limit.time.monotonic", lambda: fake_time[0])

    # 0s 时用掉 2 次
    await rl.allow("k", 3, 10)
    await rl.allow("k", 3, 10)

    # 5s 时再用 1 次
    fake_time[0] = 5.0
    await rl.allow("k", 3, 10)

    # 11s 时：0s 的两次已过期，只剩 5s 的 1 次，再用 2 次应该都通过
    fake_time[0] = 11.0
    assert await rl.allow("k", 3, 10) is True
    assert await rl.allow("k", 3, 10) is True
    # 第 3 次会超过限额
    assert await rl.allow("k", 3, 10) is False


@pytest.mark.asyncio
async def test_concurrent_calls_safe():
    """并发下 allow 不应崩；用锁确保 atomicity"""
    rl = SlidingWindowLimiter()

    async def hit():
        return await rl.allow("k", 100, 60)

    results = await asyncio.gather(*[hit() for _ in range(100)])
    # 100 个并发请求，max=100，应该全部成功
    assert all(results) is True
    # 第 101 个应该被拒
    assert await rl.allow("k", 100, 60) is False


@pytest.mark.asyncio
async def test_eviction_keeps_dict_bounded():
    """超过 10000 个 key 时回收空桶（不直接验证 dict 大小，验证功能正常）"""
    rl = SlidingWindowLimiter()
    # 模拟很多 key 都用过 1 次然后过期
    for i in range(10010):
        await rl.allow(f"k{i}", 1, 1)

    # 功能不应该崩；新请求正常工作
    assert await rl.allow("new_key", 1, 60) is True


def test_client_key_extracts_host():
    """client_key 从 request.client.host 取"""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "client": ("1.2.3.4", 12345),
        "server": ("testserver", 80),
    }
    req = Request(scope)
    assert client_key(req) == "1.2.3.4"


def test_client_key_handles_missing_client():
    """request.client 缺失时返回 'unknown'"""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "client": None,
        "server": ("testserver", 80),
    }
    req = Request(scope)
    assert client_key(req) == "unknown"


@pytest.mark.asyncio
async def test_rate_limit_dependency_raises_429(monkeypatch):
    """rate_limit 工厂返回的 dependency 在超限时抛 429。

    conftest 的 autouse fixture 把模块单例 limiter.allow mock 成 always-true，
    所以这里要换一个干净的 SlidingWindowLimiter 注入进去。
    """
    fresh_limiter = SlidingWindowLimiter()
    monkeypatch.setattr("app.rate_limit.limiter", fresh_limiter)

    dep = rate_limit(max_requests=1, window_seconds=60)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/paste",
        "headers": [],
        "query_string": b"",
        "client": ("1.2.3.4", 12345),
        "server": ("testserver", 80),
    }
    req = Request(scope)

    # 第一次：通过
    await dep(req)
    # 第二次：429
    with pytest.raises(HTTPException) as exc:
        await dep(req)
    assert exc.value.status_code == 429
    assert "Retry-After" in (exc.value.headers or {})
