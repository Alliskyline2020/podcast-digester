"""
下载链路 fallback 行为测试。

覆盖本次「优化下载链路」的核心改动：
- _classify_download_error：错误文本分类（节点不可达 / 限流 / 永久）
- _probe_node_reachable：CDN 节点连通性探测（mock requests）
- run_ytdlp 多策略 fallback 编排：
    * 策略1 node_unreachable → 切换策略2 → 成功
    * permanent 错误 → 立即 DownloadError，不试后续
    * 全部失败 → DownloadTemporaryError（交 worker 跨轮次重试）
    * rate_limit 退避 > node_unreachable 退避
- DownloadTemporaryError：retryable / to_dict / 与 DownloadError 区分
- PLATFORM_CONFIGS 结构：youtube 双策略 + 预检；bilibili 保留顶层 needs_cookies
"""
import asyncio

import pytest
from unittest.mock import MagicMock, patch

from app.errors import DownloadError, DownloadTemporaryError
from app.sources import ytdlp_runner as Y
from app.sources.ytdlp_runner import (
    PLATFORM_CONFIGS,
    _classify_download_error,
    _probe_node_reachable,
    run_ytdlp,
)


# ==================== 错误分类 ====================

@pytest.mark.unit
class TestClassifyDownloadError:
    """_classify_download_error: yt-dlp 错误文本 → fallback 决策类型。

    策略：保守重试优先。默认 node_unreachable，只对明确的视频/URL 永久错误
    归 permanent。避免把下载中途断流等临时错误误判永久（会导致 fallback 失效）。
    """

    @pytest.mark.parametrize("msg", [
        # 下载中途断流（本次实测遇到的死节点症状）
        "9662391 bytes read, 361183 more expected. Giving up after 1 retries",
        # 网络层
        "ERROR: Connection to rr5---sn-ojnpo5-c3.googlevideo.com timed out",
        "Operation timed out",
        "Connection refused",
        "Connection reset by peer",
        "temporarily unavailable",
        # 5xx 网关
        "HTTPError 502: Bad Gateway",
        "503 Service Unavailable",
    ])
    def test_node_unreachable(self, msg):
        assert _classify_download_error(msg) == "node_unreachable"

    @pytest.mark.parametrize("msg", [
        "HTTP 429 Too Many Requests",
        "sign in to confirm you're not a bot",
        "LOGIN_REQUIRED",
    ])
    def test_rate_limit(self, msg):
        assert _classify_download_error(msg) == "rate_limit"

    @pytest.mark.parametrize("msg", [
        "Video unavailable: Private video",
        "ERROR: Unsupported URL",
        "Video not found",
        "This video is not available in your country",
        "ERROR: Premieres in 2 days",
    ])
    def test_permanent(self, msg):
        assert _classify_download_error(msg) == "permanent"

    def test_empty_message_is_node_unreachable(self):
        """未知/空错误保守归为可重试（worker 有 max_retries 兜底，不会无限重试）。"""
        assert _classify_download_error("") == "node_unreachable"

    def test_rate_limit_takes_precedence(self):
        """同一条错误里既有 429 又有 timed out → 判 rate_limit（先检查限流）。"""
        msg = "429 Too Many Requests (connection timed out)"
        assert _classify_download_error(msg) == "rate_limit"


# ==================== 节点预检 ====================

@pytest.mark.unit
class TestProbeNodeReachable:
    """_probe_node_reachable: 走代理测 CDN host HTTP 连通。"""

    def test_reachable_on_any_http_response(self):
        """任何 HTTP 响应（含 404/403/405）= 节点可达，只关心握手能否完成。"""
        import requests
        with patch.object(requests, "head") as mock_head:
            mock_head.return_value = MagicMock(status_code=404)
            assert _probe_node_reachable("https://rr1.googlevideo.com/v", 5) is True
            mock_head.assert_called_once()

    def test_unreachable_on_connection_error(self):
        import requests
        with patch.object(requests, "head") as mock_head:
            mock_head.side_effect = requests.ConnectionError("timed out")
            assert _probe_node_reachable("https://rr5.googlevideo.com/x", 5) is False

    def test_unreachable_on_timeout(self):
        import requests
        with patch.object(requests, "head") as mock_head:
            mock_head.side_effect = requests.Timeout("read timed out")
            assert _probe_node_reachable("https://rr5.googlevideo.com/x", 5) is False

    def test_conservative_reachable_on_unexpected_exception(self):
        """非连接/超时异常（SSL 等）保守视为可达，不阻塞下载。"""
        import requests
        with patch.object(requests, "head") as mock_head:
            mock_head.side_effect = Exception("Unexpected SSL error")
            assert _probe_node_reachable("https://x", 5) is True


# ==================== DownloadTemporaryError ====================

@pytest.mark.unit
class TestDownloadTemporaryError:
    def test_retryable_and_status(self):
        err = DownloadTemporaryError("node down")
        assert err.retryable is True
        assert err.http_status == 503

    def test_distinct_from_permanent_download_error(self):
        """DownloadTemporaryError 可重试；DownloadError(Permanent) 不可重试。"""
        assert DownloadTemporaryError("x").retryable is True
        assert DownloadError("x").retryable is False

    def test_carries_source_and_url(self):
        err = DownloadTemporaryError(
            "x", source_type="youtube", url="https://youtu.be/abc"
        )
        assert err.to_dict()["retryable"] is True
        assert err.details["source_type"] == "youtube"
        assert err.details["url"] == "https://youtu.be/abc"


# ==================== PLATFORM_CONFIGS 结构 ====================

@pytest.mark.unit
class TestPlatformConfigs:
    def test_youtube_has_two_preflight_strategies(self):
        strategies = PLATFORM_CONFIGS["youtube"]["strategies"]
        assert len(strategies) == 2
        assert all(s.preflight for s in strategies)
        # default 不锁 client（避免锁死单一故障节点）；android_vr 兜底
        assert strategies[0].name == "default"
        assert strategies[0].client is None
        assert strategies[1].client == "android_vr"

    def test_bilibili_keeps_top_level_needs_cookies(self):
        """app/utils/video.py 仍读 PLATFORM_CONFIGS['bilibili']['needs_cookies']。"""
        assert PLATFORM_CONFIGS["bilibili"]["needs_cookies"] is True

    def test_non_youtube_platforms_skip_preflight(self):
        for platform in ["bilibili", "xiaoyuzhou", "douyin"]:
            strategies = PLATFORM_CONFIGS[platform]["strategies"]
            assert all(not s.preflight for s in strategies), (
                f"{platform} 不应启用预检（非 googlevideo CDN）"
            )


# ==================== run_ytdlp fallback 编排 ====================

@pytest.mark.unit
class TestRunYtdlpFallback:
    """run_ytdlp 编排器：遍历策略 + 错误类型决策（不真正跑 yt-dlp）。"""

    @staticmethod
    def _no_sleep(monkeypatch):
        async def _noop(_):
            return None
        monkeypatch.setattr(asyncio, "sleep", _noop)

    def test_falls_back_to_second_strategy_on_node_unreachable(
        self, monkeypatch, tmp_path
    ):
        """策略1 node_unreachable → 切换策略2 → 成功（本次死节点问题的关键修复）。"""
        self._no_sleep(monkeypatch)
        calls = []

        async def fake_try(safe_url, out_dir, strategy, config, on_progress, extra_opts):
            calls.append(strategy.name)
            if strategy.name == "default":
                return False, "node_unreachable", "预检节点不可达: rr5", None
            return True, None, None, tmp_path / "audio.m4a"

        monkeypatch.setattr(Y, "_try_audio_download", fake_try)

        result = asyncio.run(run_ytdlp(
            "https://www.youtube.com/watch?v=deadnode01",
            tmp_path, platform="youtube",
        ))
        assert result.name == "audio.m4a"
        assert calls == ["default", "android_vr"]

    def test_permanent_error_raises_immediately(self, monkeypatch, tmp_path):
        """permanent 错误立即抛 DownloadError，不再尝试后续策略。"""
        self._no_sleep(monkeypatch)
        calls = []

        async def fake_try(safe_url, out_dir, strategy, config, on_progress, extra_opts):
            calls.append(strategy.name)
            return False, "permanent", "Private video", None

        monkeypatch.setattr(Y, "_try_audio_download", fake_try)

        with pytest.raises(DownloadError):
            asyncio.run(run_ytdlp(
                "https://www.youtube.com/watch?v=privatevid",
                tmp_path, platform="youtube",
            ))
        assert calls == ["default"], "permanent 不应继续尝试后续策略"

    def test_all_strategies_fail_raises_temporary(self, monkeypatch, tmp_path):
        """全部策略 node_unreachable → DownloadTemporaryError（交 worker 跨轮次重试）。"""
        self._no_sleep(monkeypatch)

        async def fake_try(safe_url, out_dir, strategy, config, on_progress, extra_opts):
            return False, "node_unreachable", "节点不可达", None

        monkeypatch.setattr(Y, "_try_audio_download", fake_try)

        with pytest.raises(DownloadTemporaryError):
            asyncio.run(run_ytdlp(
                "https://www.youtube.com/watch?v=allnodesbad",
                tmp_path, platform="youtube",
            ))

    def test_rate_limit_uses_longer_backoff_than_node_unreachable(
        self, monkeypatch, tmp_path
    ):
        """rate_limit 退避 2s（>node_unreachable 的 1s）—验证两类错误退避差异。"""
        sleeps = []

        async def _spy_sleep(n):
            sleeps.append(n)

        monkeypatch.setattr(asyncio, "sleep", _spy_sleep)

        async def fake_try(safe_url, out_dir, strategy, config, on_progress, extra_opts):
            if strategy.name == "default":
                return False, "rate_limit", "429", None
            return True, None, None, tmp_path / "audio.m4a"

        monkeypatch.setattr(Y, "_try_audio_download", fake_try)

        asyncio.run(run_ytdlp(
            "https://www.youtube.com/watch?v=ratelimited",
            tmp_path, platform="youtube",
        ))
        assert sleeps == [2], "rate_limit 应退避 2s"

    def test_first_strategy_success_skips_rest(self, monkeypatch, tmp_path):
        """第一个策略成功 → 不尝试第二个（避免无谓 fallback）。"""
        self._no_sleep(monkeypatch)
        calls = []

        async def fake_try(safe_url, out_dir, strategy, config, on_progress, extra_opts):
            calls.append(strategy.name)
            return True, None, None, tmp_path / "audio.m4a"

        monkeypatch.setattr(Y, "_try_audio_download", fake_try)

        asyncio.run(run_ytdlp(
            "https://www.youtube.com/watch?v=worksfine",
            tmp_path, platform="youtube",
        ))
        assert calls == ["default"]

    def test_unknown_platform_uses_default_strategies_no_preflight(
        self, monkeypatch, tmp_path
    ):
        """未知平台走 _DEFAULT_STRATEGIES（不预检、不锁 client）。"""
        self._no_sleep(monkeypatch)
        seen_preflight = []

        async def fake_try(safe_url, out_dir, strategy, config, on_progress, extra_opts):
            seen_preflight.append(strategy.preflight)
            return True, None, None, tmp_path / "audio.m4a"

        monkeypatch.setattr(Y, "_try_audio_download", fake_try)

        asyncio.run(run_ytdlp(
            "https://example.com/some-audio.mp3",
            tmp_path, platform=None,
        ))
        assert seen_preflight == [False]
