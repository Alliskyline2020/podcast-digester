"""
本地文件解析器
"""
import re
from pathlib import Path
from .base import BaseSourceParser, ParseResult
from ..utils.validation import validate_audio_path


class LocalFileParser(BaseSourceParser):
    """本地音频文件解析器"""

    PRIORITY = 20
    DESCRIPTION = "本地音频文件路径，直接映射 media URL"

    # 支持的音频格式
    AUDIO_EXTENSIONS = {".mp3", ".mp4", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".webm"}

    async def matches(self, raw_input: str) -> bool:
        """检测是否为本地文件路径"""
        path_str = raw_input.strip()

        # 检查文件扩展名
        if Path(path_str).suffix.lower() not in self.AUDIO_EXTENSIONS:
            return False

        # 尝试检查文件是否存在（仅对绝对路径）
        if Path(path_str).is_absolute():
            return Path(path_str).exists()

        # 检查是否看起来像文件路径（包含扩展名）
        return any(path_str.lower().endswith(ext) for ext in self.AUDIO_EXTENSIONS)

    async def parse(
        self,
        raw_input: str,
        episode_id: str,
        out_dir: Path,
        on_progress=None,
    ) -> ParseResult:
        """本地文件直接复制到输出目录"""
        input_path = Path(raw_input.strip()).expanduser().resolve()

        # 验证路径安全
        validate_audio_path(input_path)

        if not input_path.exists():
            raise FileNotFoundError(f"文件不存在: {raw_input}")

        # 确定输出路径
        audio_path = out_dir / f"audio{input_path.suffix}"

        # 复制文件
        import shutil
        shutil.copy2(input_path, audio_path)

        # 获取文件名作为标题
        title = input_path.stem

        return ParseResult(
            title=title,
            audio_path=audio_path,
            source_type="local",
        )
