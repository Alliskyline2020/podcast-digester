"""
统一错误类型定义

定义错误层次结构：
- PodcastError: 基础错误
  - TemporaryError: 可重试的临时性错误
  - PermanentError: 不可重试的永久性错误
  - ValidationError: 输入验证错误
  - ConfigurationError: 配置错误
"""
from typing import Optional


class PodcastError(Exception):
    """播客处理基础错误类"""

    def __init__(
        self,
        message: str,
        episode_id: Optional[str] = None,
        details: Optional[dict] = None
    ):
        self.message = message
        self.episode_id = episode_id
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict:
        """转换为字典（用于API响应）"""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "episode_id": self.episode_id,
            "details": self.details,
            "retryable": getattr(self, "retryable", False)
        }


class TemporaryError(PodcastError):
    """可重试的临时性错误（网络超时、服务暂时不可用等）"""

    retryable = True
    http_status = 503  # Service Unavailable

    def __init__(
        self,
        message: str,
        episode_id: Optional[str] = None,
        suggested_retry_seconds: int = 60,
        details: Optional[dict] = None
    ):
        super().__init__(message, episode_id, details)
        self.suggested_retry_seconds = suggested_retry_seconds


class PermanentError(PodcastError):
    """不可重试的永久性错误（格式不支持、权限拒绝等）"""

    retryable = False
    http_status = 400  # Bad Request


class ValidationError(PermanentError):
    """输入验证错误"""

    http_status = 400

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        value: Optional[str] = None
    ):
        details = {}
        if field:
            details["field"] = field
        if value:
            details["provided_value"] = str(value)[:200]  # 限制长度
        super().__init__(message, details=details)


class DownloadError(PermanentError):
    """媒体下载失败（非临时性）"""

    http_status = 400

    def __init__(
        self,
        message: str,
        episode_id: Optional[str] = None,
        source_type: Optional[str] = None,
        url: Optional[str] = None
    ):
        details = {}
        if source_type:
            details["source_type"] = source_type
        if url:
            details["url"] = url[:200]  # 限制长度
        super().__init__(message, episode_id, details)


class ASRError(TemporaryError):
    """ASR转录失败（可能是临时性）"""

    http_status = 503

    def __init__(
        self,
        message: str,
        episode_id: Optional[str] = None,
        audio_file: Optional[str] = None,
        duration_ms: Optional[int] = None
    ):
        details = {}
        if audio_file:
            details["audio_file"] = audio_file
        if duration_ms:
            details["duration_seconds"] = duration_ms / 1000
        super().__init__(message, episode_id, suggested_retry_seconds=120, details=details)


class LLMError(TemporaryError):
    """LLM调用失败（API限流、网络问题等）"""

    http_status = 503

    def __init__(
        self,
        message: str,
        episode_id: Optional[str] = None,
        task: Optional[str] = None,
        model: Optional[str] = None
    ):
        details = {}
        if task:
            details["task"] = task
        if model:
            details["model"] = model
        super().__init__(message, episode_id, suggested_retry_seconds=60, details=details)


class CostLimitError(PermanentError):
    """LLM成本超限"""

    http_status = 402  # Payment Required

    def __init__(
        self,
        message: str,
        episode_id: Optional[str] = None,
        estimated_cost_usd: Optional[float] = None,
        budget_usd: Optional[float] = None
    ):
        details = {}
        if estimated_cost_usd:
            details["estimated_cost_usd"] = estimated_cost_usd
        if budget_usd:
            details["budget_usd"] = budget_usd
        super().__init__(message, episode_id, details)


class ConfigurationError(PermanentError):
    """配置错误（API密钥缺失等）"""

    http_status = 500

    def __init__(
        self,
        message: str,
        config_key: Optional[str] = None
    ):
        details = {}
        if config_key:
            details["config_key"] = config_key
        super().__init__(message, details=details)


class DatabaseError(PodcastError):
    """数据库错误"""

    retryable = True  # 数据库错误通常可以重试
    http_status = 503

    def __init__(
        self,
        message: str,
        episode_id: Optional[str] = None,
        operation: Optional[str] = None
    ):
        details = {}
        if operation:
            details["operation"] = operation
        super().__init__(message, episode_id, details)


class ConcurrencyError(PermanentError):
    """并发冲突（重复任务等）"""

    http_status = 409  # Conflict

    def __init__(
        self,
        message: str,
        episode_id: Optional[str] = None,
        conflicting_episode_id: Optional[str] = None
    ):
        details = {}
        if conflicting_episode_id:
            details["conflicting_episode_id"] = conflicting_episode_id
        super().__init__(message, episode_id, details)
