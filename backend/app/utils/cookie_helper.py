"""
Cookie 辅助模块
支持从浏览器提取 cookies 和检测可用的 cookies.txt 文件
"""
import os
import logging
from pathlib import Path
from typing import Optional, List
import shutil

logger = logging.getLogger(__name__)


# 支持的浏览器 Cookie 数据库路径（按优先级排序）
BROWSER_COOKIE_PATHS = {
    "chrome": [
        # macOS
        "~/Library/Application Support/Google/Chrome/Default/Cookies",
        "~/Library/Application Support/Google/Chrome/Profile */Cookies",
        # Linux
        "~/.config/google-chrome/Default/Cookies",
        "~/.config/google-chrome/Profile */Cookies",
        # Windows
        "~/AppData/Local/Google/Chrome/User Data/Default/Cookies",
        "~/AppData/Local/Google/Chrome/User Data/Profile */Cookies",
    ],
    "firefox": [
        # macOS
        "~/Library/Application Support/Firefox/Profiles/*.default-release*/cookies.sqlite",
        "~/Library/Application Support/Firefox/Profiles/*.default*/cookies.sqlite",
        # Linux
        "~/.mozilla/firefox/*.default-release*/cookies.sqlite",
        "~/.mozilla/firefox/*.default*/cookies.sqlite",
        # Windows
        "~/AppData/Roaming/Mozilla/Firefox/Profiles/*.default-release*/cookies.sqlite",
        "~/AppData/Roaming/Mozilla/Firefox/Profiles/*.default*/cookies.sqlite",
    ],
    "edge": [
        # macOS
        "~/Library/Application Support/Microsoft Edge/Default/Cookies",
        "~/Library/Application Support/Microsoft Edge/Profile */Cookies",
        # Linux
        "~/.config/microsoft-edge/Default/Cookies",
        "~/.config/microsoft-edge/Profile */Cookies",
        # Windows
        "~/AppData/Local/Microsoft/Edge/User Data/Default/Cookies",
        "~/AppData/Local/Microsoft/Edge/User Data/Profile */Cookies",
    ],
    "safari": [
        # macOS only
        "~/Library/Cookies/Cookies.binarycookies",
    ],
}


# cookies.txt 文件的默认搜索路径
COOKIES_TXT_SEARCH_PATHS = [
    "./cookies.txt",
    "./youtube_cookies.txt",
    "~/.config/yt-dlp/cookies.txt",
    "~/.cookies.txt",
]


def find_browser_cookies(browser: str = "chrome") -> Optional[Path]:
    """
    查找指定浏览器的 Cookie 数据库

    Args:
        browser: 浏览器名称 (chrome/firefox/edge/safari)

    Returns:
        找到的 Cookie 数据库路径，未找到返回 None
    """
    if browser not in BROWSER_COOKIE_PATHS:
        logger.warning(f"Unsupported browser: {browser}")
        return None

    paths = BROWSER_COOKIE_PATHS[browser]
    home = Path.home()

    for pattern in paths:
        # 扩展 ~ 和处理通配符
        expanded = str(home / pattern.lstrip("~/"))
        base_path = Path(expanded).parent

        # 处理通配符
        if "*" in expanded:
            matching = list(base_path.glob(Path(expanded).name))
            if matching:
                logger.info(f"Found {browser} cookies: {matching[0]}")
                return matching[0]
        else:
            path = Path(expanded)
            if path.exists():
                logger.info(f"Found {browser} cookies: {path}")
                return path

    logger.debug(f"No {browser} cookies found")
    return None


def find_cookies_txt() -> Optional[Path]:
    """
    查找 cookies.txt 文件

    Returns:
        找到的 cookies.txt 绝对路径，未找到返回 None
    """
    home = Path.home()
    cwd = Path.cwd()

    # 先检查当前工作目录
    for pattern in COOKIES_TXT_SEARCH_PATHS:
        # 先尝试相对于当前目录的路径
        relative_path = cwd / pattern
        if relative_path.exists() and relative_path.is_file():
            path = relative_path.resolve()  # Get absolute path
            logger.info(f"Found cookies.txt: {path}")
            return path

        # 再尝试相对于 home 目录的路径
        expanded = home / pattern.lstrip("~/")
        path = expanded.expanduser().resolve()  # Get absolute path

        if path.exists() and path.is_file():
            logger.info(f"Found cookies.txt: {path}")
            return path

    logger.debug("No cookies.txt found")
    return None


def detect_js_runtime() -> Optional[str]:
    """
    检测可用的 JavaScript 运行时（用于 YouTube）

    Returns:
        "deno", "node", 或 None
    """
    # 优先检测 Deno
    deno_path = shutil.which("deno")
    if deno_path:
        logger.info(f"Found Deno: {deno_path}")
        return "deno"

    # 检测 Node.js
    node_path = shutil.which("node")
    if node_path:
        logger.info(f"Found Node.js: {node_path}")
        return "node"

    logger.debug("No JavaScript runtime found (Deno or Node.js required for YouTube with cookies)")
    return None


def get_js_runtime_path(runtime: str = "auto") -> Optional[str]:
    """
    获取 JavaScript 运行时的可执行文件路径

    Args:
        runtime: 运行时类型 (auto/deno/node)

    Returns:
        可执行文件路径或 None
    """
    if runtime == "auto":
        runtime = detect_js_runtime()
        if not runtime:
            return None

    if runtime == "deno":
        return shutil.which("deno")
    elif runtime == "node":
        return shutil.which("node")

    return None


def get_available_browsers() -> List[str]:
    """
    获取系统中可用的浏览器列表

    Returns:
        可用浏览器名称列表
    """
    available = []
    for browser in BROWSER_COOKIE_PATHS.keys():
        if find_browser_cookies(browser):
            available.append(browser)
    return available


def check_cookies_txt_available() -> bool:
    """
    检查是否有可用的 cookies.txt 文件

    Returns:
        是否存在 cookies.txt
    """
    return find_cookies_txt() is not None


def get_cookie_strategy() -> List[str]:
    """
    获取推荐的 Cookie 策略顺序

    Returns:
        策略列表，可能包含: "no_cookies", "browser_cookies", "cookies_file"
    """
    strategies = []

    # 总是从 no_cookies 开始
    strategies.append("no_cookies")

    # 检查浏览器 cookies
    available_browsers = get_available_browsers()
    if available_browsers:
        strategies.append("browser_cookies")

    # 检查 cookies.txt
    if check_cookies_txt_available():
        strategies.append("cookies_file")

    return strategies


def get_best_browser() -> Optional[str]:
    """
    获取最佳浏览器（按优先级: Chrome > Edge > Firefox > Safari）

    Returns:
        浏览器名称或 None
    """
    priority = ["chrome", "edge", "firefox", "safari"]

    for browser in priority:
        if find_browser_cookies(browser):
            return browser

    return None
