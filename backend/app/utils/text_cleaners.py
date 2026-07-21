"""
文本清洗工具模块

提供统一的文本清洗功能，消除代码重复
"""
import re
from typing import List, Optional


# HTML实体映射
HTML_ENTITIES = {
    '&lt;': '<',
    '&gt;': '>',
    '&amp;': '&',
    '&quot;': '"',
    '&#39;': "'",
    '&nbsp;': ' ',
    '&mdash;': '—',
    '&ndash;': '–',
    '&hellip;': '…',
    '&copy;': '©',
    '&reg;': '®',
    '&trade;': '™',
}


# 默认语气词列表
DEFAULT_FILLER_WORDS = [
    '嗯', '啊', '哦', '呃', '那个',
    '就是', '然后', '接着', '或者说',
    'this', 'that', 'uh', 'um', 'like', 'you know'
]


def decode_html_entities(text: str) -> str:
    """
    解码HTML实体

    Args:
        text: 包含HTML实体的文本

    Returns:
        解码后的文本
    """
    if not text:
        return ""

    # 按顺序替换（避免重复替换）
    for entity, char in HTML_ENTITIES.items():
        text = text.replace(entity, char)

    return text


def remove_html_tags(text: str) -> str:
    """
    移除HTML标签（只移除已知的HTML标签，保留其他内容）

    已知HTML标签：b, i, u, strong, em, p, div, span, br, h1-h6, etc.

    Args:
        text: 包含HTML标签的文本

    Returns:
        移除标签后的文本

    Examples:
        >>> remove_html_tags("<b>hello</b>")
        'hello'
        >>> remove_html_tags("<world>")
        '<world>'  # 不是已知HTML标签，保留
    """
    if not text:
        return ""

    # 已知HTML标签列表（常用标签）
    known_tags = [
        'b', 'i', 'u', 'strong', 'em', 'p', 'div', 'span',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'br', 'hr', 'img', 'a', 'ul', 'ol', 'li',
        'table', 'tr', 'td', 'th', 'thead', 'tbody',
        'form', 'input', 'button', 'select', 'option',
        'header', 'footer', 'nav', 'aside', 'main',
        'section', 'article', 'figure', 'figcaption',
        'blockquote', 'code', 'pre', 'sub', 'sup',
        'del', 'ins', 'mark', 'small', 'cite', 'dfn',
        'abbr', 'acronym', 'address', 'time'
    ]

    # 构建正则表达式模式，匹配已知HTML标签
    # 包括：<tag>, </tag>, <tag attr="...">, <tag />
    tag_pattern = '|'.join(known_tags)
    pattern = fr'</?\s*(?:{tag_pattern})(?:\s+[^>]*)?\s*/?>'

    return re.sub(pattern, '', text, flags=re.IGNORECASE)


def remove_filler_words(
    text: str,
    filler_words: Optional[List[str]] = None,
    aggressive: bool = False
) -> str:
    """
    移除语气词

    Args:
        text: 原始文本
        filler_words: 语气词列表（None时使用默认列表）
        aggressive: 是否激进清洗（True：移除所有语气词，False：只移除单独的语气词）

    Returns:
        移除语气词后的文本
    """
    if not text:
        return ""

    if filler_words is None:
        filler_words = DEFAULT_FILLER_WORDS

    if not aggressive:
        # 保守模式：只移除单独的语气词（前后有空格）
        for filler in filler_words:
            text = re.sub(r'\s+' + re.escape(filler) + r'\s+', ' ', text)
    else:
        # 激进模式：移除所有语气词
        for filler in filler_words:
            # 移除边界上的语气词
            text = re.sub(r'\b' + re.escape(filler) + r'\b', '', text)
            # 移除单独的语气词
            text = re.sub(r'\s+' + re.escape(filler) + r'\s+', ' ', text)

    return text


def remove_special_symbols(text: str) -> str:
    """
    移除特殊符号（如[音乐]、[笑声]等）

    Args:
        text: 原始文本

    Returns:
        移除特殊符号后的文本
    """
    if not text:
        return ""

    # 移除常见的特殊符号标记
    patterns = [
        r'\[音乐?\]|\[笑声?\]|\[掌声?\]|\[applause?\]',
        r'\[.*?\]',  # 其他方括号内容
        r'\（.*?\）',  # 中文括号内容
        r'\(.*?\)',  # 英文括号内容
    ]

    for pattern in patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)

    return text


def normalize_whitespace(text: str) -> str:
    """
    标准化空白字符

    Args:
        text: 原始文本

    Returns:
        标准化后的文本
    """
    if not text:
        return ""

    # 将所有空白字符序列替换为单个空格
    text = re.sub(r'\s+', ' ', text)

    # 移除首尾空格
    text = text.strip()

    # 移除段首的特殊符号（标点）
    text = re.sub(r'^[，。、；：,.!?;:]+\s*', '', text)

    return text


def clean_text(
    text: str,
    aggressive: bool = True,
    remove_special: bool = False,
    filler_words: Optional[List[str]] = None
) -> str:
    """
    完整的文本清洗流程

    清洗步骤：
    1. 解码HTML实体
    2. 移除HTML标签
    3. 移除特殊符号（可选）
    4. 移除语气词
    5. 标准化空白字符

    Args:
        text: 原始文本
        aggressive: 是否激进清洗（包括语气词）
        remove_special: 是否移除特殊符号（如[音乐]等）
        filler_words: 自定义语气词列表（None时使用默认列表）

    Returns:
        清洗后的文本

    Examples:
        >>> clean_text("你好&lt;b&gt;啊&lt;/b&gt;")
        '你好啊'
        >>> clean_text("嗯 这个 就是 有点意思", aggressive=True)
        '这个 有点意思'
        >>> clean_text("[音乐]开始演唱", remove_special=True)
        '开始演唱'
    """
    if not text or not isinstance(text, str):
        return ""

    # 1. 解码HTML实体（必须先执行，避免标签残留）
    text = decode_html_entities(text)

    # 2. 移除HTML标签
    text = remove_html_tags(text)

    # 3. 移除特殊符号（可选）
    if remove_special:
        text = remove_special_symbols(text)

    # 4. 移除语气词
    text = remove_filler_words(text, filler_words, aggressive)

    # 5. 标准化空白字符
    text = normalize_whitespace(text)

    return text


def clean_segment_text(text: str) -> str:
    """
    清洗字幕segment文本（保守清洗）

    适用于字幕显示，只做基本的HTML清洗，不激进移除语气词

    Args:
        text: 原始字幕文本

    Returns:
        清洗后的字幕文本
    """
    return clean_text(text, aggressive=False)


def clean_llm_text(text: str) -> str:
    """
    清洗LLM生成文本（激进清洗）

    适用于LLM处理，移除语气词和特殊符号

    Args:
        text: LLM生成的文本

    Returns:
        清洗后的文本
    """
    return clean_text(text, aggressive=True, remove_special=True)


def is_text_clean(text: str, check_html: bool = True) -> bool:
    """
    检查文本是否已经清洗过

    Args:
        text: 待检查的文本
        check_html: 是否检查HTML标签和实体

    Returns:
        True表示文本已清洗，False表示需要清洗
    """
    if not text:
        return True

    if check_html:
        # 检查是否包含HTML实体或标签
        if '&lt;' in text or '&gt;' in text or '&amp;' in text:
            return False
        if '<' in text and '>' in text:
            # 可能包含HTML标签
            if re.search(r'<[^>]+>', text):
                return False

    # 检查是否有过多空白字符
    if re.search(r'\s{3,}', text):
        return False

    return True


# 音频事件标记(机械噪声): [音乐] [掌声] [笑声] [Music] [Applause] 等
_AUDIO_MARKER_RE = re.compile(
    r"\[(?:音乐|笑声?|掌声?|applause|music|laughter|noise|silence)\]",
    re.IGNORECASE,
)
# 零宽 / 方向控制字符(U+200B-200F, U+202A-202E, U+FEFF)
_ZERO_WIDTH_RE = re.compile(r"[​-‏‪-‮﻿]")


def preclean_mechanical(text: str) -> str:
    """确定性机械清洗: HTML 实体/标签、音频事件标记、零宽字符、空白。

    不删口水话/叠词/不改语义(那是 LLM 清洗的职责)。用于 LLM 清洗前的
    廉价预处理, 避免把机械垃圾喂给 LLM 浪费 token。
    """
    if not text or not isinstance(text, str):
        return ""
    text = decode_html_entities(text)
    text = remove_html_tags(text)
    text = _AUDIO_MARKER_RE.sub("", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = normalize_whitespace(text)
    return text
