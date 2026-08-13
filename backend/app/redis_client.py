from redis.asyncio import Redis

from app.core.config import settings


async def check_redis() -> bool:
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.ping()
        return True
    finally:
        await client.aclose()
