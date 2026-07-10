"""get_video_title 单元测试（subprocess 全 mock，不触网）。

验证标题获取路径为鉴权平台注入 cookies —— 与 run_ytdlp 的下载路径保持一致，
否则 bilibili 等反爬平台会在 --get-title 处拿到 412，退回占位标题。
"""
from pathlib import Path

import pytest

from app.utils.video import get_video_title


class _FakeCompleted:
    """模拟 subprocess.run 返回的 CompletedProcess。"""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def capture_run(monkeypatch):
    """捕获 subprocess.run 收到的命令，返回 (capture_dict, setter)。"""
    state = {}

    def fake_run(cmd, **kwargs):
        state["cmd"] = list(cmd)
        state["kwargs"] = kwargs
        return state.get("result", _FakeCompleted(returncode=0, stdout=""))

    monkeypatch.setattr("app.utils.video.subprocess.run", fake_run)
    return state


# --- 鉴权平台：注入浏览器 cookies（优先）---


@pytest.mark.asyncio
async def test_injects_browser_cookies_for_bilibili(capture_run, monkeypatch):
    monkeypatch.setattr("app.utils.video.get_best_browser", lambda: "chrome")
    capture_run["result"] = _FakeCompleted(returncode=0, stdout="真实标题\n")

    title = await get_video_title(
        "https://www.bilibili.com/video/BV1CMjq6nEu1",
        fallback_name="Bilibili: BV1CMjq6nEu1",
        platform="bilibili",
    )

    assert title == "真实标题"
    cmd = capture_run["cmd"]
    assert "--cookies-from-browser" in cmd
    assert "chrome" in cmd


# --- 鉴权平台：无浏览器则回退 cookies.txt ---


@pytest.mark.asyncio
async def test_falls_back_to_cookies_txt_when_no_browser(capture_run, monkeypatch, tmp_path):
    monkeypatch.setattr("app.utils.video.get_best_browser", lambda: None)
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("# placeholder")
    monkeypatch.setattr("app.utils.video.find_cookies_txt", lambda: cookies_file)
    capture_run["result"] = _FakeCompleted(returncode=0, stdout="标题\n")

    title = await get_video_title(
        "https://www.bilibili.com/video/BV1CMjq6nEu1",
        fallback_name="占位",
        platform="bilibili",
    )

    assert title == "标题"
    cmd = capture_run["cmd"]
    assert "--cookies" in cmd
    assert str(cookies_file) in cmd
    # 不应同时使用浏览器 cookies
    assert "--cookies-from-browser" not in cmd


# --- 非鉴权平台：不加任何 cookie 参数 ---


@pytest.mark.asyncio
async def test_no_cookies_for_non_auth_platform(capture_run, monkeypatch):
    monkeypatch.setattr("app.utils.video.get_best_browser", lambda: "chrome")
    capture_run["result"] = _FakeCompleted(returncode=0, stdout="YouTube Title\n")

    title = await get_video_title(
        "https://www.youtube.com/watch?v=abc123",
        fallback_name="YouTube: abc123",
        platform="youtube",
    )

    assert title == "YouTube Title"
    cmd = capture_run["cmd"]
    assert "--cookies-from-browser" not in cmd
    assert "--cookies" not in cmd


@pytest.mark.asyncio
async def test_no_cookies_when_platform_omitted(capture_run, monkeypatch):
    monkeypatch.setattr("app.utils.video.get_best_browser", lambda: "chrome")
    capture_run["result"] = _FakeCompleted(returncode=0, stdout="标题\n")

    await get_video_title("https://example.com/v/1", fallback_name="占位")

    cmd = capture_run["cmd"]
    assert "--cookies-from-browser" not in cmd
    assert "--cookies" not in cmd


# --- 失败回退：yt-dlp 报错（412 等）→ 返回 fallback_name ---


@pytest.mark.asyncio
async def test_returns_fallback_when_ytdlp_errors(capture_run, monkeypatch):
    monkeypatch.setattr("app.utils.video.get_best_browser", lambda: "chrome")
    # 412: stdout 为空
    capture_run["result"] = _FakeCompleted(returncode=1, stdout="", stderr="HTTP Error 412")

    title = await get_video_title(
        "https://www.bilibili.com/video/BV1CMjq6nEu1",
        fallback_name="Bilibili: BV1CMjq6nEu1",
        platform="bilibili",
    )

    assert title == "Bilibili: BV1CMjq6nEu1"
