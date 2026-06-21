"""
错误处理工具

提供错误处理装饰器、重试逻辑、错误日志记录等
"""
import asyncio
import functools
import logging
from typing import Callable, TypeVar, Any, Optional
from datetime import datetime

from .errors import (
    PodcastError,
    TemporaryError,
    PermanentError,
    ConcurrencyError,
    DatabaseError,
)

logger = logging.getLogger(__name__)

T = TypeVar('T')


def max_retries(max_attempts: int = 3, delay_seconds: int = 1) -> Callable:
    """
    重试装饰器（仅对TemporaryError有效）

    用法：
    @max_retries(max_attempts=3, delay_seconds=2)
    async def my_function():
        ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            last_error = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except TemporaryError as e:
                    last_error = e
                    if attempt < max_attempts:
                        wait = delay_seconds * attempt  # 指数退避
                        logger.warning(
                            f"Attempt {attempt}/{max_attempts} failed: {e}, "
                            f"retrying in {wait}s..."
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error(
                            f"All {max_attempts} attempts failed for {func.__name__}"
                        )
                        raise
                except PermanentError:
                    # 永久性错误不重试
                    raise
                except Exception as e:
                    # 未预期的错误不重试
                    logger.error(f"Unexpected error in {func.__name__}: {e}")
                    raise

            raise last_error

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            # 同步函数版本（如果需要）
            return func(*args, **kwargs)

        # 根据函数类型返回对应的包装器
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def log_errors(
    operation: str,
    episode_id: Optional[str] = None
) -> Callable:
    """
    错误日志装饰器

    用法：
    @log_errors("download_audio", episode_id="ep_123")
    async def download():
        ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            try:
                return await func(*args, **kwargs)
            except PodcastError as e:
                # 结构化日志
                logger.error(
                    f"{operation} failed",
                    extra={
                        "operation": operation,
                        "episode_id": e.episode_id or episode_id,
                        "error_type": e.__class__.__name__,
                        "error_message": str(e),
                        "retryable": getattr(e, "retryable", False),
                        "details": e.details,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
                raise
            except Exception as e:
                logger.error(
                    f"Unexpected error in {operation}",
                    extra={
                        "operation": operation,
                        "episode_id": episode_id,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "timestamp": datetime.now().isoformat(),
                    },
                    exc_info=True
                )
                raise

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except PodcastError as e:
                logger.error(
                    f"{operation} failed",
                    extra={
                        "operation": operation,
                        "episode_id": e.episode_id or episode_id,
                        "error_type": e.__class__.__name__,
                        "error_message": str(e),
                        "retryable": getattr(e, "retryable", False),
                        "details": e.details,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
                raise
            except Exception as e:
                logger.error(
                    f"Unexpected error in {operation}",
                    extra={
                        "operation": operation,
                        "episode_id": episode_id,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "timestamp": datetime.now().isoformat(),
                    },
                    exc_info=True
                )
                raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


async def mark_episode_failed(episode_id: str, error: Exception) -> None:
    """
    标记episode为失败状态

    Args:
        episode_id: 节目ID
        error: 导致失败的错误
    """
    from .database import EpisodeRepository
    from .models import EpisodeStatus

    error_msg = f"{error.__class__.__name__}: {str(error)}"

    # 限制错误消息长度（数据库字段限制）
    if len(error_msg) > 1000:
        error_msg = error_msg[:997] + "..."

    await EpisodeRepository.update(
        episode_id,
        status=EpisodeStatus.FAILED.value,
        error_msg=error_msg,
    )

    logger.error(f"Episode {episode_id} marked as failed: {error_msg}")


def handle_ingest_error(func: Callable[..., T]) -> Callable[..., T]:
    """
    Ingest流程专用错误处理装饰器

    - 捕获所有错误
    - 标记episode为failed
    - 记录结构化日志
    """
    @functools.wraps(func)
    async def wrapper(episode_id: str, *args, **kwargs) -> T:
        try:
            return await func(episode_id, *args, **kwargs)
        except ConcurrencyError as e:
            # 并发冲突不需要标记失败，直接抛出
            logger.warning(f"Concurrency conflict for {episode_id}: {e}")
            raise
        except PodcastError as e:
            # 已知错误
            await mark_episode_failed(episode_id, e)
            raise
        except Exception as e:
            # 未知错误
            logger.error(f"Unexpected error in ingest for {episode_id}: {e}", exc_info=True)
            await mark_episode_failed(episode_id, e)
            raise

    return wrapper
