"""
文件 I/O 工具
原子写入、安全读取等文件操作
"""
import json
import logging
import shutil
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class FileWriteError(Exception):
    """文件写入错误"""
    pass


def atomic_write(file_path: Path, content: str, encoding: str = "utf-8") -> None:
    """
    原子性文件写入

    使用临时文件 + 重命名确保写入过程的原子性：
    - 写入临时文件
    - 成功后原子性重命名（POSIX 保证）
    - 失败时清理临时文件

    Args:
        file_path: 目标文件路径
        content: 文件内容
        encoding: 文件编码（默认 utf-8）

    Raises:
        FileWriteError: 写入失败
    """
    temp_path = file_path.with_suffix(file_path.suffix + '.tmp')

    try:
        # 确保父目录存在
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入临时文件
        temp_path.write_text(content, encoding=encoding)

        # 原子性重命名（POSIX 保证原子性）
        temp_path.replace(file_path)

        logger.debug(f"Atomic write succeeded: {file_path}")

    except Exception as e:
        # 清理临时文件
        temp_path.unlink(missing_ok=True)
        logger.error(f"Atomic write failed for {file_path}: {e}")
        raise FileWriteError(f"Failed to write {file_path}: {e}") from None


def atomic_write_json(file_path: Path, data: Any, encoding: str = "utf-8",
                     indent: int = 2, ensure_ascii: bool = False) -> None:
    """
    原子性 JSON 文件写入

    Args:
        file_path: 目标文件路径
        data: Python 对象（会被序列化为 JSON）
        encoding: 文件编码
        indent: JSON 缩进空格数
        ensure_ascii: 是否确保 ASCII 编码

    Raises:
        FileWriteError: 写入失败或序列化失败
    """
    try:
        json_content = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    except (TypeError, ValueError) as e:
        logger.error(f"JSON serialization failed for {file_path}: {e}")
        raise FileWriteError(f"Failed to serialize JSON for {file_path}: {e}") from None

    atomic_write(file_path, json_content, encoding)


def safe_read_json(file_path: Path) -> Optional[dict]:
    """
    安全读取 JSON 文件

    Args:
        file_path: JSON 文件路径

    Returns:
        解析后的字典，文件不存在或读取失败时返回 None
    """
    if not file_path.exists():
        return None

    try:
        content = file_path.read_text(encoding="utf-8")
        return json.loads(content)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to read JSON from {file_path}: {e}")
        return None


def load_json_with_callback(file_path: Path, callback):
    """
    读取 JSON 文件并通过回调函数处理

    这是常用的加载模式：读取 JSON → 转换为模型对象 → 返回

    Args:
        file_path: JSON 文件路径
        callback: 处理数据的回调函数，接收 dict 参数

    Returns:
        回调函数的返回值，文件不存在或读取失败时返回 None

    Example:
        >>> transcript = load_json_with_callback(
        ...     transcript_file,
        ...     lambda data: Transcript(**data)
        ... )
    """
    if not file_path.exists():
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return callback(data)
    except (json.JSONDecodeError, IOError, TypeError, ValueError) as e:
        logger.warning(f"Failed to load JSON from {file_path}: {e}")
        return None


def safe_copy_file(src: Path, dst: Path) -> None:
    """
    安全复制文件

    Args:
        src: 源文件路径
        dst: 目标文件路径

    Raises:
        FileNotFoundError: 源文件不存在
        PermissionError: 权限不足
    """
    if not src.exists():
        raise FileNotFoundError(f"Source file not found: {src}")

    # 确保目标目录存在
    dst.parent.mkdir(parents=True, exist_ok=True)

    # 复制文件（保留元数据）
    shutil.copy2(src, dst)

    logger.debug(f"Copied {src} to {dst}")


def get_file_size(file_path: Path) -> int:
    """
    获取文件大小（字节）

    Args:
        file_path: 文件路径

    Returns:
        文件大小（字节），文件不存在时返回 0
    """
    try:
        return file_path.stat().st_size
    except FileNotFoundError:
        return 0
