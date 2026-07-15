"""LLM 提供方配置：PROVIDERS 预设表 + get_config() 统一读取 + SSRF 守卫。

设计（参考 qmreader）：
- provider  = 命名预设（用于填默认值 / UI 标题）
- provider_type = 实际协议（openai_compatible | anthropic_compatible），决定请求形状
- DEEPSEEK_* 环境变量作为向后兼容别名映射到 LLM_*。
"""
import ipaddress
import os
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from .runtime_config import read_runtime_override

logger = __import__("logging").getLogger(__name__)


# ==================== PROVIDERS 预设表 ====================
# 每个条目：title(展示名) / provider_type(协议) / default_base_url / base_urls / default_model
# base_url 留空 = 用 SDK 自带默认（OpenAI / Anthropic 官方端点）。
# URL 与模型名以厂商官方文档为准（impl 时已核对）。
PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "title": "DeepSeek",
        "provider_type": "openai_compatible",
        "default_base_url": "https://api.deepseek.com",
        "base_urls": ["https://api.deepseek.com"],
        "default_model": "deepseek-chat",
    },
    "openai": {
        "title": "OpenAI",
        "provider_type": "openai_compatible",
        "default_base_url": "https://api.openai.com/v1",
        "base_urls": ["https://api.openai.com/v1"],
        "default_model": "gpt-4o-mini",
    },
    "anthropic": {
        "title": "Anthropic (Claude)",
        "provider_type": "anthropic_compatible",
        "default_base_url": "https://api.anthropic.com",
        "base_urls": ["https://api.anthropic.com"],
        "default_model": "claude-3-5-sonnet-latest",
    },
    "glm": {
        "title": "智谱 GLM",
        "provider_type": "openai_compatible",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "base_urls": [
            "https://open.bigmodel.cn/api/paas/v4",          # 标准
            "https://open.bigmodel.cn/api/coding/paas/v4",   # 编码套件(Coding)
        ],
        "default_model": "glm-4-flash",
    },
    "qwen": {
        "title": "通义千问",
        "provider_type": "openai_compatible",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "base_urls": ["https://dashscope.aliyuncs.com/compatible-mode/v1"],
        "default_model": "qwen-plus",
    },
    "doubao": {
        "title": "字节豆包",
        "provider_type": "openai_compatible",
        "default_base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "base_urls": ["https://ark.cn-beijing.volces.com/api/v3"],
        # 豆包模型 id 实为 endpoint id，需用户在火山控制台创建后填入（模型下拉会拉不到，走手动输入）
        "default_model": "",
    },
    "moonshot": {
        "title": "月之暗面 Kimi",
        "provider_type": "openai_compatible",
        "default_base_url": "https://api.moonshot.cn/v1",
        "base_urls": [
            "https://api.moonshot.cn/v1",   # 国内
            "https://api.moonshot.ai/v1",   # 海外
        ],
        "default_model": "moonshot-v1-8k",
    },
    # 通用兜底：用户自填 base_url / model（无锁定列表 → 前端自由输入）
    "openai-compatible": {
        "title": "OpenAI 兼容(自定义端点)",
        "provider_type": "openai_compatible",
        "default_base_url": "",
        "base_urls": [],
        "default_model": "",
    },
    "anthropic-compatible": {
        "title": "Anthropic 兼容(自定义端点)",
        "provider_type": "anthropic_compatible",
        "default_base_url": "",
        "base_urls": [],
        "default_model": "",
    },
}


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    provider_type: str            # openai_compatible | anthropic_compatible
    api_key: str
    base_url: str                 # 可为空（用 SDK 默认）
    model: str
    temperature: float
    max_tokens: Optional[int]     # None = 不传，用 provider 默认
    timeout: float


def infer_provider_type(provider: str) -> str:
    """从 PROVIDERS 表推断协议。未知 provider 默认 openai_compatible（最通用）。"""
    entry = PROVIDERS.get(provider)
    if entry is None:
        return "openai_compatible"
    return entry["provider_type"]


def provider_base_urls(provider: str) -> list[str]:
    """该 provider 的固定 base_url 下拉列表。空列表 = 用户可自由输入。"""
    entry = PROVIDERS.get(provider, {})
    return list(entry.get("base_urls", []))


# ==================== SSRF 守卫 ====================
def _assert_public_https_base_url(base_url: str) -> None:
    """禁止把 LLM 请求打到内网/本机（参考 qmreader assertPublicHttpsBaseUrl）。

    空字符串放行（用 SDK 自带官方端点）。http 一律拒（LLM key 不可明文走 http）。
    """
    if not base_url:
        return
    parsed = urlparse(base_url)
    if parsed.scheme != "https":
        raise ValueError(f"base_url 必须是 https://：{base_url!r}")
    host = parsed.hostname or ""
    if host.endswith(".local"):
        raise ValueError(f"base_url 禁止指向 .local：{base_url!r}")
    try:
        # 解析所有 A/AAAA；任一落内网段即拒
        infos = __import__("socket").getaddrinfo(host, None)
    except OSError:
        raise ValueError(f"base_url 主机无法解析：{host!r}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError(f"base_url 禁止指向内网/本机地址 {ip}：{base_url!r}")


# ==================== 统一配置读取 ====================
def _resolve_config(require_key: bool = True) -> LLMConfig:
    """解析 LLM 配置。

    优先级：运行时覆写(app_setting) > LLM_* 环境变量 > DEEPSEEK_* 别名 > PROVIDERS 预设默认。

    require_key=False 时不强制 api_key（供「设置页」在未配置时也能加载）。
    """
    override = read_runtime_override()

    provider = override.get("provider") or os.getenv("LLM_PROVIDER", "deepseek")
    provider_type = (
        override.get("provider_type")
        or os.getenv("LLM_PROVIDER_TYPE")
        or infer_provider_type(provider)
    )

    preset = PROVIDERS.get(provider, {})

    # api_key：覆写里有就用覆写；否则 env 链
    if "api_key" in override:
        api_key = override.get("api_key") or ""
    else:
        api_key = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")

    if "base_url" in override:
        base_url = override.get("base_url") or preset.get("default_base_url", "")
    else:
        base_url = (
            os.getenv("LLM_BASE_URL")
            or os.getenv("DEEPSEEK_BASE_URL", "")
            or preset.get("default_base_url", "")
        )

    if "model" in override:
        model = override.get("model") or preset.get("default_model", "")
    else:
        model = (
            os.getenv("LLM_MODEL")
            or os.getenv("DEEPSEEK_MODEL", "")
            or preset.get("default_model", "")
        )

    temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    max_tokens_raw = os.getenv("LLM_MAX_TOKENS")
    max_tokens = int(max_tokens_raw) if max_tokens_raw else None
    timeout = float(os.getenv("LLM_TIMEOUT", "60"))

    if require_key and not api_key:
        raise ValueError(
            "LLM_API_KEY 未配置（也可用旧名 DEEPSEEK_API_KEY）。请在环境变量或设置页中设置。"
        )
    _assert_public_https_base_url(base_url)

    return LLMConfig(
        provider=provider,
        provider_type=provider_type,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )


def get_config() -> LLMConfig:
    """从环境变量 + 运行时覆写读取并校验 LLM 配置（要求 api_key）。"""
    return _resolve_config(require_key=True)
