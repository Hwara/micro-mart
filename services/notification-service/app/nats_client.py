"""
NATS 클라이언트 전역 싱글턴.

main.py lifespan에서 초기화하고 종료 시 정리한다.
순환 import를 피하면서 health check와 메시지 발행/구독 로직이 같은 연결을 보게 한다.
"""

from __future__ import annotations

from typing import Any

_nats_client: Any | None = None


def set_nats_client(client: Any) -> None:
    """lifespan 시작 시 NATS client를 보관한다."""
    global _nats_client
    _nats_client = client


def get_nats_client() -> Any | None:
    """현재 NATS client를 반환한다."""
    return _nats_client


def clear_nats_client() -> None:
    """lifespan 종료 시 NATS client 참조를 제거한다."""
    global _nats_client
    _nats_client = None
