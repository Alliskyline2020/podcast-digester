"""
WriteAuthMiddleware 单元测试。

直接构造 middleware 实例 + 假 ASGI app，不依赖 FastAPI app 装载，
避免 conftest 的 auth bypass 干扰。
"""
import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.deps import WriteAuthMiddleware
from app.config import settings


def make_request(method: str, path: str, headers=None):
    """构造一个最小可用的 Starlette Request"""
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


async def fake_app(scope, receive, send):
    """假 ASGI app，直接返回 200 给所有请求"""
    response = JSONResponse({"ok": True})
    await response(scope, receive, send)


def make_middleware(app=fake_app):
    """构造一个 WriteAuthMiddleware 实例"""
    return WriteAuthMiddleware(app)


async def call_middleware(middleware, method, path, headers=None):
    """调用 middleware 并返回 (status_code, body)"""
    request = make_request(method, path, headers)
    response = await middleware.dispatch(request, lambda r: fake_app(r.scope, r.receive, r._send))
    # dispatch 不直接返回 response；它在 dispatch 函数返回里给出 JSONResponse
    # 当 token 通过时，call_next(request) 会走真实 app。我们这里的 call_next 简化
    # 为 fake_app 调用。
    return response


@pytest.mark.asyncio
async def test_passthrough_when_token_unset(monkeypatch):
    """ADMIN_TOKEN 未配置时，所有请求放行"""
    monkeypatch.setattr(settings, "admin_token", "")

    mw = make_middleware()
    request = make_request("POST", "/api/paste", {"Content-Type": "application/json"})

    # dispatch 在 token 未配置时直接 await call_next(request)，没有 return JSONResponse
    # 我们用真实 call_next（lambda 返回 fake_app 的结果）验证它没拦
    called = {"v": False}

    async def fake_call_next(req):
        called["v"] = True
        return JSONResponse({"ok": True})

    response = await mw.dispatch(request, fake_call_next)
    assert called["v"] is True  # call_next 真的被调用了，说明 middleware 放行


@pytest.mark.asyncio
async def test_get_request_passthrough_even_with_token(monkeypatch):
    """配置了 token 时，GET 请求依然放行（只读豁免）"""
    monkeypatch.setattr(settings, "admin_token", "secret")

    mw = make_middleware()
    request = make_request("GET", "/api/episodes")

    called = {"v": False}

    async def fake_call_next(req):
        called["v"] = True
        return JSONResponse({"ok": True})

    await mw.dispatch(request, fake_call_next)
    assert called["v"] is True


@pytest.mark.asyncio
async def test_post_blocked_without_token(monkeypatch):
    """配置了 token 时，POST 不带 X-Admin-Token 返回 401"""
    monkeypatch.setattr(settings, "admin_token", "secret")

    mw = make_middleware()
    request = make_request("POST", "/api/paste", {"Content-Type": "application/json"})

    async def should_not_be_called(req):
        raise AssertionError("call_next should not be reached when token missing")

    response = await mw.dispatch(request, should_not_be_called)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_post_blocked_with_wrong_token(monkeypatch):
    """配置了 token 时，POST 带错误 X-Admin-Token 返回 401"""
    monkeypatch.setattr(settings, "admin_token", "secret")

    mw = make_middleware()
    request = make_request(
        "POST",
        "/api/paste",
        {"Content-Type": "application/json", "X-Admin-Token": "wrong"},
    )

    async def should_not_be_called(req):
        raise AssertionError("call_next should not be reached when token wrong")

    response = await mw.dispatch(request, should_not_be_called)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_post_passes_with_correct_token(monkeypatch):
    """配置了 token 时，POST 带正确 X-Admin-Token 放行"""
    monkeypatch.setattr(settings, "admin_token", "secret")

    mw = make_middleware()
    request = make_request(
        "POST",
        "/api/paste",
        {"Content-Type": "application/json", "X-Admin-Token": "secret"},
    )

    called = {"v": False}

    async def fake_call_next(req):
        called["v"] = True
        return JSONResponse({"ok": True})

    await mw.dispatch(request, fake_call_next)
    assert called["v"] is True


@pytest.mark.asyncio
async def test_exempt_paths_passthrough(monkeypatch):
    """静态资源/导出下载路径即使配置了 token 也放行"""
    monkeypatch.setattr(settings, "admin_token", "secret")

    mw = make_middleware()
    # /media/ 和 /api/exports/ 都豁免
    for path in ["/media/ep_x/audio.m4a", "/api/exports/foo.html"]:
        request = make_request("GET", path)
        called = {"v": False}

        async def fake_call_next(req):
            called["v"] = True
            return JSONResponse({"ok": True})

        await mw.dispatch(request, fake_call_next)
        assert called["v"] is True, f"Path {path} should be exempt"


@pytest.mark.asyncio
async def test_non_api_path_passthrough(monkeypatch):
    """非 /api/ 路径（如 /openapi.json、/docs）豁免"""
    monkeypatch.setattr(settings, "admin_token", "secret")

    mw = make_middleware()
    request = make_request("GET", "/openapi.json")

    called = {"v": False}

    async def fake_call_next(req):
        called["v"] = True
        return JSONResponse({"ok": True})

    await mw.dispatch(request, fake_call_next)
    assert called["v"] is True


@pytest.mark.asyncio
async def test_delete_also_blocked(monkeypatch):
    """DELETE 方法也走写认证"""
    monkeypatch.setattr(settings, "admin_token", "secret")

    mw = make_middleware()
    request = make_request("DELETE", "/api/episode/ep_x")

    async def should_not_be_called(req):
        raise AssertionError("DELETE should be blocked without token")

    response = await mw.dispatch(request, should_not_be_called)
    assert response.status_code == 401
