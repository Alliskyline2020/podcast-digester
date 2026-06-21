"""
数据访问层模块
"""
from .derived_data_repository import (
    OutlineRepository,
    SummariesRepository,
    HighlightRepository,
    ProductInsightsRepository,
)

__all__ = [
    "OutlineRepository",
    "SummariesRepository",
    "HighlightRepository",
    "ProductInsightsRepository",
]
