"""LLM 提供方配置：PROVIDERS 预设表 + get_config() 统一读取 + SSRF 守卫。

设计（参考 qmreader）：
- provider  = 命名预设（用于填默认值 / UI 标题）
- provider_type = 实际协议（openai_compatible | anthropic_compatible），决定请求形状
- DEEPSEEK_* 环境变量作为向后兼容别名映射到 LLM_*。
"""
import ipaddress
import os
import socket
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from .runtime_config import read_runtime_override

logger = __import__("logging").getLogger(__name__)


# ==================== PROVIDERS 预设表 ====================
# 每个条目：title(展示名) / provider_type(协议) / default_base_url / default_model / region
# 设计：1 provider = 1 固定 base_url。不同端点/套餐拆成独立 provider
# （如「智谱 GLM」标准端点 vs「智谱 GLM Coding Plan」编码套件端点）。
# default_base_url 留空 = 兼容自定义端点，base_url 可由用户自由填写。
# region：国内/国际 用于设置页区域筛选；空 = 兼容自定义端点（地区无关，常驻底部）。
# URL 与模型名以厂商官方文档为准（impl 时已核对）。
PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "title": "DeepSeek",
        "provider_type": "openai_compatible",
        "default_base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "region": "国内",
    },
    "openai": {
        "title": "OpenAI",
        "provider_type": "openai_compatible",
        "default_base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "region": "国际",
    },
    "anthropic": {
        "title": "Anthropic (Claude)",
        "provider_type": "anthropic_compatible",
        "default_base_url": "https://api.anthropic.com",
        "default_model": "claude-3-5-sonnet-latest",
        "region": "国际",
    },
    "glm": {
        "title": "智谱 GLM",
        "provider_type": "openai_compatible",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",          # 标准端点
        "default_model": "glm-4-flash",
        "region": "国内",
    },
    "glm-coding": {
        "title": "智谱 GLM Coding Plan",
        "provider_type": "openai_compatible",
        "default_base_url": "https://open.bigmodel.cn/api/coding/paas/v4",   # 编码套件(Coding)专用端点
        "default_model": "",   # 套餐模型需拉取后选择
        "region": "国内",
    },
    "qwen": {
        "title": "通义千问",
        "provider_type": "openai_compatible",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "region": "国内",
    },
    "doubao": {
        "title": "字节豆包",
        "provider_type": "openai_compatible",
        "default_base_url": "https://ark.cn-beijing.volces.com/api/v3",
        # 豆包模型 id 实为 endpoint id，需用户在火山控制台创建后填入（模型下拉会拉不到，走手动输入）
        "default_model": "",
        "region": "国内",
    },
    "moonshot": {
        "title": "月之暗面 Kimi",
        "provider_type": "openai_compatible",
        "default_base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
        "region": "国内",
    },
    # 通用兜底：用户自填 base_url / model（default_base_url 空 = 可自由输入；region 空 = 地区无关）
    "openai-compatible": {
        "title": "OpenAI 兼容(自定义端点)",
        "provider_type": "openai_compatible",
        "default_base_url": "",
        "default_model": "",
        "region": "",
    },
    "anthropic-compatible": {
        "title": "Anthropic 兼容(自定义端点)",
        "provider_type": "anthropic_compatible",
        "default_base_url": "",
        "default_model": "",
        "region": "",
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


def provider_base_url_editable(provider: str) -> bool:
    """该 provider 的 base_url 是否可由用户自由填写。
    命名厂商(default_base_url 非空) = 锁定为预设 url；兼容自定义端点(空) = 可编辑。
    未知 provider 视为可编辑（自由输入）。"""
    return not bool(PROVIDERS.get(provider, {}).get("default_base_url"))


def resolve_effective_base_url(
    provider: str, form_base_url: str | None, saved_base_url: str
) -> str:
    """解析实际生效的 base_url。

    锁定型 provider 一律返回预设 default_base_url（忽略表单/已保存值，防篡改，
    与前端只读展示一致）；可编辑型用表单值，缺省回退已保存值。
    返回值仍需在各端点过 SSRF 守卫（见 _assert_public_https_base_url）。
    """
    if provider_base_url_editable(provider):
        return form_base_url if form_base_url else saved_base_url
    return PROVIDERS.get(provider, {}).get("default_base_url", "")


# ==================== SSRF 守卫 ====================
# 云元数据 / CGNAT 显式拒绝名单：ipaddress.is_private 不覆盖 RFC 6598（100.64.0.0/10）
# 与阿里云元数据 100.100.100.200，须显式拦截。
_METADATA_NETWORKS = [
    ipaddress.ip_network("169.254.169.254/32"),   # AWS / Azure / GCP 元数据
    ipaddress.ip_network("100.100.100.200/32"),   # 阿里云 ECS 元数据
    ipaddress.ip_network("100.64.0.0/10"),        # RFC 6598 CGNAT
]


def _assert_public_https_base_url(base_url: str) -> None:
    """禁止把 LLM 请求打到内网/本机/云元数据（参考 qmreader assertPublicHttpsBaseUrl）。

    空字符串放行（用 SDK 自带官方端点）。http 一律拒（LLM key 不可明文走 http）。
    字面量 IP 走 ipaddress 直接分类——与 httpx 解析口径一致；且字面量不经 DNS，
    消除「校验时解析公网、连接时 DNS 重绑定到内网」的 TOCTOU 窗口。
    """
    if not base_url:
        return
    parsed = urlparse(base_url)
    if parsed.scheme != "https":
        raise ValueError(f"base_url 必须是 https://：{base_url!r}")
    host = parsed.hostname or ""
    if host.endswith(".local"):
        raise ValueError(f"base_url 禁止指向 .local：{base_url!r}")

    # 字面量 IP 直接分类；主机名才走 DNS 解析所有 A/AAAA
    try:
        resolved = [ipaddress.ip_address(host)]
    except ValueError:
        # 仅含数字与点却非合法 IPv4 字面量（如 0177.0.0.1 / 2130706433）：
        # getaddrinfo 可能按八进制/十进制解出公网地址、与 httpx 口径不一致 → 可疑，直接拒。
        if host and all(c.isdigit() or c == "." for c in host):
            raise ValueError(f"base_url 主机为可疑 IP 字面量：{host!r}")
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            raise ValueError(f"base_url 主机无法解析：{host!r}")
        resolved = [ipaddress.ip_address(info[4][0]) for info in infos]

    for ip in resolved:
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or any(ip in net for net in _METADATA_NETWORKS)):
            raise ValueError(f"base_url 禁止指向内网/本机/元数据地址 {ip}：{base_url!r}")


# 热路径守卫记忆化：同一 base_url 校验通过即缓存，避免每次 LLM 调用都重复一次
# 阻塞的 getaddrinfo。仅缓存「通过」结果（不合法的会在入集合前抛 ValueError）；
# 坏配置本就让请求失败，重复校验开销可忽略，故失败不缓存。
_SSRF_VERIFIED_URLS: set[str] = set()


def _assert_public_https_base_url_cached(base_url: str) -> None:
    """_assert_public_https_base_url 的记忆化包装（供 _resolve_config 热路径用）。"""
    if base_url in _SSRF_VERIFIED_URLS:
        return
    _assert_public_https_base_url(base_url)
    _SSRF_VERIFIED_URLS.add(base_url)


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

    # base_url：DB 覽写 > LLM_* env > DEEPSEEK_* 别名 > 预设默认。
    # 注意：锁定型 provider 的「固定 url」只约束设置页 UI + PUT 写入；
    # 这里仍保留 LLM_BASE_URL 环境变量作为运维逃生舱（如企业代理/镜像网关）。
    base_url_from_override = "base_url" in override
    if base_url_from_override:
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
    # 仅 DB 覆写来源（设置页用户输入）过 SSRF 守卫；env/预设视为运维可信放行。
    # 用记忆化版本，避免热路径每次请求都重复一次阻塞的 getaddrinfo。
    if base_url_from_override and base_url:
        _assert_public_https_base_url_cached(base_url)

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
