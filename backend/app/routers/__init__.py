"""Router package for podcast-digester API.

Each module exposes a `router: APIRouter` that main.py includes via
`app.include_router(...)`. Routers import shared deps from `..deps`
and helpers from `..services.background_tasks`, never from `..main`.
"""
