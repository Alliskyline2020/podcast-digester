"""LLM 配置设置端点测试。"""
import pytest
from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app)


@pytest.fixture
async def cfg_env(temp_db, monkeypatch):
    """临时库 + 清空 env，让端点行为可预测。"""
    for k in list(__import__("os").environ):
        if k.startswith(("LLM_", "DEEPSEEK_")):
            monkeypatch.delenv(k, raising=False)
    return monkeypatch


@pytest.mark.api
async def test_get_returns_masked_key_and_providers(cfg_env, monkeypatch):
    from app.llm.runtime_config import write_runtime_override
    await write_runtime_override({"provider": "deepseek", "api_key": "sk-abcd1234",
                                  "model": "deepseek-chat"})
    resp = _client().get("/api/admin/llm-config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "deepseek"
    assert body["model"] == "deepseek-chat"
    assert body["has_api_key"] is True
    assert body["api_key_masked"].endswith("1234")
    assert body["api_key_masked"].startswith("****")
    assert "deepseek" in body["providers"]


@pytest.mark.api
async def test_put_writes_override(cfg_env, monkeypatch):
    resp = _client().put("/api/admin/llm-config", json={
        "provider": "glm", "api_key": "sk-glm-xyz", "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
    })
    assert resp.status_code == 200
    # 读回验证
    body = _client().get("/api/admin/llm-config").json()
    assert body["provider"] == "glm"
    assert body["has_api_key"] is True
    assert body["api_key_masked"].endswith("xyz")


@pytest.mark.api
async def test_put_without_api_key_keeps_old(cfg_env, monkeypatch):
    from app.llm.runtime_config import write_runtime_override
    await write_runtime_override({"api_key": "sk-old-9999"})
    _client().put("/api/admin/llm-config", json={"model": "gpt-4o-mini"})
    body = _client().get("/api/admin/llm-config").json()
    assert body["api_key_masked"].endswith("9999")  # 旧 key 保留


@pytest.mark.api
async def test_put_rejects_ssrf_base_url(cfg_env, monkeypatch):
    # SSRF 只对可编辑(自定义端点) provider 生效；锁定型 base_url 被强制为预设默认
    resp = _client().put("/api/admin/llm-config", json={
        "provider": "openai-compatible", "provider_type": "openai_compatible",
        "api_key": "sk-x", "base_url": "http://127.0.0.1:8080",
    })
    assert resp.status_code == 400
    assert "base_url" in resp.json()["message"]


@pytest.mark.api
async def test_test_endpoint_ok(cfg_env, monkeypatch):
    import app.routers.llm_config as router
    async def _ok(cfg):
        return True, "连通（模型 x）"
    monkeypatch.setattr(router, "ping_llm", _ok)
    resp = _client().post("/api/admin/llm-config/test", json={
        "api_key": "sk-x", "model": "m", "base_url": "https://api.deepseek.com",
        "provider": "deepseek",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True


@pytest.mark.api
async def test_test_endpoint_no_key(cfg_env, monkeypatch):
    resp = _client().post("/api/admin/llm-config/test", json={"provider": "deepseek"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


# ==================== Task 3: /models 端点 ====================

@pytest.mark.api
async def test_models_endpoint_ok(cfg_env, monkeypatch):
    import app.routers.llm_config as router
    async def _ok(cfg):
        return True, ["deepseek-chat", "deepseek-reasoner"]
    monkeypatch.setattr(router, "list_models", _ok)
    resp = _client().post("/api/admin/llm-config/models", json={
        "api_key": "sk-x", "base_url": "https://api.deepseek.com", "provider": "deepseek",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["models"] == ["deepseek-chat", "deepseek-reasoner"]


@pytest.mark.api
async def test_models_endpoint_failure_detail(cfg_env, monkeypatch):
    import app.routers.llm_config as router
    async def _fail(cfg):
        return False, "API Key 无效或未授权(401)"
    monkeypatch.setattr(router, "list_models", _fail)
    resp = _client().post("/api/admin/llm-config/models", json={
        "api_key": "sk-x", "base_url": "https://api.deepseek.com", "provider": "deepseek",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "API Key" in body["detail"]


@pytest.mark.api
async def test_models_endpoint_ssrf_blocked(cfg_env, monkeypatch):
    # SSRF 只对可编辑 provider 生效；锁定型 base_url 被强制为预设默认
    resp = _client().post("/api/admin/llm-config/models", json={
        "api_key": "sk-x", "base_url": "http://127.0.0.1:8080",
        "provider": "openai-compatible", "provider_type": "openai_compatible",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "base_url" in body["detail"]


@pytest.mark.api
async def test_models_endpoint_locked_provider_ignores_form_base_url(cfg_env, monkeypatch):
    # 锁定型 provider：前端传入的恶意 base_url 被忽略，实际用预设默认（防篡改）
    captured = {}
    import app.routers.llm_config as router
    async def _spy(cfg):
        captured["base_url"] = cfg.base_url
        return True, ["deepseek-chat"]
    monkeypatch.setattr(router, "list_models", _spy)
    resp = _client().post("/api/admin/llm-config/models", json={
        "api_key": "sk-x", "base_url": "http://127.0.0.1/evil", "provider": "deepseek",
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert captured["base_url"] == "https://api.deepseek.com"   # 非恶意 url


@pytest.mark.api
async def test_put_locked_provider_forces_default_base_url(cfg_env, monkeypatch):
    # 锁定型 provider 即便提交别的 base_url，存进去的也是预设默认
    _client().put("/api/admin/llm-config", json={
        "provider": "deepseek", "api_key": "sk-x",
        "base_url": "http://127.0.0.1/evil",   # 应被忽略
    })
    body = _client().get("/api/admin/llm-config").json()
    assert body["base_url"] == "https://api.deepseek.com"


@pytest.mark.api
async def test_models_endpoint_no_key(cfg_env, monkeypatch):
    resp = _client().post("/api/admin/llm-config/models", json={"provider": "deepseek"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


@pytest.mark.api
async def test_get_returns_editable_flag_and_glm_coding(cfg_env, monkeypatch):
    from app.llm.runtime_config import write_runtime_override
    await write_runtime_override({"provider": "glm", "api_key": "sk-glm"})
    body = _client().get("/api/admin/llm-config").json()
    glm = body["providers"]["glm"]
    assert glm["base_url_editable"] is False
    assert glm["default_base_url"] == "https://open.bigmodel.cn/api/paas/v4"
    assert "base_urls" not in glm   # 多选下拉机制已移除
    # 编码套件是独立 provider，固定 coding 端点
    coding = body["providers"]["glm-coding"]
    assert coding["default_base_url"] == "https://open.bigmodel.cn/api/coding/paas/v4"
    assert coding["base_url_editable"] is False
    # 兼容自定义端点仍可编辑
    assert body["providers"]["openai-compatible"]["base_url_editable"] is True


@pytest.mark.api
async def test_get_exposes_region(cfg_env, monkeypatch):
    from app.llm.runtime_config import write_runtime_override
    await write_runtime_override({"provider": "deepseek", "api_key": "sk-x"})
    body = _client().get("/api/admin/llm-config").json()
    assert body["providers"]["deepseek"]["region"] == "国内"
    assert body["providers"]["openai"]["region"] == "国际"
    assert body["providers"]["openai-compatible"]["region"] == ""
