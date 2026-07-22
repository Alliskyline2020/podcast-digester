"""应用启动冒烟测试。

不 mock 路由装配：直接 ``from app.main import app`` → ``TestClient`` 打真实 HTTP，
验证 FastAPI app 能装配、路由能响应、健康端点契约稳定。CI 最小存活闸门。
"""
from fastapi.testclient import TestClient


def test_health_endpoint_responds_healthy():
    """GET / → 200 + {name, version, status: healthy}。"""
    from app.main import app

    client = TestClient(app)
    resp = client.get("/")

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "podcast-digester"
    assert body["status"] == "healthy"
    assert "version" in body
