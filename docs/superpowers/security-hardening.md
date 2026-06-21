# 字幕同步功能 - 安全加固指南

> **版本:** v0.3.0  
> **发布日期:** 2025-06-15  
> **适用范围:** 字幕同步 API、批量操作、管理员端点

---

## 安全概述

### 潜在安全风险

字幕同步功能涉及以下安全考虑：

1. **批量操作 API (`/api/admin/batch-sync-subtitles`)**
   - 风险: 无限制批量操作可能导致资源耗尽
   - 缓解: 速率限制、身份验证、批次大小限制

2. **文件系统访问**
   - 风险: 读取任意路径的文件可能导致信息泄露
   - 缓解: 路径验证、沙箱限制

3. **数据库操作**
   - 风险: SQL 注入、数据污染
   - 缓解: 参数化查询、输入验证

4. **CORS 配置**
   - 风险: 过于宽松的跨域策略
   - 缓解: 白名单域名、凭证限制

---

## 身份认证与授权

### 1. 实现 JWT 身份验证

**安装依赖:**

```bash
pip install python-jose[cryptography] passlib[bcrypt]
```

**配置认证中间件:**

```python
# backend/app/auth.py
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-here")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭据",
            headers={"WWW-Authenticate": "Bearer"},
        )

def get_current_admin(payload: dict = Depends(verify_token)) -> dict:
    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足，需要管理员角色"
        )
    return payload
```

**保护管理员端点:**

```python
# backend/app/main.py
from .auth import get_current_admin

@router.post("/api/admin/batch-sync-subtitles")
async def batch_sync_subtitle_segments(
    request: BatchSyncRequest,
    db: Session = Depends(get_db),
    current_admin: dict = Depends(get_current_admin)
) -> BatchSyncResponse:
    """批量同步字幕（仅管理员）"""
    # ... 现有逻辑 ...
```

---

## 速率限制

### 1. 安装限流依赖

```bash
pip install slowapi
```

### 2. 配置速率限制

```python
# backend/app/rate_limit.py
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request

limiter = Limiter(key_func=get_remote_address)

def get_real_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    return request.client.host
```

### 3. 应用速率限制

```python
# backend/app/main.py
from .rate_limit import limiter

app.state.limiter = limiter

# 批量同步 API: 每分钟最多 10 次
@router.post("/api/admin/batch-sync-subtitles")
@limiter.limit("10/minute")
async def batch_sync_subtitle_segments(
    request: Request,
    batch_request: BatchSyncRequest,
    db: Session = Depends(get_db),
    current_admin: dict = Depends(get_current_admin)
) -> BatchSyncResponse:
    """批量同步字幕（速率限制: 10次/分钟）"""
    # ... 现有逻辑 ...
```

---

## 输入验证

### 1. 验证 episode_ids 格式

```python
# backend/app/main.py
from pydantic import validator

class BatchSyncRequest(BaseModel):
    episode_ids: list[str] = Field(..., description="要同步的节目ID列表", max_items=50)

    @validator('episode_ids')
    def validate_episode_ids(cls, v):
        if not v:
            raise ValueError('episode_ids 不能为空')
        
        if len(v) > 50:
            raise ValueError('单次最多支持 50 个节目')
        
        for eid in v:
            if not isinstance(eid, str) or len(eid) > 100:
                raise ValueError(f'无效的节目 ID: {eid}')
        
        return v
```

### 2. 验证文件路径

```python
# backend/app/main.py
import os
from pathlib import Path

def safe_resolve_media_path(episode_id: str) -> Path:
    base_dir = Path(os.getenv('MEDIA_DIR', './data/media')).resolve()
    target_dir = (base_dir / episode_id).resolve()
    
    try:
        target_dir.relative_to(base_dir)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"无效的节目 ID: {episode_id}"
        )
    
    return target_dir / 'transcript.json'
```

---

## CORS 配置

### 生产环境 CORS 配置

```python
# backend/app/main.py
import os

ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "https://your-domain.com"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
```

---

## HTTPS/TLS 配置

### 1. 使用 Let's Encrypt 获取免费证书

```bash
sudo certbot --nginx -d your-domain.com
```

### 2. Nginx 反向代理配置

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;

    location /api {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 安全检查清单

### 部署前检查

- [ ] **身份认证**
  - [ ] JWT 认证已实现并测试
  - [ ] 管理员端点受保护
  - [ ] 令牌过期时间合理

- [ ] **速率限制**
  - [ ] 批量 API 限制 10 次/分钟
  - [ ] 单个 API 限制 20 次/分钟

- [ ] **输入验证**
  - [ ] episode_ids 格式验证
  - [ ] 批次大小限制
  - [ ] 文件路径遍历防护

- [ ] **CORS 配置**
  - [ ] 使用白名单域名

- [ ] **HTTPS/TLS**
  - [ ] SSL 证书已配置
  - [ ] 安全头已添加

---

**安全加固完成后，请参考:**
- [部署指南](./deployment-guide.md)
- [用户使用指南](./user-guide.md)
- [功能测试清单](./testing-checklist.md)
