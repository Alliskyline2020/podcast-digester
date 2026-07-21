"""回归测试: yt-dlp 下载命令必须带重试/超时参数。

弱网或代理环境下 yt-dlp 下载可能在文件末尾截断, 丢掉 progressive MP4 的 moov atom,
得到一个 Duration=N/A / 无音轨的坏 m4a, 进而让 Apple SpeechAnalyzer 报 avfaudio
解码错误。下载命令带 --retries / --fragment-retries / --socket-timeout 可让 yt-dlp
在连接抖动时自愈, 避免坏文件。
"""
import asyncio
from pathlib import Path

import pytest

from app.sources import ytdlp_runner


@pytest.mark.asyncio
async def test_download_cmd_includes_retry_and_timeout_flags(tmp_path, monkeypatch):
    """下载命令应包含重试与 socket 超时, 防止代理截断。"""
    captured = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return (b"", b"")

    async def _fake_exec(*cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    # 预置 audio.m4a, 让 run_ytdlp 的 find-existing 返回成功路径
    (tmp_path / "audio.m4a").write_bytes(b"\x00\x00\x00\x00ftyp")

    await ytdlp_runner.run_ytdlp(
        "https://www.youtube.com/watch?v=test123",
        tmp_path,
        on_progress=None,
        platform="youtube",
    )

    cmd = captured.get("cmd", [])
    assert "--retries" in cmd, f"download cmd missing --retries: {cmd}"
    assert "--fragment-retries" in cmd, f"missing --fragment-retries: {cmd}"
    assert "--socket-timeout" in cmd, f"missing --socket-timeout: {cmd}"
