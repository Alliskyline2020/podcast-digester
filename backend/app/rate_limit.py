"""
进程内滑动窗口限流器。

设计目标：
- 单一可复用组件，覆盖 export / paste / LLM 触发端点等多种场景。
- 使用 asyncio.Lock 保护共享 dict，避免 H1 描述的竞态。
- 按 (client_host, endpoint_key) 维度限流；端点自己在调用处决定 key 粒度。
- 仅适用于单进程部署；多副本部署需要换 Redis 后端。
"""
import asyncio
import time
from collections import defaultdict, deque
from typing import Callable, Optional

from fastapi import HTTPException, Request


class SlidingWindowLimiter:
    """滑动窗口限流器（线程安全 / asyncio 安全）。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def allow(
        self,
        key: str,
        max_requests: int,
        window_seconds: float,
    ) -> bool:
        """
        判断 key 在窗口内是否还能放行。

        Args:
            key: 限流维度标识，建议格式 f"{client_host}:{endpoint}"
            max_requests: 窗口内允许的最大请求数
            window_seconds: 窗口长度（秒）

        Returns:
            True 允许放行；False 表示已达上限。
        """
        now = time.monotonic()
        cutoff = now - window_seconds
        async with self._lock:
            bucket = self._hits[key]
            # 淘汰窗口外旧记录
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= max_requests:
                return False
            bucket.append(now)
            # 偶尔回收空桶，避免长期运行后 dict 无限增长
            if len(self._hits) > 10000:
                self._evict_empty_locked()
            return True

    def _evict_empty_locked(self) -> None:
        """调用方必须已持有 _lock。"""
        empty = [k for k, v in self._hits.items() if not v]
        for k in empty:
            del self._hits[k]


# 模块级单例
limiter = SlidingWindowLimiter()


def client_key(request: Request) -> str:
    """提取客户端标识。当前用 request.client.host；
    若后续放到反代后面，再考虑解析 X-Forwarded-For。"""
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def rate_limit(
    max_requests: int,
    window_seconds: int,
    *,
    key_func: Optional[Callable[[Request], str]] = None,
) -> Callable:
    """
    FastAPI 依赖工厂：按端点 + 客户端限流。

    用法：
        @app.post("/api/paste", dependencies=[Depends(rate_limit(5, 60))])
        async def paste(...): ...
    """
    async def _dependency(request: Request) -> None:
        host = key_func(request) if key_func else client_key(request)
        key = f"{host}:{request.url.path}"
        if not await limiter.allow(key, max_requests, window_seconds):
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded: {max_requests} requests per "
                    f"{window_seconds}s for {request.url.path}"
                ),
                headers={"Retry-After": str(window_seconds)},
            )

    return _dependency
