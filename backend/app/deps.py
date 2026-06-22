"""
跨 router 共享的依赖、工具与全局对象。

设计动机：main.py 拆分时，多个 router 都需要：
- 认证依赖 `verify_admin`
- 数据目录 `data_dir`
- 共享 logger
集中放在这里，避免 router 反向 import main.py 造成循环依赖。
"""
import hmac
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse

from .config import settings


logger = logging.getLogger("podcast_digester")


# ==================== 数据目录 ====================
# main.py 里历史上用 Path(__file__).parent.parent.parent / "data"，
# 等价于 backend/../data。这里显式从 settings 取，避免对 main.py 路径布局的依赖。
data_dir = Path(os.getenv(
    "PODCAST_DIGESTER_DATA_DIR",
    str(Path(__file__).parent.parent.parent / "data"),
))


# ==================== Loopback 判断 ====================

def is_loopback(host: Optional[str]) -> bool:
    """判断客户端 host 是否为 loopback（开发模式放行管理端点）"""
    if not host:
        return False
    return host in ("127.0.0.1", "::1", "localhost")


# ==================== 管理端认证依赖 ====================

async def verify_admin(request: Request) -> None:
    """
    FastAPI 依赖：保护 /api/admin/* 等敏感端点。

    策略：
    - 若 PODCAST_DIGESTER_ADMIN_TOKEN 已配置：请求头 X-Admin-Token 必须匹配；
      不匹配返回 401。Loopback 也必须带 token，避免依赖网络层判断。
    - 若未配置（开发默认）：仅允许 loopback；非 loopback 返回 403。
    """
    client_host = request.client.host if request.client else None

    if settings.admin_token:
        provided = request.headers.get("X-Admin-Token", "")
        if not hmac.compare_digest(provided, settings.admin_token):
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing X-Admin-Token header",
            )
    else:
        if not is_loopback(client_host):
            raise HTTPException(
                status_code=403,
                detail="Admin endpoints require PODCAST_DIGESTER_ADMIN_TOKEN for non-loopback access",
            )


# ==================== 全局写操作认证中间件 ====================

# 路径前缀 → 是否豁免写认证。
# - GET / 任何路径：豁免（只读）
# - /media/, /fixtures/, /api/exports/：豁免（资源下载，不需要 token；
#   export POST 已经各自带 rate_limit）
# - 非 /api/ 开头：豁免（静态 / openapi / docs）
_WRITE_AUTH_EXEMPT_PREFIXES = (
    "/media/",
    "/fixtures/",
    "/api/exports/",
)


class WriteAuthMiddleware(BaseHTTPMiddleware):
    """
    全局写操作认证中间件。

    策略：
    - 若 PODCAST_DIGESTER_ADMIN_TOKEN 未配置：放行所有请求（开发模式，
      假定只在 loopback 暴露）。
    - 若已配置：所有 POST / PUT / DELETE / PATCH 请求（除豁免的静态/导出
      下载路径外）必须在 X-Admin-Token 头里携带正确 token；否则返回 401。
      GET / HEAD 一律豁免（只读）。

    这道全局兜底覆盖所有 router，避免每个端点单独挂依赖时漏挂。
    router 自己挂的 verify_admin 在批量管理端点上仍保留，是双层防御。
    """

    async def dispatch(self, request: StarletteRequest, call_next):
        # Token 未配置：开发模式，不做认证
        if not settings.admin_token:
            return await call_next(request)

        method = request.method.upper()
        path = request.url.path

        # 只读方法豁免
        if method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)

        # 静态资源 / 导出文件下载豁免（导出本身的 POST 由 rate_limit 保护）
        if path.startswith(_WRITE_AUTH_EXEMPT_PREFIXES):
            return await call_next(request)

        # 非 API 路径豁免（openapi / docs / redoc / 健康检查）
        if not path.startswith("/api/"):
            return await call_next(request)

        # 检查 X-Admin-Token
        provided = request.headers.get("X-Admin-Token", "")
        if not hmac.compare_digest(provided, settings.admin_token):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing X-Admin-Token header"},
            )

        return await call_next(request)
