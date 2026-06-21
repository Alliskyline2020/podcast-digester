"""
配置管理

集中管理所有配置项，使用环境变量覆盖默认值
"""
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, use system env vars


class Settings:
    """应用配置（从环境变量加载）"""

    def __init__(self):
        # ==================== 应用信息 ====================
        self.app_name = "Podcast Digester"
        self.app_version = "0.2.1-m2p"
        self.prompt_version = 2
        self.environment = os.getenv("ENV", "development")

        # ==================== 数据目录 ====================
        self.data_dir = Path(os.getenv(
            "PODCAST_DIGESTER_DATA_DIR",
            str(Path(__file__).parent.parent.parent / "data")
        ))

        # ==================== DeepSeek API ====================
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.deepseek_base_url = os.getenv(
            "DEEPSEEK_BASE_URL",
            "https://api.deepseek.com/v1"
        )
        self.deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

        # ==================== Whisper ASR 配置 ====================
        self.whisper_model = os.getenv("PODCAST_DIGESTER_WHISPER_MODEL", "small")
        self.whisper_compute = os.getenv("PODCAST_DIGESTER_WHISPER_COMPUTE", "int8")
        self.whisper_device = os.getenv("PODCAST_DIGESTER_WHISPER_DEVICE", "cpu")

        # ==================== ASR 转录参数 ====================
        self.whisper_beam_size = int(os.getenv("PODCAST_DIGESTER_WHISPER_BEAM_SIZE", "5"))
        self.whisper_min_silence_duration_ms = int(os.getenv("PODCAST_DIGESTER_WHISPER_MIN_SILENCE", "500"))
        self.max_model_cache_size = int(os.getenv("PODCAST_DIGESTER_MAX_MODEL_CACHE", "2"))

        # ==================== ASR 锁等待配置 ====================
        self.asr_max_wait_seconds = int(os.getenv("PODCAST_DIGESTER_ASR_MAX_WAIT", "300"))
        self.asr_wait_short_threshold = int(os.getenv("PODCAST_DIGESTER_ASR_WAIT_SHORT", "30"))
        self.asr_wait_medium_threshold = int(os.getenv("PODCAST_DIGESTER_ASR_WAIT_MEDIUM", "120"))
        self.asr_wait_short_interval = int(os.getenv("PODCAST_DIGESTER_ASR_INTERVAL_SHORT", "1"))
        self.asr_wait_medium_interval = int(os.getenv("PODCAST_DIGESTER_ASR_INTERVAL_MEDIUM", "5"))
        self.asr_wait_long_interval = int(os.getenv("PODCAST_DIGESTER_ASR_INTERVAL_LONG", "10"))

        # ==================== LLM 配置 ====================
        self.llm_default_temperature = float(os.getenv("PODCAST_DIGESTER_LLM_TEMPERATURE", "0.3"))
        self.llm_max_retries = int(os.getenv("PODCAST_DIGESTER_LLM_MAX_RETRIES", "3"))
        self.llm_base_delay = float(os.getenv("PODCAST_DIGESTER_LLM_BASE_DELAY", "1.0"))
        self.llm_max_delay = float(os.getenv("PODCAST_DIGESTER_LLM_MAX_DELAY", "60.0"))

        # ==================== 成本配置（元 per 1M tokens） ====================
        self.llm_cost_per_token = {
            "deepseek-chat": {"input": 0.00014, "output": 0.00028},
            "deepseek-reasoner": {"input": 0.00055, "output": 0.00219},
        }

        # ==================== Worker 配置 ====================
        self.worker_poll_interval_seconds = int(os.getenv("PODCAST_DIGESTER_WORKER_POLL_INTERVAL", "5"))
        self.worker_lock_file = Path(os.getenv("PODCAST_DIGESTER_WORKER_LOCK", "/tmp/podcast_worker.pid"))
        self.worker_process_cleanup_patterns = [
            "whisper",
            "faster-whisper",
            "python.*worker.py"
        ]

        # ==================== 进程锁配置 ====================
        self.asr_lock_file = Path(os.getenv("PODCAST_DIGESTER_ASR_LOCK", "/tmp/podcast_asr.lock"))

        # ==================== 限制和成本控制 ====================
        self.max_llm_cost_usd = float(os.getenv("PODCAST_DIGESTER_MAX_LLM_COST", "5.0"))
        self.max_episode_hours = float(os.getenv("PODCAST_DIGESTER_MAX_EPISODE_HOURS", "5.0"))
        self.max_concurrent_tasks = int(os.getenv("PODCAST_DIGESTER_MAX_CONCURRENT_TASKS", "1"))

        # ==================== LLM 处理限制 ====================
        self.llm_translate_batch_size = int(os.getenv("PODCAST_DIGESTER_LLM_BATCH_SIZE", "50"))
        self.llm_split_window_size = int(os.getenv("PODCAST_DIGESTER_LLM_WINDOW_SIZE", "800"))
        self.llm_highlight_max_segments = int(os.getenv("PODCAST_DIGESTER_LLM_MAX_SEGMENTS", "900"))
        self.llm_max_input_length = int(os.getenv("PODCAST_DIGESTER_MAX_INPUT_LENGTH", "200000"))

        # ==================== 性能和重试 ====================
        self.http_timeout_seconds = int(os.getenv("PODCAST_DIGESTER_HTTP_TIMEOUT", "30"))
        self.max_retries = int(os.getenv("PODCAST_DIGESTER_MAX_RETRIES", "3"))
        self.retry_delay_seconds = int(os.getenv("PODCAST_DIGESTER_RETRY_DELAY", "2"))

        # ==================== 阶段配置 ====================
        # 处理阶段权重（总和应该为 100）
        self.stage_weights = {
            "download": 20,
            "transcribe": 20,
            "chapterize": 10,
            "summarize": 17,
            "highlight": 18,
            "product_insights": 15,
        }
        self.stage_order = ["download", "transcribe", "chapterize", "summarize", "highlight", "product_insights"]

        # ==================== 日志 ====================
        self.log_level = os.getenv("PODCAST_DIGESTER_LOG_LEVEL", "INFO")
        log_file = os.getenv("PODCAST_DIGESTER_LOG_FILE")
        self.log_file = Path(log_file) if log_file else None

        # ==================== CORS和安全 ====================
        cors_origins_str = os.getenv("PODCAST_DIGESTER_CORS_ORIGINS", "")
        if cors_origins_str:
            self.cors_origins = [origin.strip() for origin in cors_origins_str.split(",")]
        else:
            self.cors_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]

        self.bind_host = os.getenv("PODCAST_DIGESTER_HOST", "127.0.0.1")
        self.bind_port = int(os.getenv("PODCAST_DIGESTER_PORT", "8000"))

        # ==================== 管理端认证 ====================
        # 共享密钥：保护 /api/admin/* 等敏感端点。
        # 留空时仅允许 loopback 访问管理端点（开发模式）。
        self.admin_token = os.getenv("PODCAST_DIGESTER_ADMIN_TOKEN", "")


# ==================== 全局实例 ====================

# 默认实例（从环境变量加载）
settings = Settings()


def get_settings() -> Settings:
    """获取配置实例（依赖注入用）"""
    return settings


def reload_settings() -> Settings:
    """重新加载配置（用于测试）"""
    global settings
    settings = Settings()
    return settings


# ==================== 辅助函数 ====================

def get_db_path() -> Path:
    """获取数据库文件路径"""
    return settings.data_dir / "podcast_digester.db"


def get_media_dir(episode_id: str) -> Path:
    """获取episode媒体目录"""
    return settings.data_dir / "media" / episode_id


def get_fixtures_dir() -> Path:
    """获取fixtures目录"""
    return settings.data_dir / "fixtures"


def is_production() -> bool:
    """是否生产环境"""
    return settings.environment == "production"


def is_development() -> bool:
    """是否开发环境"""
    return settings.environment == "development"


def calculate_llm_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """计算 LLM 调用成本（美元）

    Args:
        model: 模型名称
        prompt_tokens: 输入 token 数
        completion_tokens: 输出 token 数

    Returns:
        成本（美元）
    """
    rates = settings.llm_cost_per_token.get(model, settings.llm_cost_per_token["deepseek-chat"])
    input_cost = (prompt_tokens / 1_000_000) * rates["input"]
    output_cost = (completion_tokens / 1_000_000) * rates["output"]
    return input_cost + output_cost


def calculate_overall_progress(current_stage: str, stage_progress: float) -> float:
    """计算总体进度（0-1）

    Args:
        current_stage: 当前阶段 ID
        stage_progress: 当前阶段进度（0-1）

    Returns:
        总体进度（0-1）
    """
    overall = 0.0
    stage_found = False

    for stage_id in settings.stage_order:
        weight = settings.stage_weights.get(stage_id, 0)

        if stage_id == current_stage:
            # 当前阶段，添加部分进度
            overall += weight * stage_progress
            stage_found = True
        elif stage_found:
            # 后续阶段，不添加
            break
        else:
            # 之前阶段，添加完整权重
            overall += weight

    return overall / 100  # 转换为 0-1 范围


# ==================== 配置验证 ====================

def validate_config() -> None:
    """验证配置有效性"""
    errors = []

    # 验证必需的API密钥
    if not settings.deepseek_api_key or settings.deepseek_api_key == "sk-your-api-key-here":
        errors.append("DEEPSEEK_API_KEY must be set")

    # 验证数据目录可写
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        test_file = settings.data_dir / ".write_test"
        test_file.touch()
        test_file.unlink()
    except Exception as e:
        errors.append(f"Cannot write to data directory {settings.data_dir}: {e}")

    # 验证模型选择
    valid_models = ["tiny", "small", "medium", "large", "large-v2", "large-v3"]
    if settings.whisper_model not in valid_models:
        errors.append(
            f"Invalid WHISPER_MODEL: {settings.whisper_model}. "
            f"Must be one of {valid_models}"
        )

    # 验证阶段权重总和
    total_weight = sum(settings.stage_weights.values())
    if total_weight != 100:
        errors.append(
            f"Stage weights sum to {total_weight}, should be 100"
        )

    if errors:
        error_msg = "Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(error_msg)


# ==================== 导出的便捷访问 ====================

# 常用配置的便捷访问（向后兼容）
DEEPSEEK_API_KEY = settings.deepseek_api_key
DEEPSEEK_BASE_URL = settings.deepseek_base_url
DEEPSEEK_MODEL = settings.deepseek_model

WHISPER_MODEL = settings.whisper_model
WHISPER_COMPUTE = settings.whisper_compute
WHISPER_DEVICE = settings.whisper_device

WHISPER_BEAM_SIZE = settings.whisper_beam_size
WHISPER_MIN_SILENCE_DURATION_MS = settings.whisper_min_silence_duration_ms
MAX_MODEL_CACHE_SIZE = settings.max_model_cache_size

ASR_MAX_WAIT_SECONDS = settings.asr_max_wait_seconds
ASR_WAIT_SHORT_THRESHOLD = settings.asr_wait_short_threshold
ASR_WAIT_MEDIUM_THRESHOLD = settings.asr_wait_medium_threshold
ASR_WAIT_SHORT_INTERVAL = settings.asr_wait_short_interval
ASR_WAIT_MEDIUM_INTERVAL = settings.asr_wait_medium_interval
ASR_WAIT_LONG_INTERVAL = settings.asr_wait_long_interval
ASR_LOCK_FILE = settings.asr_lock_file

MAX_RETRIES = settings.llm_max_retries
BASE_DELAY = settings.llm_base_delay
MAX_DELAY = settings.llm_max_delay
DEFAULT_TEMPERATURE = settings.llm_default_temperature

WORKER_POLL_INTERVAL_SECONDS = settings.worker_poll_interval_seconds
WORKER_LOCK_FILE = settings.worker_lock_file
PROCESS_CLEANUP_PATTERNS = settings.worker_process_cleanup_patterns

MAX_LLM_COST_USD = settings.max_llm_cost_usd
MAX_EPISODE_HOURS = settings.max_episode_hours

DB_PATH = get_db_path()
DATA_DIR = settings.data_dir

# LLM 处理限制（向后兼容）
LLM_TRANSLATE_BATCH_SIZE = settings.llm_translate_batch_size
LLM_SPLIT_WINDOW_SIZE = settings.llm_split_window_size
LLM_HIGHLIGHT_MAX_SEGMENTS = settings.llm_highlight_max_segments
LLM_MAX_INPUT_LENGTH = settings.llm_max_input_length

# 阶段配置（向后兼容）
STAGE_NAMES = {
    "download": "下载",
    "transcribe": "转录",
    "chapterize": "分章",
    "summarize": "摘要",
    "highlight": "亮点",
    "product_insights": "产品洞察",
    "done": "完成",
}
STAGE_CONFIG = {
    k: {"weight": v, "name": STAGE_NAMES.get(k, k)}
    for k, v in settings.stage_weights.items()
}
# 添加 done 阶段（无权重，用于完成标记）
STAGE_CONFIG["done"] = {"weight": 0, "name": STAGE_NAMES["done"]}
STAGE_ORDER = settings.stage_order
