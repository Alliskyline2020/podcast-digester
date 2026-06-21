"""Glossary router: term-correction dictionary CRUD.

Routes:
- POST   /api/glossary/entries        获取词库所有条目
- POST   /api/glossary/add            添加词库条目
- DELETE /api/glossary/entries/{correct}  删除词库条目

注：POST /api/episodes/{id}/apply-glossary 仍留在 main.py，因为它依赖
_load_episode_bundle（待后续 phase 把 loader 抽到 services 后再迁）。
"""
import logging

from fastapi import APIRouter
from pydantic import BaseModel

from ..deps import data_dir


router = APIRouter()
logger = logging.getLogger(__name__)


# ==================== Schemas ====================

class GlossaryEntry(BaseModel):
    """词库条目"""
    correct: str
    wrong: list[str]


class GlossaryResponse(BaseModel):
    """词库响应"""
    entries: dict[str, list[str]]


# ==================== Routes ====================

@router.post("/api/glossary/entries", response_model=GlossaryResponse)
async def get_glossary_entries() -> GlossaryResponse:
    """获取词库所有条目"""
    from ..services.glossary import get_glossary

    glossary = get_glossary(data_dir)
    return GlossaryResponse(entries=glossary.get_all_entries())


@router.post("/api/glossary/add")
async def add_glossary_entry(entry: GlossaryEntry):
    """
    添加词库条目

    Args:
        entry: 词库条目
    """
    from ..services.glossary import get_glossary

    glossary = get_glossary(data_dir)
    glossary.add_entry(entry.correct, entry.wrong)

    return {"success": True, "message": "词库条目已添加"}


@router.delete("/api/glossary/entries/{correct}")
async def delete_glossary_entry(correct: str):
    """
    删除词库条目

    Args:
        correct: 正确的词汇
    """
    from ..services.glossary import get_glossary

    glossary = get_glossary(data_dir)
    glossary.remove_entry(correct)

    return {"success": True, "message": "词库条目已删除"}
