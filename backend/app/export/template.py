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

        # 按 kind 分组（固定顺序：金句/洞察/事实/反常识/故事），导出按类别排列
        _KIND_ORDER = ['quote', 'insight', 'fact', 'contrarian', 'story']
        _groups_map = {}
        for hl in highlight_list:
            k = hl.get('kind') or 'insight'
            _groups_map.setdefault(k, []).append(hl)
        highlight_groups = []
        for _k in _KIND_ORDER:
            if _k in _groups_map:
                highlight_groups.append({
                    'label': _get_kind_label(_k),
                    'entries': _groups_map.pop(_k),  # 'entries' 避免 jinja2 dict.items 冲突
                })
        for _k, _items in _groups_map.items():
            highlight_groups.append({'label': _get_kind_label(_k) or _k, 'entries': _items})

        # 处理产品/技术/市场洞察（兼容旧 list[str] 和新结构化 shape）
        product_insight_groups = _build_product_insight_groups(
            episode_data.get('product_insights') or {}
        )

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
            'highlight_groups': highlight_groups,
            'product_insight_groups': product_insight_groups,
            'has_product_insights': len(product_insight_groups) > 0,
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
        'contrarian': '🔥 反常识',
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


# 产品洞察 domain 元信息
_DOMAIN_META = {
    'product': ('📦', '产品洞察'),
    'technical': ('⚙️', '技术洞察'),
    'market': ('📊', '市场/行业洞察'),
}

# category 中文标签
_CATEGORY_LABEL = {
    'product_strategy': '策略', 'product_ux': '体验',
    'product_growth': '增长', 'product_positioning': '定位',
    'tech_architecture': '架构', 'tech_eng_practice': '工程实践',
    'tech_trend': '技术趋势', 'tech_challenge': '技术挑战',
    'market_trend': '市场趋势', 'market_competition': '竞争格局',
    'market_business_model': '商业模式', 'market_opportunity': '机会点',
    'other': '其他',
}


def _extract_insight_items(pi_data: dict, domain_key: str) -> list:
    """从 product_insights 取指定 domain 的 items，兼容新旧 shape。

    新 shape: {domain_key: {items: [{text_zh, ...}]}}
    旧 shape: {domain_key_insights_zh: ["str", ...]}
    """
    if not isinstance(pi_data, dict):
        return []
    new = pi_data.get(domain_key)
    if isinstance(new, dict) and isinstance(new.get('items'), list):
        return new['items']
    legacy = pi_data.get(f"{domain_key}_insights_zh")
    if isinstance(legacy, list):
        return legacy
    return []


def _build_product_insight_groups(pi_data: dict) -> list:
    """构建模板友好的洞察分组（兼容新旧 shape）。

    返回 [{icon, label, items: [{text_zh, rationale_zh, category_label}]}, ...]
    """
    groups = []
    for domain_key in ('product', 'technical', 'market'):
        items = _extract_insight_items(pi_data, domain_key)
        if not items:
            continue
        icon, label = _DOMAIN_META[domain_key]
        rendered = []
        for it in items:
            if isinstance(it, dict):
                text = (it.get('text_zh') or '').strip()
                if not text:
                    continue
                category = it.get('category') or 'other'
                rendered.append({
                    'text_zh': text,
                    'rationale_zh': (it.get('rationale_zh') or '').strip(),
                    'category_label': _CATEGORY_LABEL.get(category, '其他'),
                })
            elif isinstance(it, str) and it.strip():
                # 旧 shape 的 str 元素
                rendered.append({
                    'text_zh': it.strip(),
                    'rationale_zh': '',
                    'category_label': '其他',
                })
        if rendered:
            # key 用 'insights' 而非 'items'：jinja2 里 group.items 会解析为
            # dict.items() 方法而非此 key，导致 for 循环报错
            groups.append({'icon': icon, 'label': label, 'insights': rendered})
    return groups
