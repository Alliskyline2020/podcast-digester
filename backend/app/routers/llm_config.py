"""LLM 配置设置端点：前端「设置页」读 / 写 / 测试连接。

所有路由通过 verify_admin 保护（与 admin.py 一致）。
api_key 永不完整回传；base_url 过 SSRF 守卫。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..deps import verify_admin
from ..llm.client import ping_llm
from ..llm.config import (
    PROVIDERS, _resolve_config, _assert_public_https_base_url, infer_provider_type,
)
from ..llm.runtime_config import read_runtime_override, write_runtime_override

router = APIRouter(dependencies=[Depends(verify_admin)])
logger = logging.getLogger(__name__)


# ==================== Schemas ====================

class LLMConfigUpdate(BaseModel):
    """设置页提交体：所有字段可选，未提供 = 不改。"""
    provider: str | None = None
    provider_type: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


# ==================== Helpers ====================

def _mask(key: str) -> str:
    return ("****" + key[-4:]) if key and len(key) >= 4 else "****"


def _public_providers() -> dict:
    """给下拉用的预设（全是展示字段，无敏感信息）。"""
    return {
        name: {
            "title": p["title"],
            "provider_type": p["provider_type"],
            "default_base_url": p["default_base_url"],
            "default_model": p["default_model"],
        }
        for name, p in PROVIDERS.items()
    }


# ==================== Routes ====================

@router.get("/api/admin/llm-config")
async def get_llm_config() -> dict:
    """返回当前生效配置（key 掩码）+ provider 预设。未配 key 也不报错。"""
    cfg = _resolve_config(require_key=False)
    return {
        "provider": cfg.provider,
        "provider_type": cfg.provider_type,
        "base_url": cfg.base_url,
        "model": cfg.model,
        "has_api_key": bool(cfg.api_key),
        "api_key_masked": _mask(cfg.api_key),
        "providers": _public_providers(),
    }


@router.put("/api/admin/llm-config")
async def put_llm_config(req: LLMConfigUpdate) -> dict:
    """写入运行时覆写。未提供 api_key 时保留旧值。"""
    if req.base_url:
        try:
            _assert_public_https_base_url(req.base_url)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    if req.provider_type and req.provider_type not in (
        "openai_compatible", "anthropic_compatible"
    ):
        raise HTTPException(status_code=400, detail="provider_type 非法")

    override = read_runtime_override() or {}
    for field in ("provider", "provider_type", "base_url", "model"):
        val = getattr(req, field)
        if val:
            override[field] = val
    # api_key：仅在用户真的填了新值时覆盖（None/空 = 保持不变）
    if req.api_key:
        override["api_key"] = req.api_key

    await write_runtime_override(override)
    logger.info("LLM 配置已更新（provider=%s）", override.get("provider"))

    cfg = _resolve_config(require_key=False)
    return {
        "ok": True,
        "provider": cfg.provider,
        "has_api_key": bool(cfg.api_key),
        "api_key_masked": _mask(cfg.api_key),
    }


@router.post("/api/admin/llm-config/test")
async def test_llm_config(req: LLMConfigUpdate) -> dict:
    """用提交中的值（未保存也能测）发一个极小请求验证连通性。"""
    from ..llm.config import LLMConfig

    base = _resolve_config(require_key=False)
    provider = req.provider or base.provider
    provider_type = req.provider_type or infer_provider_type(provider)
    api_key = req.api_key or base.api_key
    base_url = req.base_url if req.base_url is not None else base.base_url
    model = req.model or base.model

    if not api_key:
        return {"ok": False, "detail": "未填写 API Key"}
    if base_url:
        try:
            _assert_public_https_base_url(base_url)
        except ValueError as e:
            return {"ok": False, "detail": str(e)}

    cfg = LLMConfig(
        provider=provider, provider_type=provider_type, api_key=api_key,
        base_url=base_url, model=model,
        temperature=base.temperature, max_tokens=base.max_tokens, timeout=base.timeout,
    )
    ok, detail = await ping_llm(cfg)
    return {"ok": ok, "detail": detail}
