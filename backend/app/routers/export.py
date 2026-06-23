"""Export router: 生成并分发可分享的 HTML/PNG 摘要卡片。

Routes:
- POST /api/episodes/{episode_id}/export   生成摘要导出（HTML 或 PNG）
- GET  /api/exports/{filename}             下载已生成的导出文件

POST 端点带 rate_limit(3, 60) 依赖，防止 CPU 密集型 PNG 渲染被滥用。
"""
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import deps
from ..config import DATA_DIR
from ..models import ExportRequest, ExportResponse, HighlightCard
from ..rate_limit import rate_limit
from ..utils.io import load_json_with_callback, safe_read_json


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/api/episodes/{episode_id}/export",
    response_model=ExportResponse,
    dependencies=[Depends(rate_limit(3, 60))],
)
async def export_episode_summary(
    episode_id: str,
    request: ExportRequest,
) -> ExportResponse:
    """
    导出节目摘要

    生成精美的HTML或PNG格式的摘要卡片，包含：
    - 中英文标题
    - 节目摘要（TL;DR）
    - 章节目录
    - 章节摘要
    - 趋势洞察

    支持两种格式：
    - HTML: 可分享的网页链接
    - PNG: 适合社交媒体分享的长图
    """
    # 速率限制由路由依赖 rate_limit(3, 60) 强制执行
    from ..export import render_html_template, render_png_from_html, render_pdf_from_html

    # 1. 加载节目数据（从文件系统）
    data_dir = DATA_DIR
    media_dir = data_dir / "media" / episode_id

    if not media_dir.exists():
        raise HTTPException(status_code=404, detail="Episode media directory not found")

    # 尝试从transcript.json获取metadata
    transcript_file = media_dir / "transcript.json"
    episode_meta = {}

    if transcript_file.exists():
        transcript_data = safe_read_json(transcript_file)
        if transcript_data:
            episode_meta = transcript_data.get('meta', {})

    # 构造episode对象（至少要有id）
    episode = {
        'id': episode_id,
        'title': episode_meta.get('title', episode_id),
        'title_zh': episode_meta.get('title_zh', episode_meta.get('title', episode_id)),
        'tldr_zh': '',  # 后续从highlight加载
        'worth_listening_verdict': '',
        'target_audience_zh': '',
        'publish_date': ''
    }

    # 2. 加载章节数据 (outline.json)
    chapters = None
    outline_file = media_dir / "outline.json"
    if outline_file.exists():
        # 直接加载JSON，不需要Outline模型验证（outline.json缺少episode_id字段）
        outline_data = safe_read_json(outline_file)
        chapters = outline_data.get('entries', []) if outline_data else []
        logger.info(f"Loaded {len(chapters) if chapters else 0} chapters from outline.json")

    # 3. 加载章节摘要 (summaries.json)
    summaries = None
    summaries_file = media_dir / "summaries.json"
    if summaries_file.exists():
        summaries = load_json_with_callback(summaries_file, lambda d: d)  # summaries是直接数组
        logger.info(f"Loaded {len(summaries) if summaries else 0} summaries from summaries.json")

    # 4. 加载洞察 (highlight.json)
    highlights = []
    highlights_file = media_dir / "highlight.json"
    if highlights_file.exists():
        highlight_data = load_json_with_callback(highlights_file, lambda d: HighlightCard(**d))
        if highlight_data:
            # 从highlight中获取tldr等episode级别信息
            episode['tldr_zh'] = highlight_data.tldr_zh or ''
            episode['worth_listening_verdict'] = highlight_data.worth_listening_verdict or ''
            episode['target_audience_zh'] = highlight_data.target_audience_zh or ''
            highlights = highlight_data.highlights if highlight_data.highlights else []
            logger.info(f"Loaded {len(highlights)} highlights from highlight.json")

    # 5. 加载产品/技术/市场洞察 (product_insights.json)
    product_insights = None
    insights_file = media_dir / "product_insights.json"
    if insights_file.exists():
        product_insights = safe_read_json(insights_file)
        if product_insights:
            logger.info("Loaded product_insights from product_insights.json")

    # 6. 准备导出数据
    export_data = {
        'episode': episode,
        'chapters': chapters or [],
        'summaries': summaries or [],
        'highlights': highlights,
        'product_insights': product_insights or {},
        'transcript': []  # 暂时不包含完整字幕
    }

    logger.info(f"Export data prepared: {len(export_data['chapters'])} chapters, {len(export_data['summaries'])} summaries, {len(export_data['highlights'])} highlights")

    # 6. 生成文件名和路径
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_id = f"{episode_id}_{timestamp}"

    # 导出目录
    export_dir = data_dir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    # 7. 渲染HTML模板
    logger.info(f"Exporting episode {episode_id} as {request.format}")

    html_content = render_html_template(
        export_data,
        theme=request.theme,
        include_transcript=request.include_transcript
    )

    # 8. 根据格式生成文件
    expires_at = datetime.now() + timedelta(hours=24)  # 24小时后过期
    download_url = ""
    file_size = 0

    if request.format == "html":
        # 保存HTML文件
        html_file = export_dir / f"{export_id}.html"
        html_file.write_text(html_content, encoding='utf-8')

        # 生成下载URL
        download_url = f"/api/exports/{export_id}.html"
        file_size = html_file.stat().st_size

    elif request.format == "png":
        # 渲染PNG
        png_file = export_dir / f"{export_id}.png"
        await render_png_from_html(
            html_content,
            png_file,
            width=request.width,
            scale=2.0
        )

        # 生成下载URL
        download_url = f"/api/exports/{export_id}.png"
        file_size = png_file.stat().st_size

    elif request.format == "pdf":
        # 渲染PDF（矢量、文字可选、适合打印归档）
        pdf_file = export_dir / f"{export_id}.pdf"
        await render_pdf_from_html(html_content, pdf_file)

        download_url = f"/api/exports/{export_id}.pdf"
        file_size = pdf_file.stat().st_size

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {request.format}")

    logger.info(f"Export completed: {download_url} ({file_size} bytes)")

    # 9. 返回响应
    return ExportResponse(
        download_url=download_url,
        format=request.format,
        expires_at=expires_at.isoformat(),
        file_size=file_size
    )


@router.get("/api/exports/{filename}")
async def download_export(filename: str):
    """
    下载导出文件

    静态文件服务端点，用于下载生成的HTML或PNG文件
    """
    data_dir = DATA_DIR
    export_file = data_dir / "exports" / filename

    if not export_file.exists():
        raise HTTPException(status_code=404, detail="Export file not found")

    # 根据文件类型设置Content-Type
    if filename.endswith('.html'):
        media_type = 'text/html'
    elif filename.endswith('.png'):
        media_type = 'image/png'
    elif filename.endswith('.pdf'):
        media_type = 'application/pdf'
    else:
        media_type = 'application/octet-stream'

    return FileResponse(
        export_file,
        media_type=media_type,
        filename=filename
    )
