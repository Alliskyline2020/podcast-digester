"""
HTML模板渲染器

使用Jinja2模板引擎生成精美的HTML摘要卡片
"""
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


def render_html_template(
    episode_data: Dict[str, Any],
    theme: str = "light",
    include_transcript: bool = False
) -> str:
    """
    渲染HTML模板

    Args:
        episode_data: EpisodeBundle数据，包含:
            - episode: 节目信息
            - chapters: 章节列表
            - summaries: 章节摘要列表
            - highlights: 趋势洞察
        theme: 主题 ('light' 或 'dark')
        include_transcript: 是否包含完整字幕

    Returns:
        渲染后的HTML字符串
    """
    try:
        # 获取模板目录
        template_dir = Path(__file__).parent
        env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=True  # 自动转义，防止XSS
        )

        # 加载模板
        template = env.get_template('template.html')

        # 准备模板数据
        episode = episode_data.get('episode', {})
        chapters = episode_data.get('chapters', [])
        summaries = episode_data.get('summaries', [])
        highlights = episode_data.get('highlights', [])

        # 格式化时间范围
        def format_time_range(start_ms: int, end_ms: int) -> str:
            """格式化时间范围"""
            def format_ms(ms: int) -> str:
                seconds = ms // 1000
                minutes = seconds // 60
                secs = seconds % 60
                return f"{minutes:02d}:{secs:02d}"

            return f"{format_ms(start_ms)} - {format_ms(end_ms)}"

        # 处理章节数据
        chapter_list = []
        for chapter in chapters:
            start_ms = chapter.get('start_ms', 0) if isinstance(chapter, dict) else getattr(chapter, 'start_ms', 0)
            end_ms = chapter.get('end_ms', 0) if isinstance(chapter, dict) else getattr(chapter, 'end_ms', 0)
            chapter_list.append({
                'title_zh': chapter.get('title_zh', '') if isinstance(chapter, dict) else getattr(chapter, 'title_zh', ''),
                'time_range': format_time_range(start_ms, end_ms),
                'start_ms': start_ms,
                'end_ms': end_ms
            })

        # 处理摘要数据
        summary_list = []
        for summary in summaries:
            # 从chapters中找到对应的章节标题和时间戳
            chapter_id = summary.get('chapter_id', '')
            chapter_title = ''
            time_range = ''

            # 在chapters中查找匹配的章节
            for chapter in chapters:
                ch_index = chapter.get('index', None) if isinstance(chapter, dict) else getattr(chapter, 'index', None)
                # 如果index匹配chapter_id (ch0 -> 0, ch1 -> 1)
                if ch_index is not None and chapter_id == f"ch{ch_index}":
                    chapter_title = chapter.get('title_zh', '') if isinstance(chapter, dict) else getattr(chapter, 'title_zh', '')
                    # 获取时间戳
                    start_ms = chapter.get('start_ms', 0) if isinstance(chapter, dict) else getattr(chapter, 'start_ms', 0)
                    end_ms = chapter.get('end_ms', 0) if isinstance(chapter, dict) else getattr(chapter, 'end_ms', 0)
                    time_range = format_time_range(start_ms, end_ms)
                    break

            summary_list.append({
                'title_zh': chapter_title or summary.get('chapter_id', ''),
                'content_zh': summary.get('content_zh', ''),
                'key_points_zh': summary.get('key_points_zh', []),
                'time_range': time_range
            })

        # 处理洞察数据
        highlight_list = []
        for highlight in highlights:
            # Highlight是Pydantic对象，使用getattr访问属性
            start_ms = getattr(highlight, 'start_ms', None)
            start_time = None
            if start_ms:
                seconds = start_ms // 1000
                minutes = seconds // 60
                secs = seconds % 60
                start_time = f"{minutes:02d}:{secs:02d}"

            highlight_list.append({
                'kind': getattr(highlight, 'kind', ''),
                'kind_label': _get_kind_label(getattr(highlight, 'kind', '')),
                'text_zh': getattr(highlight, 'text_zh', ''),
                'why_zh': getattr(highlight, 'why_zh', ''),
                'start_time': start_time
            })

        # 准备模板上下文
        context = {
            'title': episode.get('title', ''),
            'title_zh': episode.get('title_zh', ''),
            'tldr_zh': episode.get('tldr_zh', ''),
            'verdict': episode.get('worth_listening_verdict', ''),
            'verdict_label': _get_verdict_label(episode.get('worth_listening_verdict', '')),
            'target_audience_zh': episode.get('target_audience_zh', ''),
            'chapters': chapter_list,
            'summaries': summary_list,
            'highlights': highlight_list,
            'theme': theme,
            'include_transcript': include_transcript,
            'transcript': episode_data.get('transcript', []),
            'date': episode.get('publish_date', ''),
            'duration_min': episode.get('duration_min', 0)
        }

        logger.info(f"Template context prepared: {len(chapter_list)} chapters, {len(summary_list)} summaries, {len(highlight_list)} highlights")

        # 渲染模板
        html_content = template.render(**context)

        logger.info(f"HTML template rendered successfully for episode {episode.get('id')}")

        return html_content

    except Exception as e:
        logger.error(f"Failed to render HTML template: {e}")
        raise RuntimeError(f"Template rendering failed: {e}")


def _get_kind_label(kind: str) -> str:
    """获取亮点类型的中文标签"""
    labels = {
        'quote': '💬 金句',
        'insight': '💡 洞察',
        'fact': '📊 事实',
        'contrarian': '🔥 反观点',
        'story': '📖 故事'
    }
    return labels.get(kind, kind)


def _get_verdict_label(verdict: str) -> str:
    """获取值听裁定的中文标签"""
    labels = {
        'deep_listen': '🎧 值得细听',
        'skim_outline': '📝 快速浏览',
        'skip': '⏭️ 可跳过'
    }
    return labels.get(verdict, verdict)
