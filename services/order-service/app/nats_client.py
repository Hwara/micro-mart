"""
NATS 클라이언트 전역 싱글턴

main.py의 lifespan에서 초기화, order_service.py에서 참조.
순환 import(order_service → main → order_service) 방지를 위해
별도 모듈로 분리.
"""

from __future__ import annotations

from typing import Any

# 앱 수명 동안 단 하나의 NATS 커넥션을 보관
_nats_client: Any | None = None


def set_nats_client(client: Any) -> None:
    """lifespan 시작 시 main.py에서 호출."""
    global _nats_client
    _nats_client = client


def get_nats_client() -> Any | None:
    """order_service.py에서 발행 시 호출."""
    return _nats_client


def clear_nats_client() -> None:
    """lifespan 종료 시 main.py에서 호출."""
    global _nats_client
    _nats_client = None
