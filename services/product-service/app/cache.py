"""
Redis Cache-Aside 헬퍼

설계 결정:
- JSON 직렬화: orjson 대신 표준 json 사용 (의존성 최소화)
  성능이 중요해지면 orjson으로 교체 가능
- 캐시 미스 시 None 반환: 예외 대신 None으로 처리 → 호출부 코드 단순화
- Redis 장애 시 Graceful Degradation: 캐시 오류는 로그만 남기고 DB fallback
  → 캐시는 성능 최적화 수단이지 필수 인프라가 아님
"""

import json

import redis.asyncio as aioredis
import structlog

log = structlog.get_logger(__name__)

# 키 네임스페이스: user-service의 refresh:* 키와 충돌 방지
_PREFIX_PRODUCT = "product:detail:"
_PREFIX_LIST = "product:list:"


def _product_key(product_id: int) -> str:
    return f"{_PREFIX_PRODUCT}{product_id}"


def _list_key(page: int, page_size: int) -> str:
    return f"{_PREFIX_LIST}p{page}:s{page_size}"


async def get_cached_product(
    redis: aioredis.Redis,
    product_id: int,
) -> dict | None:
    """
    상품 상세 캐시 조회.
    반환값: dict (캐시 히트) | None (캐시 미스 또는 Redis 장애)
    """
    try:
        data = await redis.get(_product_key(product_id))
        if data is None:
            return None
        return json.loads(data)
    except Exception as e:
        # Redis 장애 시 DB fallback을 위해 None 반환 (서비스 중단 방지)
        log.warning("Redis Get 실패", product_id=product_id, error=str(e))
        return None


async def set_cached_product(
    redis: aioredis.Redis,
    product_id: int,
    data: dict,
    ttl: int,
) -> None:
    """상품 상세 캐시 저장."""
    try:
        await redis.setex(_product_key(product_id), ttl, json.dumps(data, default=str))
    except Exception as e:
        log.warning("Redis Set 실패", product_id=product_id, error=str(e))


async def invalidate_product_cache(
    redis: aioredis.Redis,
    product_id: int,
) -> None:
    """
    상품 수정/삭제 시 캐시 무효화.

    목록 캐시도 함께 삭제: 상품명·가격이 목록에 표시되므로
    특정 페이지를 특정하기 어려워 패턴 삭제 사용.
    주의: SCAN + DEL 패턴은 키가 많을 때 느릴 수 있음.
          운영에서는 목록 캐시 TTL을 짧게 두고 자연 만료에 의존하는 게 더 안전.
    """
    try:
        # 상세 캐시 삭제
        await redis.delete(_product_key(product_id))

        # 목록 캐시 패턴 삭제 (SCAN 사용: KEYS는 운영 Redis에서 사용 금지)
        cursor = 0
        while True:
            cursor, keys = await redis.scan(
                cursor=cursor,
                match=f"{_PREFIX_LIST}*",
                count=100,
            )
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
    except Exception as e:
        log.warning("Redis 캐시 무효화 실패", product_id=product_id, error=str(e))
