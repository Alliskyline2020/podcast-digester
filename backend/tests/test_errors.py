"""
错误处理测试

测试自定义错误类型、错误传播、错误响应格式等
"""
import pytest
from datetime import datetime

from app.errors import (
    PodcastError,
    TemporaryError,
    PermanentError,
    ValidationError,
    DownloadError,
    ASRError,
    LLMError,
    CostLimitError,
    ConcurrencyError,
    ConfigurationError,
    DatabaseError,
)


@pytest.mark.unit
class TestErrorTypes:
    """测试错误类型"""

    def test_base_error(self):
        """测试基础错误"""
        error = PodcastError("Test error", episode_id="test_001")
        assert error.message == "Test error"
        assert error.episode_id == "test_001"
        assert error.to_dict()["error_type"] == "PodcastError"

    def test_temporary_error_is_retryable(self):
        """测试临时性错误可重试"""
        error = TemporaryError("Network timeout", episode_id="test_001")
        assert error.retryable is True
        assert error.http_status == 503
        assert error.suggested_retry_seconds == 60

    def test_permanent_error_not_retryable(self):
        """测试永久性错误不可重试"""
        error = PermanentError("Invalid format", episode_id="test_001")
        assert error.retryable is False
        assert error.http_status == 400

    def test_validation_error(self):
        """测试验证错误"""
        error = ValidationError(
            "Invalid URL format",
            field="url",
            value="not-a-url"
        )
        assert error.retryable is False
        assert error.http_status == 400
        assert error.details["field"] == "url"

    def test_download_error(self):
        """测试下载错误"""
        error = DownloadError(
            "Video not found",
            episode_id="test_001",
            source_type="youtube",
            url="https://youtube.com/watch?v=invalid"
        )
        assert error.retryable is False
        assert error.details["source_type"] == "youtube"

    def test_asr_error(self):
        """测试ASR错误"""
        error = ASRError(
            "ASR failed",
            episode_id="test_001",
            audio_file="/media/test_001/audio.m4a",
            duration_ms=1800000  # 30分钟
        )
        assert error.retryable is True
        assert error.suggested_retry_seconds == 120
        assert error.details["duration_seconds"] == 1800.0

    def test_llm_error(self):
        """测试LLM错误"""
        error = LLMError(
            "API rate limit exceeded",
            episode_id="test_001",
            task="chapterize",
            model="deepseek-chat"
        )
        assert error.retryable is True
        assert error.details["task"] == "chapterize"

    def test_cost_limit_error(self):
        """测试成本限制错误"""
        error = CostLimitError(
            "Estimated cost exceeds budget",
            episode_id="test_001",
            estimated_cost_usd=6.0,
            budget_usd=5.0
        )
        assert error.retryable is False
        assert error.http_status == 402  # Payment Required
        assert error.details["estimated_cost_usd"] == 6.0

    def test_concurrency_error(self):
        """测试并发冲突错误"""
        error = ConcurrencyError(
            "Task already running",
            episode_id="test_001",
            conflicting_episode_id="test_001"
        )
        assert error.retryable is False
        assert error.http_status == 409  # Conflict

    def test_error_to_dict(self):
        """测试错误转换为字典"""
        error = TemporaryError("Test error", episode_id="test_001")
        error_dict = error.to_dict()

        assert error_dict["error_type"] == "TemporaryError"
        assert error_dict["message"] == "Test error"
        assert error_dict["episode_id"] == "test_001"
        assert error_dict["retryable"] is True


@pytest.mark.unit
class TestErrorHandling:
    """测试错误处理逻辑"""

    async def test_error_propagation(self):
        """测试错误传播"""
        from app.error_handling import max_retries, log_errors
        import asyncio

        @log_errors("test_operation", episode_id="test_001")
        @max_retries(max_attempts=3, delay_seconds=0.1)
        async def failing_operation():
            raise TemporaryError("Operation failed")

        with pytest.raises(TemporaryError):
            await failing_operation()

    async def test_retry_mechanism(self):
        """测试重试机制"""
        from app.error_handling import max_retries
        import asyncio

        call_count = 0

        @max_retries(max_attempts=3, delay_seconds=0.1)
        async def flaky_operation():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TemporaryError("Not ready yet")
            return "success"

        result = await flaky_operation()
        assert result == "success"
        assert call_count == 3

    async def test_permanent_error_no_retry(self):
        """测试永久性错误不重试"""
        from app.error_handling import max_retries

        call_count = 0

        @max_retries(max_attempts=3, delay_seconds=0.1)
        async def permanent_failure():
            nonlocal call_count
            call_count += 1
            raise PermanentError("Invalid format")

        with pytest.raises(PermanentError):
            await permanent_failure()

        # 永久性错误应该立即失败，不重试
        assert call_count == 1


@pytest.mark.unit
class TestErrorInAPI:
    """测试API中的错误处理"""

    def test_http_exception_from_podcast_error(self):
        """测试从PodcastError生成HTTP响应"""
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from app.errors import ValidationError
        from app.main import podcast_error_handler

        # 创建模拟环境
        app = FastAPI()
        app.add_exception_handler(ValidationError, podcast_error_handler)

        error = ValidationError("Invalid URL", field="url", value="bad")
        response = podcast_error_handler(None, error)

        assert isinstance(response, JSONResponse)
        # 验证响应内容
        # （这里需要实际启动FastAPI应用才能完全测试）
