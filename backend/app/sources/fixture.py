"""
Fixture 解析器 - 内置示例节目
"""
from pathlib import Path
from .base import BaseSourceParser, ParseResult


class FixtureParser(BaseSourceParser):
    """内置示例节目解析器"""

    PRIORITY = 10  # 最高优先级
    DESCRIPTION = "内置示例节目，即时返回，不走下载流程"

    # Fixture ID 列表
    FIXTURE_IDS = {"en_ai_pm", "zh_ai_agents"}

    async def matches(self, raw_input: str) -> bool:
        """检测是否为 fixture ID"""
        return raw_input.strip() in self.FIXTURE_IDS

    async def parse(
        self,
        raw_input: str,
        episode_id: str,
        out_dir: Path,
        on_progress=None,
    ) -> ParseResult:
        """Fixture 不需要下载，直接返回预构建的数据路径"""
        fixture_id = raw_input.strip()

        # 从 fixtures 目录加载
        from ..config import DATA_DIR
        fixture_dir = DATA_DIR.parent / "fixtures" / fixture_id
        if not fixture_dir.exists():
            raise FileNotFoundError(f"Fixture not found: {fixture_id}")

        # 读取 fixture 元数据
        import json
        meta_file = fixture_dir / "meta.json"
        if meta_file.exists():
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
                title = meta.get("title", fixture_id)
        else:
            title = f"Fixture: {fixture_id}"

        return ParseResult(
            title=title,
            audio_path=fixture_dir / "audio.mp3",  # Fixture 可以没有真实音频
            source_type="fixture",
            duration_ms=meta.get("duration_ms") if meta_file.exists() else None,
            language=meta.get("language") if meta_file.exists() else None,
            extra={
                "fixture_id": fixture_id,
                # 可以直接加载预构建的 transcript
                # "transcript": load_fixture_transcript(fixture_id),
            },
        )
