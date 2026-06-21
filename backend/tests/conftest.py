"""
pytest配置和fixtures

提供全局fixtures和测试工具
"""
import asyncio
import tempfile
from pathlib import Path
from typing import AsyncGenerator, Generator
import pytest
import aiosqlite

from app.database import DB_PATH, init_db
from app.models import Episode, EpisodeStatus
from app.database import EpisodeRepository


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环（session级别）"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def temp_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """临时数据库fixture（每个测试独立）"""
    # 创建临时数据库文件
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db_path = f.name

    # 临时替换DB_PATH
    import app.database
    original_db_path = app.database.DB_PATH
    app.database.DB_PATH = Path(temp_db_path)

    # 初始化数据库
    await init_db()

    # 提供连接
    async with aiosqlite.connect(temp_db_path) as db:
        yield db

    # 清理
    Path(temp_db_path).unlink(missing_ok=True)
    app.database.DB_PATH = original_db_path


@pytest.fixture
def temp_data_dir():
    """临时数据目录fixture（用于测试媒体文件）"""
    import shutil
    temp_dir = Path(tempfile.mkdtemp())

    # 临时替换 data_dir
    import app.main
    original_data_dir = app.main.data_dir
    app.main.data_dir = temp_dir

    yield temp_dir

    # 清理
    shutil.rmtree(temp_dir, ignore_errors=True)
    app.main.data_dir = original_data_dir


@pytest.fixture(autouse=True)
def _bypass_auth_and_rate_limit():
    """autouse：测试中默认绕过 admin 认证和限流，避免每个测试单独配置。

    需要测试认证/限流本身时，在本测试里用 `monkeypatch` 还原行为即可。
    """
    from app.main import app, verify_admin
    from app.rate_limit import limiter as _lim

    app.dependency_overrides[verify_admin] = lambda: None
    # 让限流器永远放行
    original_allow = _lim.allow
    async def _always_allow(*args, **kwargs):
        return True
    _lim.allow = _always_allow

    yield

    app.dependency_overrides.pop(verify_admin, None)
    _lim.allow = original_allow


@pytest.fixture
async def sample_episode(temp_db: aiosqlite.Connection) -> dict:
    """示例episode数据"""
    episode_data = {
        "id": "test_ep_001",
        "title": "Test Episode",
        "status": EpisodeStatus.READY.value,
        "language": "en",
        "media_path": "/media/test_ep_001/audio.m4a",
        "is_fixture": False,
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    }
    await EpisodeRepository.create(episode_data)
    return episode_data


@pytest.fixture
def sample_transcript_data() -> dict:
    """示例transcript数据"""
    return {
        "episode_id": "test_ep_001",
        "language": "en",
        "segments": [
            {
                "id": 0,
                "start_ms": 0,
                "end_ms": 5000,
                "text_original": "Hello world",
                "text_translated": "你好世界",
                "speaker": None
            },
            {
                "id": 1,
                "start_ms": 5000,
                "end_ms": 10000,
                "text_original": "This is a test",
                "text_translated": "这是一个测试",
                "speaker": None
            }
        ]
    }


@pytest.fixture
def sample_outline_data() -> dict:
    """示例outline数据"""
    return {
        "episode_id": "test_ep_001",
        "entries": [
            {
                "title_zh": "第一章",
                "start_segment_id": 0,
                "end_segment_id": 5,
                "start_ms": 0,
                "end_ms": 15000
            },
            {
                "title_zh": "第二章",
                "start_segment_id": 6,
                "end_segment_id": 10,
                "start_ms": 15000,
                "end_ms": 30000
            }
        ]
    }


# ==================== Mock Fixtures ====================

@pytest.fixture
def mock_llm_response(monkeypatch):
    """Mock LLM响应"""
    async def mock_chat_json(*args, **kwargs):
        from app.models import ChapterSummary
        return {
            "chapters": [
                {
                    "title_zh": "测试章节",
                    "start_segment_id": 0,
                    "end_segment_id": 10
                }
            ]
        }

    import app.llm
    monkeypatch.setattr(app.llm, "chat_json", mock_chat_json)
    return mock_chat_json


@pytest.fixture
def mock_asr_result(monkeypatch):
    """Mock ASR结果"""
    from app.models import Transcript, Segment

    async def mock_run_asr(*args, **kwargs):
        return Transcript(
            episode_id="test_ep_001",
            language="en",
            segments=[
                Segment(
                    id=0,
                    start_ms=0,
                    end_ms=5000,
                    text_original="Hello world",
                    text_translated="你好世界"
                )
            ]
        ), "en", 5000

    import app.asr
    monkeypatch.setattr(app.asr, "run_asr", mock_run_asr)
    return mock_run_asr


# ==================== 测试辅助函数 ====================

async def create_test_episode(episode_id: str = "test_ep_001", **kwargs) -> dict:
    """创建测试episode的辅助函数"""
    default_data = {
        "id": episode_id,
        "title": f"Test Episode {episode_id}",
        "status": EpisodeStatus.PENDING.value,
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    }
    default_data.update(kwargs)
    await EpisodeRepository.create(default_data)
    return default_data


def assert_valid_episode(data: dict):
    """验证episode数据有效性"""
    assert "id" in data
    assert "title" in data
    assert "status" in data
    assert data["id"] is not None
    assert data["title"] is not None
    assert data["status"] in EpisodeStatus.__members__.values()
