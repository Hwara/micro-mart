import os
from pathlib import Path

import pytest

KEY_DIR = Path(__file__).resolve().parents[3] / "keys"
os.environ.setdefault("JWT_PRIVATE_KEY_FILE", str(KEY_DIR / "private.pem"))
os.environ.setdefault("JWT_PUBLIC_KEY_FILE", str(KEY_DIR / "public.pem"))

from app import auth as auth_utils


class FakePipeline:
    """Minimal async Redis pipeline for refresh token rotation tests."""

    def __init__(self, redis: "FakeRedis", fail_execute: bool = False) -> None:
        self.redis = redis
        self.fail_execute = fail_execute
        self.operations: list[tuple[str, str, str]] = []

    async def __aenter__(self) -> "FakePipeline":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.operations.append((key, str(ttl), value))

    async def execute(self) -> None:
        if self.fail_execute:
            raise RuntimeError("pipeline failed")
        for key, ttl, value in self.operations:
            self.redis.values[key] = value
            self.redis.ttls[key] = int(ttl)


class FakeRedis:
    """Small Redis subset used by rotate_refresh_token."""

    def __init__(self, fail_pipeline: bool = False) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.fail_pipeline = fail_pipeline

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self, fail_execute=self.fail_pipeline)


@pytest.mark.asyncio
async def test_rotate_refresh_token_tombstones_old_token_and_persists_new_token() -> None:
    """Rotation should keep reuse detection while storing the new session token."""
    redis = FakeRedis()
    redis.values["refresh:user:1:web"] = "old-token"
    redis.values["refresh:token:old-token"] = "1:web"
    redis.ttls["refresh:user:1:web"] = 3600

    new_token = await auth_utils.rotate_refresh_token(redis, user_id=1, device="web")

    assert redis.values["refresh:user:1:web"] == new_token
    assert redis.values[f"refresh:token:{new_token}"] == "1:web"
    assert redis.values["refresh:token:old-token"] == "REVOKED:1:web"


@pytest.mark.asyncio
async def test_rotate_refresh_token_preserves_old_token_when_pipeline_fails() -> None:
    """If persistence fails, the old refresh token should not be revoked first."""
    redis = FakeRedis(fail_pipeline=True)
    redis.values["refresh:user:1:web"] = "old-token"
    redis.values["refresh:token:old-token"] = "1:web"
    redis.ttls["refresh:user:1:web"] = 3600
    original_values = redis.values.copy()

    with pytest.raises(RuntimeError):
        await auth_utils.rotate_refresh_token(redis, user_id=1, device="web")

    assert redis.values == original_values
    assert redis.values["refresh:user:1:web"] == "old-token"
    assert redis.values["refresh:token:old-token"] == "1:web"
