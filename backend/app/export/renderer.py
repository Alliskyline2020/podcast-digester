"""
PNG渲染器 - 使用Playwright将HTML转换为PNG长图
"""
from playwright.async_api import async_playwright, Browser
from pathlib import Path
from typing import Optional
import logging
import asyncio

logger = logging.getLogger(__name__)

# 全局浏览器实例（复用以提高性能）
_browser: Optional[Browser] = None
_browser_lock = asyncio.Lock()


async def _get_browser() -> Browser:
    """获取或创建浏览器实例"""
    global _browser

    async with _browser_lock:
        if _browser is None:
            try:
                playwright = await async_playwright().start()
                _browser = await playwright.chromium.launch(
                    args=['--no-sandbox', '--disable-setuid-sandbox']
                )
                logger.info("Browser instance created")
            except Exception as e:
                logger.error(f"Failed to launch browser: {e}")
                raise RuntimeError(f"Browser launch failed: {e}")

        return _browser


async def render_png_from_html(
    html_content: str,
    output_path: Path,
    width: int = 1080,
    scale: float = 2.0,
    timeout: int = 30000
) -> Path:
    """
    将HTML渲染为PNG长图

    Args:
        html_content: HTML字符串
        output_path: 输出PNG文件路径
        width: 视口宽度（像素），影响布局
        scale: 设备缩放因子，用于高清显示（2x = retina）
        timeout: 超时时间（毫秒）

    Returns:
        生成的PNG文件路径
    """
    try:
        # 确保输出目录存在
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 获取浏览器实例
        browser = await _get_browser()

        # 创建新页面
        page = await browser.new_page(
            viewport={'width': width, 'height': 1080, 'device_scale_factor': scale}
        )

        try:
            # 设置HTML内容
            await page.set_content(html_content, wait_until='networkidle', timeout=timeout)

            # 等待所有资源加载完成
            await page.wait_for_load_state('networkidle', timeout=timeout)

            # 截取完整页面
            await page.screenshot(
                path=str(output_path),
                full_page=True,
                type='png'
            )

            logger.info(f"PNG rendered successfully: {output_path}")

            return output_path

        finally:
            await page.close()

    except Exception as e:
        logger.error(f"Failed to render PNG: {e}")
        # 清理可能的部分文件
        if output_path.exists():
            output_path.unlink()
        raise RuntimeError(f"PNG rendering failed: {e}")


async def cleanup_browser():
    """清理浏览器实例（用于关闭时）"""
    global _browser

    async with _browser_lock:
        if _browser is not None:
            try:
                await _browser.close()
                _browser = None
                logger.info("Browser instance closed")
            except Exception as e:
                logger.error(f"Failed to close browser: {e}")


def estimate_png_size(episode_data: dict) -> int:
    """
    估算PNG文件大小（字节）

    基于内容长度和复杂度进行估算
    """
    # 基础大小（头部、尾部）
    base_size = 100 * 1024  # 100KB

    # TL;DR大小
    tldr_len = len(episode_data.get('tldr_zh', ''))
    tldr_size = tldr_len * 2  # 每字符约2字节

    # 章节大小
    chapters = episode_data.get('chapters', [])
    chapters_size = len(chapters) * 5 * 1024  # 每章节约5KB

    # 摘要大小
    summaries = episode_data.get('summaries', [])
    summaries_size = sum(len(s.get('content_zh', '')) for s in summaries) * 2

    # 洞察大小
    highlights = episode_data.get('highlights', [])
    highlights_size = len(highlights) * 3 * 1024  # 每洞察约3KB

    total = base_size + tldr_size + chapters_size + summaries_size + highlights_size

    return int(total * 1.5)  # 1.5倍余量（PNG压缩）
