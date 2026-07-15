"""app/llm/config 单元测试：PROVIDERS、get_config 别名、provider_type 推断、SSRF 守卫。"""
import pytest

from app.llm.config import (
    PROVIDERS, get_config, infer_provider_type, LLMConfig, _resolve_config,
    provider_base_url_editable, resolve_effective_base_url,
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
    for name in ("deepseek", "openai", "anthropic", "glm", "glm-coding", "qwen", "doubao", "moonshot"):
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


# ==================== SSRF 加固：云元数据 / 字面量 IP（防重定向外的补充）====================

def test_ssrf_guard_blocks_alibaba_metadata(clean_llm_env, monkeypatch):
    # 阿里云 ECS 元数据 100.100.100.200：is_private 不覆盖，须显式拒绝
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_BASE_URL", "https://100.100.100.200")
    with pytest.raises(ValueError, match="base_url"):
        get_config()


def test_ssrf_guard_blocks_cgnat_range(clean_llm_env, monkeypatch):
    # RFC 6598 CGNAT 100.64.0.0/10：is_private 不覆盖，须显式拒绝
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_BASE_URL", "https://100.64.10.20")
    with pytest.raises(ValueError, match="base_url"):
        get_config()


def test_ssrf_guard_blocks_suspicious_ip_literal(clean_llm_env, monkeypatch):
    # 0177.0.0.1 这类带前导零的「伪字面量」：getaddrinfo 会当成公网 177.0.0.1 放行，
    # 但 httpx 可能按八进制解析 → guard 与客户端解析不一致的隐患，直接拒。
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_BASE_URL", "https://0177.0.0.1")
    with pytest.raises(ValueError, match="base_url"):
        get_config()


def test_ssrf_guard_literal_ip_skips_dns(clean_llm_env, monkeypatch):
    # 字面量公网 IP 不走 DNS：消除 check / use 之间的 rebinding 窗口
    import app.llm.config as cfgmod
    def _boom(*a, **k):
        raise OSError("字面量 IP 不应触发 DNS 解析")
    monkeypatch.setattr(cfgmod.socket, "getaddrinfo", _boom)
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_BASE_URL", "https://8.8.8.8")
    cfg = get_config()  # 不抛，且不调 getaddrinfo
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


# ==================== base_url 锁定（1 provider = 1 url）测试 ====================

def test_providers_have_default_base_url():
    for name, p in PROVIDERS.items():
        assert "default_base_url" in p, f"{name} 缺 default_base_url"


def test_glm_standard_and_coding_are_separate_providers():
    # 标准 GLM 与编码套件拆成两个独立 provider，各自一个固定 url
    assert PROVIDERS["glm"]["default_base_url"] == "https://open.bigmodel.cn/api/paas/v4"
    assert "glm-coding" in PROVIDERS
    assert PROVIDERS["glm-coding"]["default_base_url"] == "https://open.bigmodel.cn/api/coding/paas/v4"
    assert PROVIDERS["glm-coding"]["title"] == "智谱 GLM Coding Plan"


def test_moonshot_has_single_url():
    assert PROVIDERS["moonshot"]["default_base_url"] == "https://api.moonshot.cn/v1"


def test_provider_base_url_editable_helper():
    # 命名厂商锁定
    assert provider_base_url_editable("deepseek") is False
    assert provider_base_url_editable("glm") is False
    assert provider_base_url_editable("glm-coding") is False
    # 兼容自定义端点可编辑
    assert provider_base_url_editable("openai-compatible") is True
    assert provider_base_url_editable("anthropic-compatible") is True
    # 未知 provider 视为可编辑
    assert provider_base_url_editable("totally-unknown") is True


def test_resolve_effective_base_url_locked_forces_default():
    # 锁定型：无论表单/已保存传什么，一律用预设默认（防篡改）
    assert resolve_effective_base_url("deepseek", "http://127.0.0.1/x", "") == "https://api.deepseek.com"
    assert resolve_effective_base_url("glm-coding", None, "whatever") == "https://open.bigmodel.cn/api/coding/paas/v4"


def test_resolve_effective_base_url_editable_uses_form_or_saved():
    assert resolve_effective_base_url("openai-compatible", "https://my.proxy/v1", "https://old/v1") == "https://my.proxy/v1"
    assert resolve_effective_base_url("openai-compatible", None, "https://saved/v1") == "https://saved/v1"
    assert resolve_effective_base_url("openai-compatible", "", "") == ""


# ==================== region（国内/国际）测试 ====================

def test_providers_have_region_field():
    for name, p in PROVIDERS.items():
        assert "region" in p, f"{name} 缺 region"
        assert p["region"] in ("国内", "国际", ""), f"{name} region 取值非法: {p['region']!r}"


def test_region_classification():
    domestic = {"deepseek", "glm", "glm-coding", "qwen", "doubao", "moonshot"}
    overseas = {"openai", "anthropic"}
    compat = {"openai-compatible", "anthropic-compatible"}
    for name in domestic:
        assert PROVIDERS[name]["region"] == "国内", f"{name} 应为国内"
    for name in overseas:
        assert PROVIDERS[name]["region"] == "国际", f"{name} 应为国际"
    for name in compat:
        assert PROVIDERS[name]["region"] == "", f"{name} 应为地区无关(空)"
