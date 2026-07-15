"""app/llm/config 单元测试：PROVIDERS、get_config 别名、provider_type 推断、SSRF 守卫。"""
import pytest

from app.llm.config import (
    PROVIDERS, get_config, infer_provider_type, LLMConfig, _resolve_config, provider_base_urls,
)


@pytest.fixture
def clean_llm_env(monkeypatch):
    """清空所有 LLM/DEEPSEEK 环境变量，并把运行时覆写 DB 指向不存在的路径，
    使 get_config() 在单测里只受 env 影响（不被真实库里的覆写污染）。"""
    from pathlib import Path
    for k in list(__import__("os").environ):
        if k.startswith(("LLM_", "DEEPSEEK_")):
            monkeypatch.delenv(k, raising=False)
    from app import database as _db
    monkeypatch.setattr(_db, "DB_PATH", Path("/tmp/pd-nonexistent-clellm.db"))
    return monkeypatch


def test_providers_registry_has_required_entries():
    for name in ("deepseek", "openai", "anthropic", "glm", "qwen", "doubao", "moonshot"):
        assert name in PROVIDERS, f"缺少 provider: {name}"
        entry = PROVIDERS[name]
        assert "provider_type" in entry
        assert entry["provider_type"] in ("openai_compatible", "anthropic_compatible")
        assert "default_base_url" in entry
        assert "default_model" in entry


def test_infer_provider_type_from_registry():
    assert infer_provider_type("deepseek") == "openai_compatible"
    assert infer_provider_type("anthropic") == "anthropic_compatible"


def test_infer_unknown_provider_defaults_to_openai():
    assert infer_provider_type("totally-unknown") == "openai_compatible"


def test_deepseek_legacy_alias_works(clean_llm_env, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-legacy")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    cfg = get_config()
    assert cfg.api_key == "sk-legacy"
    assert cfg.model == "deepseek-chat"
    assert cfg.provider == "deepseek"
    assert cfg.provider_type == "openai_compatible"


def test_llm_vars_take_precedence_over_deepseek_alias(clean_llm_env, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-legacy")
    monkeypatch.setenv("LLM_API_KEY", "sk-new")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "claude-3-5-haiku-latest")
    cfg = get_config()
    assert cfg.api_key == "sk-new"
    assert cfg.provider == "anthropic"
    assert cfg.provider_type == "anthropic_compatible"
    assert cfg.model == "claude-3-5-haiku-latest"


def test_explicit_provider_type_overrides_inference(clean_llm_env, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")  # 推断为 openai_compatible
    monkeypatch.setenv("LLM_PROVIDER_TYPE", "anthropic_compatible")  # 显式覆盖
    cfg = get_config()
    assert cfg.provider_type == "anthropic_compatible"


def test_missing_api_key_raises(clean_llm_env):
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        get_config()


def test_ssrf_guard_blocks_localhost(clean_llm_env, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:8080")
    with pytest.raises(ValueError, match="base_url"):
        get_config()


def test_ssrf_guard_blocks_private_range(clean_llm_env, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_BASE_URL", "https://192.168.1.5")
    with pytest.raises(ValueError, match="base_url"):
        get_config()


def test_ssrf_guard_allows_public_https(clean_llm_env, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_BASE_URL", "https://8.8.8.8")
    cfg = get_config()  # 不抛
    assert cfg.base_url == "https://8.8.8.8"


# ==================== 运行时覆写测试 ====================

@pytest.fixture
async def override_env(temp_db, monkeypatch):
    """temp_db（带 app_setting 表的真实临时库）+ 清空 env，供覆写测试用。"""
    for k in list(__import__("os").environ):
        if k.startswith(("LLM_", "DEEPSEEK_")):
            monkeypatch.delenv(k, raising=False)
    return monkeypatch


@pytest.mark.database
async def test_override_in_db_takes_effect(override_env, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-env")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    from app.llm.runtime_config import write_runtime_override
    await write_runtime_override({"provider": "openai", "api_key": "sk-db"})
    cfg = get_config()
    assert cfg.provider == "openai"
    assert cfg.api_key == "sk-db"


@pytest.mark.database
async def test_override_partial_fields_keep_env_defaults(override_env, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-env")
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    from app.llm.runtime_config import write_runtime_override
    await write_runtime_override({"base_url": "https://api.openai.com"})
    cfg = get_config()
    # 未被覆写的字段仍来自 env
    assert cfg.api_key == "sk-env"
    assert cfg.model == "deepseek-chat"
    assert cfg.base_url == "https://api.openai.com"


@pytest.mark.unit
def test_resolve_config_no_require_key_does_not_raise(clean_llm_env):
    # 无 key 也不抛，供 GET 端点加载页面用
    cfg = _resolve_config(require_key=False)
    assert cfg.api_key == ""


# ==================== base_urls 锁定列表测试 ====================

def test_providers_have_base_urls_list():
    for name, p in PROVIDERS.items():
        assert "base_urls" in p, f"{name} 缺 base_urls"
        assert isinstance(p["base_urls"], list)


def test_default_base_url_is_first_in_base_urls():
    for name, p in PROVIDERS.items():
        if p["base_urls"]:
            assert p["default_base_url"] == p["base_urls"][0], name


def test_glm_has_coding_endpoint():
    assert "https://open.bigmodel.cn/api/coding/paas/v4" in PROVIDERS["glm"]["base_urls"]


def test_moonshot_has_global_endpoint():
    assert "https://api.moonshot.ai/v1" in PROVIDERS["moonshot"]["base_urls"]


def test_compatible_providers_have_empty_base_urls():
    assert PROVIDERS["openai-compatible"]["base_urls"] == []
    assert PROVIDERS["anthropic-compatible"]["base_urls"] == []


def test_provider_base_urls_helper():
    assert provider_base_urls("glm") == PROVIDERS["glm"]["base_urls"]
    assert provider_base_urls("openai-compatible") == []
    assert provider_base_urls("totally-unknown") == []
