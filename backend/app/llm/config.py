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

logger = __import__("logging").getLogger(__name__)


# ==================== PROVIDERS 预设表 ====================
# 每个条目：title(展示名) / provider_type(协议) / default_base_url / default_model
# base_url 留空 = 用 SDK 自带默认（OpenAI / Anthropic 官方端点）。
# URL 与模型名以厂商官方文档为准（impl 时已核对）。
PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "title": "DeepSeek",
        "provider_type": "openai_compatible",
        "default_base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
    },
    "openai": {
        "title": "OpenAI",
        "provider_type": "openai_compatible",
        "default_base_url": "",  # SDK 默认 https://api.openai.com/v1
        "default_model": "gpt-4o-mini",
    },
    "anthropic": {
        "title": "Anthropic (Claude)",
        "provider_type": "anthropic_compatible",
        "default_base_url": "",  # SDK 默认 https://api.anthropic.com
        "default_model": "claude-3-5-sonnet-latest",
    },
    "glm": {
        "title": "智谱 GLM",
        "provider_type": "openai_compatible",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
    },
    "qwen": {
        "title": "通义千问",
        "provider_type": "openai_compatible",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
    },
    "doubao": {
        "title": "字节豆包",
        "provider_type": "openai_compatible",
        "default_base_url": "https://ark.cn-beijing.volces.com/api/v3",
        # 豆包模型 id 实为 endpoint id，需用户在火山控制台创建后填入 LLM_MODEL
        "default_model": "",
    },
    "moonshot": {
        "title": "月之暗面 Kimi",
        "provider_type": "openai_compatible",
        "default_base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
    },
    # 通用兜底：用户自填 base_url / model
    "openai-compatible": {
        "title": "OpenAI 兼容（自定义端点）",
        "provider_type": "openai_compatible",
        "default_base_url": "",
        "default_model": "",
    },
    "anthropic-compatible": {
        "title": "Anthropic 兼容（自定义端点）",
        "provider_type": "anthropic_compatible",
        "default_base_url": "",
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
def get_config() -> LLMConfig:
    """从环境变量读取并校验 LLM 配置。

    优先级：LLM_* > DEEPSEEK_*（向后兼容别名）> PROVIDERS[provider] 默认值。
    """
    provider = os.getenv("LLM_PROVIDER", "deepseek")

    # 显式 LLM_PROVIDER_TYPE 胜出；否则从 provider 推断
    provider_type = os.getenv("LLM_PROVIDER_TYPE") or infer_provider_type(provider)

    # API key / base_url / model：LLM_* 优先，回退 DEEPSEEK_* 别名，再回退 registry 默认
    api_key = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")
    preset = PROVIDERS.get(provider, {})
    base_url = (
        os.getenv("LLM_BASE_URL")
        or os.getenv("DEEPSEEK_BASE_URL", "")
        or preset.get("default_base_url", "")
    )
    model = (
        os.getenv("LLM_MODEL")
        or os.getenv("DEEPSEEK_MODEL", "")
        or preset.get("default_model", "")
    )

    temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    max_tokens_raw = os.getenv("LLM_MAX_TOKENS")
    max_tokens = int(max_tokens_raw) if max_tokens_raw else None
    timeout = float(os.getenv("LLM_TIMEOUT", "60"))

    if not api_key:
        raise ValueError(
            "LLM_API_KEY 未配置（也可用旧名 DEEPSEEK_API_KEY）。请在环境变量中设置。"
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
