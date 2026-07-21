"""按标题命名导出音频副本到「音频库」目录。

下载完成（标题翻译之后），pipeline 把内部 audio 副本按标题命名复制一份到
``audio_library_dir``，方便用户在访达里按标题查找原始音频。pipeline 内部那份
``data/media/<episode_id>/`` 保持不动 —— 转录/洞察仍读它，这里只导出副本。

- 标题选择（中文优先、回退原始）由 pipeline 决定；本模块只接收最终标题。
- 扁平结构：``<dir>/<安全化标题>.<原扩展名>``。
- 文件名做跨文件系统安全化 + 按字节截断 + 重名自动加 ``(n)`` 后缀（不覆盖既有文件）。
"""
from __future__ import annotations

import re
import shutil
import unicodedata
from pathlib import Path

# 跨文件系统非法字符（含 macOS 的 ':' 与控制字符、Windows 的通配符等），统一替换为 '_'
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# 连续空白 → 单个空格（保留标题里的空格，访达里更可读）
_WS_RUN = re.compile(r"\s+")
# 连续下划线 → 单个下划线
_UNDERSCORE_RUN = re.compile(r"_+")
# 文件名（不含扩展名）字节预算。留余量给扩展名 + 重名后缀 " (999)"，
# 保证 < 255 字节（APFS / NTFS 文件名上限）。
_MAX_BASENAME_BYTES = 180
# 重名后缀上限，防止极端情况下死循环
_MAX_COLLISION_ATTEMPTS = 999
# 标题全空 / 全非法字符时的兜底名
_FALLBACK_NAME = "untitled"


def _truncate_bytes(text: str, max_bytes: int) -> str:
    """按字节截断到预算内，并退回到完整的 UTF-8 字符边界（不切碎多字节字符）。"""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # 先按字节砍，再用 ignore 丢掉被切坏的尾字符，最后去掉因截断产生的尾部分隔符
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return truncated.rstrip("._ ")


def sanitize_filename(name: str) -> str:
    """把任意标题安全化为可作文件名的字符串。

    - NFC 规范化（避免组合字符带来的怪异排序/重复）
    - 非法字符（含控制字符、路径分隔符、macOS 的 ':'）→ '_'
    - 连续空白/下划线合并；去掉首尾的 '.'、空格、下划线（前置 '.' 会让文件隐藏）
    - 全空 / 全非法 → 'untitled'
    - 按字节截断到预算内（CJK 每字符 3 字节，按字符截断会撞 255 字节上限）
    """
    if not name:
        return _FALLBACK_NAME
    cleaned = unicodedata.normalize("NFC", name)
    cleaned = _ILLEGAL_CHARS.sub("_", cleaned)
    cleaned = _WS_RUN.sub(" ", cleaned)
    cleaned = _UNDERSCORE_RUN.sub("_", cleaned).strip("._ ")
    if not cleaned:
        return _FALLBACK_NAME
    cleaned = _truncate_bytes(cleaned, _MAX_BASENAME_BYTES)
    return cleaned or _FALLBACK_NAME


def resolve_export_path(
    output_dir: Path, display_title: str, src_audio_path: Path
) -> Path:
    """计算导出目标路径：``<dir>/<安全化标题>.<原扩展名>``，重名自动加 ``(n)`` 后缀。

    纯函数 —— 不写盘，只返回首个尚不存在的目标路径。单用户单 worker 自托管场景
    下不存在并发同名竞态；若未来放开并发，调用方需自行加锁。
    """
    output_dir = Path(output_dir)
    ext = Path(src_audio_path).suffix  # 含 '.'，如 '.m4a'；无扩展名则为 ''
    base = sanitize_filename(display_title)

    candidate = output_dir / f"{base}{ext}"
    if not candidate.exists():
        return candidate

    for n in range(2, _MAX_COLLISION_ATTEMPTS + 1):
        candidate = output_dir / f"{base} ({n}){ext}"
        if not candidate.exists():
            return candidate

    # 999 个同名：极端兜底，直接返回同名（不抛错，保证 pipeline 不挂）
    return output_dir / f"{base}{ext}"


def save_audio_to_library(
    src_audio_path: Path, display_title: str, output_dir: Path
) -> Path:
    """把 src 音频按标题命名复制一份到 output_dir，返回目标路径。

    - src 必须存在，否则抛 FileNotFoundError（由调用方决定是否吞掉）。
    - 只复制、不移动/删除源（pipeline 内部副本继续供转录/洞察使用）。
    - 自动建目录；用 copy2 保留元数据与时间戳。
    """
    src = Path(src_audio_path)
    if not src.exists():
        raise FileNotFoundError(f"音频源文件不存在: {src}")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    dest = resolve_export_path(output_dir, display_title, src)
    shutil.copy2(src, dest)
    return dest
