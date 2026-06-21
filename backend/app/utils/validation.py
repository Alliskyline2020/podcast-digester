"""
输入验证工具
防止命令注入、路径遍历等安全风险
"""
import re
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional


# ==================== URL 验证 ====================

def validate_url(url: str) -> bool:
    """
    验证 URL 格式是否合法

    Args:
        url: 待验证的 URL

    Returns:
        True 如果 URL 合法，否则 False
    """
    try:
        # URL 长度限制
        if len(url) > 2000:
            return False

        cleaned = url.strip()
        result = urlparse(cleaned)

        # 检查协议和域名
        if not result.scheme or result.scheme not in ("http", "https"):
            return False
        if not result.netloc or "." not in result.netloc:
            return False

        # 检查 URL 中没有危险字符
        dangerous_chars = ['\n', '\r', '\x00', '\t', '\x1b']
        if any(char in cleaned for char in dangerous_chars):
            return False

        # 检查域名的有效性（基本格式）
        # 域名部分只允许字母、数字、连字符和点
        netloc = result.netloc.split(':')[0]  # 移除端口
        if not re.match(r'^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', netloc):
            # 允许 localhost 或 IP 地址
            if netloc not in ('localhost', '127.0.0.1'):
                if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', netloc):
                    return False

        return True
    except Exception:
        return False


def sanitize_url(url: str) -> str:
    """
    清理 URL，移除潜在的危险字符

    Args:
        url: 待清理的 URL

    Returns:
        清理后的 URL
    """
    # 移除所有控制字符和危险字符
    dangerous_chars = ['\n', '\r', '\x00', '\t', '\x1b', '\x08', '\x0c']
    cleaned = url.strip()
    for char in dangerous_chars:
        cleaned = cleaned.replace(char, '')
    return cleaned


# ==================== 路径验证 ====================

# 允许的根目录
_ALLOWED_ROOTS = [
    Path.home(),  # 用户主目录
    Path("/media"),  # 系统媒体目录（如果有）
]

# 允许的音频扩展名
_AUDIO_EXTENSIONS = {".mp3", ".mp4", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".webm"}


def validate_audio_path(file_path: Path) -> bool:
    """
    验证音频文件路径是否安全且合法

    Args:
        file_path: 文件路径

    Returns:
        True 如果路径安全，否则 False

    Raises:
        ValueError: 路径不安全时
    """
    # 解析路径
    try:
        resolved = file_path.expanduser().resolve()
    except Exception:
        raise ValueError(f"无效的路径: {file_path}")

    # 检查路径在允许的根目录下
    is_allowed = False
    for allowed_root in _ALLOWED_ROOTS:
        try:
            resolved.relative_to(allowed_root)
            is_allowed = True
            break
        except ValueError:
            continue

    if not is_allowed:
        # 检查是否在项目数据目录内
        from ..config import DATA_DIR
        try:
            resolved.relative_to(DATA_DIR)
            is_allowed = True
        except ValueError:
            pass

    if not is_allowed:
        raise ValueError(
            f"路径不在允许的目录内: {resolved}。"
            f"只允许访问用户主目录或项目数据目录"
        )

    # 检查文件扩展名
    if resolved.exists() and resolved.is_file():
        if resolved.suffix.lower() not in _AUDIO_EXTENSIONS:
            raise ValueError(
                f"不支持的文件类型: {resolved.suffix}。"
                f"支持的类型: {', '.join(_AUDIO_EXTENSIONS)}"
            )

    return True


def validate_safe_path(file_path: Path) -> bool:
    """
    快速检查路径是否安全（用于文件读取操作前）

    Args:
        file_path: 文件路径

    Returns:
        True 如果路径安全，否则 False
    """
    try:
        resolved = file_path.expanduser().resolve()
    except Exception:
        return False

    # 检查路径不在敏感系统目录
    sensitive_paths = [
        Path("/etc"), Path("/root"), Path("/sys"),
        Path("/proc"), Path("/dev"), Path("/run"),
    ]

    for sensitive in sensitive_paths:
        try:
            resolved.relative_to(sensitive)
            return False  # 在敏感目录下
        except ValueError:
            pass  # 无法访问，可能在敏感目录外

    return True


# ==================== 输入验证 ====================

def validate_raw_input(raw_input: str) -> str:
    """
    验证并清理用户输入

    Args:
        raw_input: 原始用户输入

    Returns:
        清理后的输入

    Raises:
        ValueError: 输入不安全时
    """
    if not raw_input or not raw_input.strip():
        raise ValueError("输入不能为空")

    cleaned = raw_input.strip()

    # 检查是否为 URL
    if cleaned.startswith(("http://", "https://")):
        if not validate_url(cleaned):
            raise ValueError("无效的 URL 格式")
        return sanitize_url(cleaned)

    # 检查是否为本地文件路径
    if cleaned.startswith("/") or cleaned.startswith("~") or (
        len(cleaned) > 1 and cleaned[1] == ":"
    ):
        try:
            path = Path(cleaned)
            validate_audio_path(path)
            return str(path)
        except ValueError:
            # 可能是 fixture ID
            pass

    # 最后检查长度限制
    if len(cleaned) > 2000:
        raise ValueError("输入过长，请检查")

    return cleaned


# ==================== 字符串验证 ====================

def is_safe_string(s: str, max_length: int = 500) -> bool:
    """
    检查字符串是否安全（不含危险字符）

    Args:
        s: 待检查的字符串
        max_length: 最大长度限制

    Returns:
        True 如果字符串安全
    """
    if not s or len(s) > max_length:
        return False

    # 检查控制字符和特殊序列
    dangerous_patterns = [
        r'\x00',  # 空字节
        r'\r\n',  # CRLF（可能用于CRLF注入）
        r'<script',  # XSS 风险
        r'javascript:',  # XSS 风险
    ]

    s_lower = s.lower()
    for pattern in dangerous_patterns:
        if pattern in s_lower:
            return False

    return True
