"""
order.completed 이벤트 처리와 알림 발송 시뮬레이션.

NATS callback은 raw bytes만 이 모듈로 넘기고, JSON 파싱, payload 검증,
발송 시뮬레이션, 로그/메트릭 기록은 이 서비스 계층에서 처리한다.
"""

import asyncio
import json
import random
import time
from json import JSONDecodeError

import structlog
from opentelemetry import metrics
from pydantic import ValidationError

from ..config import get_settings
from ..schemas import OrderCompletedEvent

log = structlog.get_logger(__name__)

CHANNEL_EMAIL = "email"
ORDER_COMPLETED_SUBJECT = "order.completed"

REASON_INVALID_JSON = "INVALID_JSON"
REASON_INVALID_PAYLOAD = "INVALID_PAYLOAD"
REASON_SIMULATED_SEND_FAILURE = "SIMULATED_SEND_FAILURE"
REASON_UNEXPECTED_ERROR = "UNEXPECTED_ERROR"

meter = metrics.get_meter("notification-service")

notification_message_consumed_counter = meter.create_counter(
    "notification_message_consumed_total",
    description="NATS 메시지 소비 횟수",
)
notification_send_success_counter = meter.create_counter(
    "notification_send_success_total",
    description="알림 발송 성공 횟수",
)
notification_send_failed_counter = meter.create_counter(
    "notification_send_failed_total",
    description="알림 처리 실패 횟수",
)
notification_processing_latency_histogram = meter.create_histogram(
    "notification_processing_latency_ms",
    description="메시지 수신부터 처리 완료까지 시간",
    unit="ms",
)
notification_send_latency_histogram = meter.create_histogram(
    "notification_send_latency_ms",
    description="발송 시뮬레이션 소요 시간",
    unit="ms",
)


class NotificationSendError(Exception):
    """알림 발송 시뮬레이션 실패를 reason 값과 함께 표현한다."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


async def handle_order_completed_message(raw_data: bytes) -> None:
    """NATS order.completed 메시지를 검증하고 알림 발송 시뮬레이션을 수행한다."""
    start = time.perf_counter()
    subject = get_settings().nats_subject_order_completed
    notification_message_consumed_counter.add(1, {"subject": subject})

    log.info(
        "notification_message_received",
        channel=CHANNEL_EMAIL,
    )

    try:
        payload = json.loads(raw_data.decode("utf-8"))
    except (UnicodeDecodeError, JSONDecodeError):
        _record_failure(REASON_INVALID_JSON)
        log.warning(
            "notification_payload_invalid",
            reason=REASON_INVALID_JSON,
            channel=CHANNEL_EMAIL,
        )
        _record_processing_latency(start, subject)
        return

    try:
        event = OrderCompletedEvent.model_validate(payload)
    except ValidationError:
        _record_failure(REASON_INVALID_PAYLOAD)
        log.warning(
            "notification_payload_invalid",
            reason=REASON_INVALID_PAYLOAD,
            channel=CHANNEL_EMAIL,
        )
        _record_processing_latency(start, subject)
        return

    try:
        await simulate_notification_send(event)
        notification_send_success_counter.add(1, {"channel": CHANNEL_EMAIL})
        log.info(
            "notification_send_succeeded",
            order_id=event.order_id,
            user_id=event.user_id,
            payment_id=event.payment_id,
            total_amount=event.total_amount,
            channel=CHANNEL_EMAIL,
        )
    except NotificationSendError as exc:
        _record_failure(exc.reason)
        log.warning(
            "notification_send_failed",
            order_id=event.order_id,
            user_id=event.user_id,
            payment_id=event.payment_id,
            total_amount=event.total_amount,
            reason=exc.reason,
            channel=CHANNEL_EMAIL,
        )
    except Exception as exc:
        _record_failure(REASON_UNEXPECTED_ERROR)
        log.exception(
            "notification_send_failed",
            order_id=event.order_id,
            user_id=event.user_id,
            payment_id=event.payment_id,
            total_amount=event.total_amount,
            reason=REASON_UNEXPECTED_ERROR,
            channel=CHANNEL_EMAIL,
            error=str(exc),
        )
    finally:
        _record_processing_latency(start, subject)


async def simulate_notification_send(event: OrderCompletedEvent) -> None:
    """주문 완료 알림 발송을 시뮬레이션한다."""
    settings = get_settings()
    start = time.perf_counter()

    log.info(
        "notification_send_started",
        order_id=event.order_id,
        user_id=event.user_id,
        payment_id=event.payment_id,
        total_amount=event.total_amount,
        channel=CHANNEL_EMAIL,
    )

    if settings.notification_send_delay_ms > 0:
        await asyncio.sleep(settings.notification_send_delay_ms / 1000)

    if (
        settings.notification_failure_rate > 0
        and random.random() < settings.notification_failure_rate
    ):
        notification_send_latency_histogram.record(
            _elapsed_ms(start),
            {"channel": CHANNEL_EMAIL},
        )
        raise NotificationSendError(REASON_SIMULATED_SEND_FAILURE)

    notification_send_latency_histogram.record(
        _elapsed_ms(start),
        {"channel": CHANNEL_EMAIL},
    )


def _record_failure(reason: str) -> None:
    """알림 처리 실패 카운터를 낮은 카디널리티 label로 기록한다."""
    notification_send_failed_counter.add(1, {"reason": reason, "channel": CHANNEL_EMAIL})


def _record_processing_latency(start: float, subject: str) -> None:
    """메시지 처리 시간을 ms 단위 histogram으로 기록한다."""
    notification_processing_latency_histogram.record(_elapsed_ms(start), {"subject": subject})


def _elapsed_ms(start: float) -> float:
    """perf_counter 시작점에서 지난 시간을 ms로 변환한다."""
    return (time.perf_counter() - start) * 1000
