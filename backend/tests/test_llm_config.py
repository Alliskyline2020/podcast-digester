"""app/llm/config 单元测试：PROVIDERS、get_config 别名、provider_type 推断、SSRF 守卫。"""
import pytest

from app.llm.config import (
    PROVIDERS, get_config, infer_provider_type, LLMConfig,
)


@pytest.fixture
def clean_llm_env(monkeypatch):
    """清空所有 LLM/DEEPSEEK 环境变量，每个用例显式 set 需要的。"""
    for k in list(__import__("os").environ):
        if k.startswith(("LLM_", "DEEPSEEK_")):
            monkeypatch.delenv(k, raising=False)
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
