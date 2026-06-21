"""
CDP (Chrome DevTools Protocol) 下载器备用方案
当 yt-dlp 不可用时使用 CDP 直接下载
可用于小宇宙、Bilibili 等需要绕过反爬的平台

依赖安装:
    pip install playwright
    或
    pip install selenium

使用方式:
    from .cdp_downloader import download_with_cdp
    audio_path = await download_with_cdp(url, out_dir)
"""

import asyncio
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# CDP 配置
CDP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


async def download_with_playwright(url: str, out_dir: Path) -> Optional[Path]:
    """
    使用 Playwright 下载音频（备用方案）

    Args:
        url: 音频 URL
        out_dir: 输出目录

    Returns:
        下载的音频文件路径或 None
    """
    try:
        from playwright.async_api import async_playwright

        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / "audio.mp3"

        async with async_playwright() as p:
            # 启动浏览器
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            # 设置额外的请求头
            await page.set_extra_http_headers(CDP_HEADERS)

            # 导航到 URL
            logger.info(f"CDP: Navigating to {url}")
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # 等待音频元素加载
            try:
                audio_selector = "audio"
                await page.wait_for_selector(audio_selector, timeout=15000)

                # 获取音频 URL
                audio_url = await page.evaluate(f"""
                    () => {{
                        const audio = document.querySelector('{audio_selector}');
                        return audio ? audio.src : null;
                    }}
                """)

                if audio_url:
                    logger.info(f"CDP: Found audio at {audio_url}")

                    # 下载音频文件
                    import aiohttp
                    async with aiohttp.ClientSession() as session:
                        async with session.get(audio_url, headers=CDP_HEADERS) as resp:
                            if resp.status == 200:
                                content = await resp.read()
                                output_path.write_bytes(content)
                                logger.info(f"CDP: Downloaded to {output_path}")
                                return output_path
                else:
                    logger.warning("CDP: No audio URL found")
            except Exception as e:
                logger.warning(f"CDP: Audio selector not found: {e}")

            # 尝试获取页面标题
            try:
                title = await page.title()
                logger.info(f"CDP: Page title: {title}")
            except Exception as title_exc:
                # 标题获取失败不应阻断下载流程，但仍记录原因便于排查
                logger.debug(f"CDP: title fetch failed: {title_exc}")

            await browser.close()

    except ImportError:
        logger.warning("CDP: playwright not installed, skipping CDP download")
    except Exception as e:
        logger.warning(f"CDP: Download failed: {e}")

    return None


async def download_with_selenium(url: str, out_dir: Path) -> Optional[Path]:
    """
    使用 Selenium 下载音频（备用方案）

    Args:
        url: 音频 URL
        out_dir: 输出目录

    Returns:
        下载的音频文件路径或 None
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.chrome.service import Service

        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / "audio.mp3"

        # 配置 Chrome 选项
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument(f"--user-agent={CDP_HEADERS['User-Agent']}")

        # 启动浏览器
        driver = webdriver.Chrome(options=chrome_options)

        try:
            driver.get(url)

            # 等待页面加载
            await asyncio.sleep(3)

            # 查找音频元素
            audio_element = driver.find_element("tag name", "audio")
            audio_url = audio_element.get_attribute("src")

            if audio_url:
                logger.info(f"CDP(Selenium): Found audio at {audio_url}")

                # 下载音频文件
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(audio_url, headers=CDP_HEADERS) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            output_path.write_bytes(content)
                            logger.info(f"CDP(Selenium): Downloaded to {output_path}")
                            return output_path

        finally:
            driver.quit()

    except ImportError:
        logger.warning("CDP: selenium not installed, skipping CDP download")
    except Exception as e:
        logger.warning(f"CDP(Selenium): Download failed: {e}")

    return None


async def download_with_cdp(url: str, out_dir: Path) -> Optional[Path]:
    """
    使用 CDP 下载音频（自动选择可用方案）

    Args:
        url: 音频/页面 URL
        out_dir: 输出目录

    Returns:
        下载的音频文件路径或 None
    """
    # 优先使用 Playwright
    result = await download_with_playwright(url, out_dir)
    if result:
        return result

    # 回退到 Selenium
    result = await download_with_selenium(url, out_dir)
    if result:
        return result

    logger.warning("CDP: All download methods failed")
    return None


# 小宇宙专用 CDP 解析器
async def fetch_xiaoyuzhou_with_cdp(url: str) -> dict:
    """
    使用 CDP 获取小宇宙音频 URL

    Args:
        url: 小宇宙节目页面 URL

    Returns:
        包含 title 和 audio_url 的字典
    """
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            await page.set_extra_http_headers(CDP_HEADERS)
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # 等待页面加载
            await asyncio.sleep(3)

            # 提取标题
            title = await page.title()
            logger.info(f"CDP: Page title: {title}")

            # 查找音频元素
            audio_url = await page.evaluate("""
                () => {
                    const audio = document.querySelector('audio');
                    return audio ? audio.src : null;
                }
            """)

            await browser.close()

            return {
                "title": title,
                "audio_url": audio_url,
            }

    except Exception as e:
        logger.warning(f"CDP: Failed to fetch xiaoyuzhou: {e}")
        return None


# Bilibili 专用 CDP 解析器
async def fetch_bilibili_with_cdp(url: str) -> dict:
    """
    使用 CDP 获取 Bilibili 音频 URL

    Args:
        url: Bilibili 视频 URL

    Returns:
        包含 title 和 audio_url 的字典
    """
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            # Bilibili 需要 Referer
            headers = CDP_HEADERS.copy()
            headers["Referer"] = "https://www.bilibili.com"

            await page.set_extra_http_headers(headers)
            await page.goto(url, wait_until="networkidle", timeout=30000)

            await asyncio.sleep(3)

            # 提取标题
            title = await page.title()
            logger.info(f"CDP: Page title: {title}")

            # 查找音频元素
            audio_url = await page.evaluate("""
                () => {
                    const audio = document.querySelector('audio');
                    return audio ? audio.src : null;
                }
            """)

            await browser.close()

            return {
                "title": title,
                "audio_url": audio_url,
            }

    except Exception as e:
        logger.warning(f"CDP: Failed to fetch bilibili: {e}")
        return None
