"""
播客整理项目 - 数据模型
Pydantic v2 严格模型定义
"""
from datetime import datetime
from enum import Enum
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field, model_validator


class EpisodeStatus(str, Enum):
    """节目处理状态机"""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    ASR_RUNNING = "asr_running"
    LLM_RUNNING = "llm_running"
    READY = "ready"
    FAILED = "failed"


class VerdictType(str, Enum):
    """值听裁定"""
    DEEP_LISTEN = "deep_listen"
    SKIM_OUTLINE = "skim_outline"
    SKIP = "skip"


class ConfidenceType(str, Enum):
    """置信度"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class HighlightKind(str, Enum):
    """亮点类型"""
    QUOTE = "quote"
    INSIGHT = "insight"
    FACT = "fact"
    CONTRARIAN = "contrarian"
    STORY = "story"


class EpisodeType(str, Enum):
    """节目类型"""
    PODCAST = "podcast"
    LAUNCH = "launch"
    INTERVIEW = "interview"
    TALK_SHOW = "talk_show"
    OTHER = "other"


# ==================== 基础模型 ====================

class Segment(BaseModel):
    """字幕段落"""
    id: int = Field(..., description="段落序号（0 起）")
    start_ms: int = Field(..., description="段落开始时间（毫秒）")
    end_ms: int = Field(..., description="段落结束时间（毫秒）")
    text_original: str = Field(..., description="原始语言文本")
    text_translated: Optional[str] = Field(None, description="中文翻译")
    text_with_punct: Optional[str] = Field(None, description="带标点符号的文本（后处理添加）")
    speaker: Optional[str] = Field(None, description="说话人标签")
    text_zh: Optional[str] = Field(None, description="中文文本（无论原文还是译文）")
    text_en: Optional[str] = Field(None, description="英文文本（无论原文还是译文）")


class Transcript(BaseModel):
    """完整转录"""
    episode_id: str = Field(..., description="节目 ID")
    language: str = Field(..., description="检测到的语言 zh/en/unknown")
    segments: List[Segment] = Field(default_factory=list, description="所有字幕段")


class OutlineEntry(BaseModel):
    """章节条目"""
    title_zh: str = Field(..., description="中文章节标题")
    start_ms: int = Field(..., description="章节开始时间")
    end_ms: int = Field(..., description="章节结束时间")
    start_segment_id: int = Field(..., description="起始段落ID")
    end_segment_id: int = Field(..., description="结束段落ID")
    index: int = Field(..., description="章节索引")
    chapter_summary_id: Optional[str] = Field(None, description="关联的章节摘要ID")


class Outline(BaseModel):
    """章节大纲"""
    episode_id: str = Field(..., description="节目 ID")
    entries: List[OutlineEntry] = Field(default_factory=list, description="章节列表")


class ChapterSummary(BaseModel):
    """章节摘要"""
    chapter_id: str = Field(..., description="章节 ID，如 ch0, ch1")
    content_zh: str = Field(..., min_length=50, max_length=500, description="章节摘要内容")
    key_points_zh: List[str] = Field(..., min_items=2, max_items=10, description="关键点列表")
    cited_segment_ids: List[int] = Field(..., min_items=0, max_items=200, description="引用的段落 id")


class HighlightItem(BaseModel):
    """单条亮点"""
    kind: HighlightKind = Field(default=HighlightKind.INSIGHT, description="亮点类型")
    text_zh: str = Field(default="", description="亮点正文（prompt 中已约定 30-80 字）")
    why_zh: str = Field(default="", description="价值说明（prompt 中已约定 10-30 字）")
    cited_segment_ids: List[int] = Field(default_factory=list, description="支撑原文段落 id")
    start_ms: Optional[int] = Field(None, description="点击亮点跳转时间")


class HighlightCard(BaseModel):
    """亮点卡"""
    tldr_zh: str = Field(..., description="总结（prompt 中已约定 200-400 字）")
    worth_listening_verdict: VerdictType = Field(..., description="值听裁定")
    verdict_confidence: ConfidenceType = Field(..., description="置信度")
    target_audience_zh: str = Field(..., description="受众描述（prompt 中已约定 30-60 字）")
    highlights: List[HighlightItem] = Field(default_factory=list, description="精华亮点列表")
    estimated_time_saved_min: Optional[int] = Field(None, description="节省时间（skip/skim 时）")


class IngestStage(BaseModel):
    """处理阶段"""
    name: str = Field(..., description="阶段名称")
    status: EpisodeStatus = Field(..., description="阶段状态")
    progress: float = Field(default=0.0, ge=0, le=1, description="进度 0-1")
    current: Optional[int] = Field(None, description="已处理量(如已润色段数)")
    total: Optional[int] = Field(None, description="总量(如总段数)")
    error: Optional[str] = Field(None, description="错误信息")
    started_at: Optional[datetime] = Field(None, description="开始时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")


class IngestJob(BaseModel):
    """处理任务"""
    episode_id: str = Field(..., description="节目 ID")
    current_stage: str = Field(default="pending", description="当前阶段")
    stages: List[IngestStage] = Field(default_factory=list, description="所有阶段")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")


# ==================== 核心模型 ====================

class Episode(BaseModel):
    """节目基础信息"""
    id: str = Field(..., description="ep_{timestamp_ms} 或 fixture id")
    title: str = Field(..., description="节目标题（原文）")
    title_zh: Optional[str] = Field(None, description="中文标题（英文标题翻译后；纯中文标题则与 title 一致）")
    status: EpisodeStatus = Field(..., description="处理状态")
    language: Optional[str] = Field(None, description="zh/en/unknown")
    media_path: Optional[str] = Field(None, description="/media/{id}/audio.*")
    is_fixture: bool = Field(default=False, description="是否为内置示例")
    error_msg: Optional[str] = Field(None, description="失败时的错误信息")
    source_type: Optional[str] = Field(None, description="来源平台类型")
    source_url: Optional[str] = Field(None, description="原始URL（用于恢复任务）")
    episode_type: EpisodeType = Field(default=EpisodeType.OTHER, description="节目类型")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")
    last_activity_ts: Optional[datetime] = Field(None, description="最后播放时间")
    paragraph_mappings: Optional[List[Dict[str, Any]]] = Field(None, description="字幕段落与原始segments的映射关系")


# ==================== 专项分析模型 ====================

class LaunchSpecCard(BaseModel):
    """发布会规格卡"""
    product_name: str
    specs: Dict[str, str] = Field(default_factory=dict)
    key_highlights: List[str] = Field(default_factory=list)


class LaunchProductInsight(BaseModel):
    """发布会产品洞察"""
    highlights: List[str] = Field(default_factory=list)
    shortcomings: List[str] = Field(default_factory=list)
    innovations: List[str] = Field(default_factory=list)
    value_verdict: str


class LaunchMarketingInsight(BaseModel):
    """发布会营销洞察"""
    opening_strategy: str
    product_reveal_time: str
    eco_ratio: str
    competitors_mentioned: List[str] = Field(default_factory=list)
    pricing_strategy: str


class LaunchAnalysis(BaseModel):
    """发布会分析结果"""
    episode_id: str
    spec_card: LaunchSpecCard
    product_insight: LaunchProductInsight
    marketing_insight: LaunchMarketingInsight


class PodcastViewpoint(BaseModel):
    """播客观点"""
    speaker: str
    main_argument: str
    supporting_quotes: List[str] = Field(default_factory=list)


class PodcastDisagreement(BaseModel):
    """播客分歧点"""
    topic: str
    parties: List[str]
    resolution: str


class PodcastConsensus(BaseModel):
    """播客共识点"""
    content: str


class PodcastViewpoints(BaseModel):
    """播客观点集合"""
    viewpoints: List[PodcastViewpoint] = Field(default_factory=list)
    disagreements: List[PodcastDisagreement] = Field(default_factory=list)
    consensus: List[PodcastConsensus] = Field(default_factory=list)


class PodcastStory(BaseModel):
    """播客故事/轶事"""
    title: str
    description: str
    key_people: List[str] = Field(default_factory=list)
    cited_segment_ids: List[int] = Field(default_factory=list)


class PodcastInsiderData(BaseModel):
    """行业内幕数据"""
    metric: str
    value: str
    context: str
    cited_segment_ids: List[int] = Field(default_factory=list)


class PodcastAdvice(BaseModel):
    """从业建议"""
    target: str
    tip: str
    cited_segment_ids: List[int] = Field(default_factory=list)


class PodcastIntel(BaseModel):
    """播客情报"""
    stories: List[PodcastStory] = Field(default_factory=list)
    insider_data: List[PodcastInsiderData] = Field(default_factory=list)
    advice: List[PodcastAdvice] = Field(default_factory=list)


class PodcastAnalysis(BaseModel):
    """播客分析结果"""
    episode_id: str
    viewpoints: PodcastViewpoints
    insights: PodcastIntel


# ==================== 产品和技术洞察 ====================

class InsightCategory(str, Enum):
    """洞察细分维度（前缀命名避免不同域的 trend 冲突）"""
    # product
    PRODUCT_STRATEGY = "product_strategy"
    PRODUCT_UX = "product_ux"
    PRODUCT_GROWTH = "product_growth"
    PRODUCT_POSITIONING = "product_positioning"
    # technical
    TECH_ARCHITECTURE = "tech_architecture"
    TECH_ENG_PRACTICE = "tech_eng_practice"
    TECH_TREND = "tech_trend"
    TECH_CHALLENGE = "tech_challenge"
    # market
    MARKET_TREND = "market_trend"
    MARKET_COMPETITION = "market_competition"
    MARKET_BUSINESS_MODEL = "market_business_model"
    MARKET_OPPORTUNITY = "market_opportunity"
    OTHER = "other"


class InsightItem(BaseModel):
    """单条结构化洞察"""
    text_zh: str = Field(..., min_length=1, description="洞察正文（prompt 约定 30-80 字，模型层只要求非空）")
    cited_segment_ids: List[int] = Field(default_factory=list, description="支撑段落 id")
    rationale_zh: str = Field(default="", description="提炼依据 10-30 字")
    category: InsightCategory = Field(default=InsightCategory.OTHER, description="细分维度")
    confidence: Optional[float] = Field(None, ge=0, le=1, description="verify 阶段打分（可选）")


class InsightGroup(BaseModel):
    """一个域下的洞察集合"""
    items: List[InsightItem] = Field(default_factory=list, description="该域的洞察列表")


class ProductInsights(BaseModel):
    """产品/技术/市场洞察（v3 结构化 + 旧 list[str] 兼容）

    旧 shape: {"product_insights_zh": ["..."], "technical_insights_zh": [...], ...}
    新 shape: {"product": {"items": [{text_zh, cited_segment_ids, rationale_zh, category}]}, ...}
    model_validator(mode=before) 在解析前把旧 list[str] 包装成 InsightItem(category=other)，
    保证旧 episode 的 product_insights.json 无需迁移即可加载。
    """
    schema_version: int = Field(default=3)
    product: InsightGroup = Field(default_factory=InsightGroup, description="产品洞察")
    technical: InsightGroup = Field(default_factory=InsightGroup, description="技术洞察")
    market: InsightGroup = Field(default_factory=InsightGroup, description="市场洞察")
    mentioned_companies: List[str] = Field(default_factory=list, description="提到的公司/产品")
    mentioned_technologies: List[str] = Field(default_factory=list, description="提到的技术栈/工具")

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        # 已是新 shape（含 product/technical/market 任一）则不处理
        if any(k in data for k in ("product", "technical", "market")):
            return data
        # 旧 shape：把 *_insights_zh list[str] 升级为 InsightGroup
        upgraded: Dict[str, Any] = dict(data)
        for legacy_key in ("product_insights_zh", "technical_insights_zh", "market_insights_zh"):
            legacy_val = upgraded.pop(legacy_key, None)
            if isinstance(legacy_val, list):
                domain_key = legacy_key.replace("_insights_zh", "")  # product/technical/market
                upgraded[domain_key] = {
                    "items": [
                        {"text_zh": s, "category": "other"}
                        for s in legacy_val
                        if isinstance(s, str) and s.strip()
                    ]
                }
        upgraded.setdefault("schema_version", 3)
        return upgraded


class EpisodeBundle(BaseModel):
    """节目完整数据包"""
    episode: Episode = Field(..., description="基础元信息")
    transcript: Optional[Transcript] = Field(None, description="转录文本（优先翻译版）")
    outline: Optional[Outline] = Field(None, description="章节大纲")
    chapter_summaries: List[ChapterSummary] = Field(default_factory=list, description="章节摘要列表")
    highlight: Optional[HighlightCard] = Field(None, description="亮点卡")
    ingest_job: Optional[IngestJob] = Field(None, description="处理进度（进行中时）")
    # 专项分析结果
    launch_analysis: Optional[LaunchAnalysis] = Field(None, description="发布会分析")
    podcast_analysis: Optional[PodcastAnalysis] = Field(None, description="播客分析")
    product_insights: Optional[ProductInsights] = Field(None, description="产品和技术洞察")
    # 处理过程中的非致命失败状态（供前端提示用户）
    punctuation_status: Optional[dict] = Field(None, description="标点恢复状态（失败时含 error/error_type/failed_at）")


# ==================== 请求/响应模型 ====================

class StageInfo(BaseModel):
    """阶段信息"""
    id: str = Field(..., description="阶段 ID（download/transcribe/.../highlight）")
    name: str = Field(..., description="阶段名称（中文）")
    status: EpisodeStatus = Field(..., description="阶段状态")
    progress: float = Field(default=0.0, ge=0, le=1, description="进度 0-1")
    current: Optional[int] = Field(None, description="已处理量(如已润色段数)")
    total: Optional[int] = Field(None, description="总量(如总段数)")


class EpisodeCard(BaseModel):
    """Library 卡片展示"""
    id: str
    title: str
    status: EpisodeStatus
    language: Optional[str] = None
    is_fixture: bool = False
    created_at: datetime
    last_activity_ts: Optional[datetime] = None
    # 处理进度信息（进行中时）
    current_stage: Optional[str] = Field(None, description="当前阶段名称")
    stages: List[StageInfo] = Field(default_factory=list, description="处理阶段列表")
    overall_progress: float = Field(default=0.0, ge=0, le=1, description="总体进度 0-1")
    # 从 highlight.json 读取的摘要数据
    tldr_zh: Optional[str] = None
    worth_listening_verdict: Optional[VerdictType] = None
    verdict_confidence: Optional[ConfidenceType] = None
    target_audience_zh: Optional[str] = None
    highlights_count: int = 0
    duration_min: Optional[int] = None
    # 元信息标签（语种/时长/来源/分类）——用于卡片和播放器头部展示
    source_type: Optional[str] = Field(None, description="来源平台标签：YouTube/B站/小宇宙/抖音/本地")
    source_url: Optional[str] = Field(None, description="原始 URL（前端用于推断分类等）")
    title_zh: Optional[str] = Field(None, description="中文标题（英文标题翻译后；纯中文标题则与 title 一致）")


class PasteRequest(BaseModel):
    """粘贴请求"""
    raw_input: str = Field(..., description="URL 或本地文件路径")


class PasteResponse(BaseModel):
    """粘贴响应"""
    episode: EpisodeCard


class PlayRequest(BaseModel):
    """播放请求"""
    position_ms: Optional[int] = Field(None, description="播放位置")


class PlayResponse(BaseModel):
    """播放响应"""
    ok: bool = True
    ts: datetime = Field(default_factory=datetime.now)


# ==================== 数据库模型 ====================

class SourceRecord(BaseModel):
    """原始输入记录"""
    id: int
    episode_id: str
    source_type: str
    raw_input: str
    resolved_url: Optional[str] = None
    requires_auth: bool = False
    created_at: datetime = Field(default_factory=datetime.now)


class UsageLog(BaseModel):
    """用户行为埋点"""
    id: int
    ts: datetime = Field(default_factory=datetime.now)
    event_type: str = Field(..., description="paste/play_start/delete/seek")
    episode_id: str
    payload_json: Optional[str] = None


class CostLog(BaseModel):
    """LLM 调用成本记录"""
    id: int
    ts: datetime = Field(default_factory=datetime.now)
    task: str = Field(..., description="chapterize/summarize/translate/highlight/verify")
    model: str = Field(..., description="configured LLM model id")
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    prompt_version: int = 2
    episode_id: Optional[str] = None
    success: bool = True
    error: Optional[str] = None


class EpisodeViewState(BaseModel):
    """前端 UI 状态持久化"""
    id: int
    episode_id: str
    highlight_collapsed: bool = True
    last_played_position_ms: int = 0


# ==================== Export Models ====================

class ExportRequest(BaseModel):
    """导出请求"""
    format: str = Field(..., description="导出格式: html / png / pdf")
    include_transcript: bool = Field(default=False, description="是否包含完整字幕")
    theme: str = Field(default="light", description="主题: light 或 dark")
    width: int = Field(default=1080, description="PNG宽度（像素）")


class ExportResponse(BaseModel):
    """导出响应"""
    download_url: str = Field(..., description="下载链接")
    format: str = Field(..., description="导出格式")
    expires_at: str = Field(..., description="过期时间（ISO 8601）")
    file_size: Optional[int] = Field(None, description="文件大小（字节）")
    updated_at: datetime = Field(default_factory=datetime.now)


class TranscriptResponse(BaseModel):
    """字幕响应"""
    segments: List[Segment] = Field(default_factory=list, description="所有字幕段")
