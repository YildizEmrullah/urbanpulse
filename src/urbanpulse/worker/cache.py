"""Redis cache with transparent in-memory dict fallback."""

import json
import logging
from typing import Any

from urbanpulse.config import settings

logger = logging.getLogger(__name__)

_mem_cache: dict[str, str] = {}
_redis_client = None


async def get_cache_client():
    """Get Redis client, or None if Redis is unavailable (uses in-memory fallback)."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not settings.redis_url:
        return None
    try:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await _redis_client.ping()
        logger.info("Redis connected: %s", settings.redis_url)
        return _redis_client
    except Exception as exc:
        logger.warning("Redis unavailable (%s) — using in-memory cache", exc)
        return None


async def cache_get(key: str) -> Any | None:
    client = await get_cache_client()
    try:
        if client:
            val = await client.get(key)
        else:
            val = _mem_cache.get(key)
        return json.loads(val) if val else None
    except Exception:
        return None


async def cache_set(key: str, value: Any, ttl: int = settings.cache_ttl_seconds) -> None:
    serialized = json.dumps(value, default=str)
    client = await get_cache_client()
    try:
        if client:
            await client.setex(key, ttl, serialized)
        else:
            _mem_cache[key] = serialized  # no TTL in fallback — acceptable for dev
    except Exception as exc:
        logger.debug("Cache set failed: %s", exc)


async def cache_delete(key: str) -> None:
    client = await get_cache_client()
    try:
        if client:
            await client.delete(key)
        else:
            _mem_cache.pop(key, None)
    except Exception:
        pass
