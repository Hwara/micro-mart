import json

import pytest
from app.cache import get_cached_product, invalidate_product_cache, set_cached_product


@pytest.mark.asyncio
async def test_get_cached_product_hit_miss_and_failure(fake_redis) -> None:
    fake_redis.values["product:detail:1"] = json.dumps({"id": 1, "name": "Keyboard"})

    assert await get_cached_product(fake_redis, 1) == {"id": 1, "name": "Keyboard"}
    assert await get_cached_product(fake_redis, 2) is None

    fake_redis.fail_get = True
    assert await get_cached_product(fake_redis, 1) is None


@pytest.mark.asyncio
async def test_set_cached_product_stores_json_with_ttl_and_swallows_failure(fake_redis) -> None:
    await set_cached_product(fake_redis, 1, {"id": 1, "name": "Keyboard"}, ttl=60)

    assert json.loads(fake_redis.values["product:detail:1"]) == {"id": 1, "name": "Keyboard"}
    assert fake_redis.ttls["product:detail:1"] == 60

    fake_redis.fail_setex = True
    await set_cached_product(fake_redis, 2, {"id": 2}, ttl=60)


@pytest.mark.asyncio
async def test_invalidate_product_cache_deletes_detail_and_list_keys(fake_redis) -> None:
    fake_redis.values.update(
        {
            "product:detail:1": "{}",
            "product:list:p1:s10": "[]",
            "product:list:p2:s10": "[]",
            "other:key": "kept",
        }
    )

    await invalidate_product_cache(fake_redis, 1)

    assert "product:detail:1" in fake_redis.deleted
    assert "product:list:p1:s10" in fake_redis.deleted
    assert "product:list:p2:s10" in fake_redis.deleted
    assert fake_redis.values["other:key"] == "kept"

    fake_redis.fail_scan = True
    await invalidate_product_cache(fake_redis, 1)
