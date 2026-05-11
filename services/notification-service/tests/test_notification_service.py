import json
from unittest.mock import AsyncMock

import pytest
from app.config import get_settings
from app.services import notification_service


@pytest.mark.asyncio
async def test_handle_order_completed_message_processes_valid_payload(mocker):
    """Valid raw NATS payload triggers notification simulation."""
    mock_send = mocker.patch(
        "app.services.notification_service.simulate_notification_send",
        new=AsyncMock(),
    )
    payload = {
        "order_id": 1,
        "user_id": 10,
        "total_amount": 25000,
        "payment_id": 3,
    }

    await notification_service.handle_order_completed_message(json.dumps(payload).encode())

    mock_send.assert_awaited_once()
    sent_event = mock_send.await_args.args[0]
    assert sent_event.order_id == 1
    assert sent_event.user_id == 10


@pytest.mark.asyncio
async def test_handle_order_completed_message_records_invalid_json(mocker):
    """Invalid JSON is classified as INVALID_JSON and swallowed."""
    mock_failed_counter = mocker.patch.object(
        notification_service.notification_send_failed_counter, "add"
    )

    await notification_service.handle_order_completed_message(b"{not-json")

    mock_failed_counter.assert_called_with(
        1,
        {"reason": "INVALID_JSON", "channel": "email"},
    )


@pytest.mark.asyncio
async def test_handle_order_completed_message_records_invalid_payload(mocker):
    """Schema validation failures are classified as INVALID_PAYLOAD."""
    mock_failed_counter = mocker.patch.object(
        notification_service.notification_send_failed_counter, "add"
    )

    await notification_service.handle_order_completed_message(
        json.dumps(
            {
                "order_id": 0,
                "user_id": 10,
                "total_amount": 25000,
                "payment_id": 3,
            }
        ).encode()
    )

    mock_failed_counter.assert_called_with(
        1,
        {"reason": "INVALID_PAYLOAD", "channel": "email"},
    )


@pytest.mark.asyncio
async def test_simulate_notification_send_raises_when_failure_rate_is_one(monkeypatch):
    """Failure rate 1.0 always raises SIMULATED_SEND_FAILURE."""
    settings = get_settings()
    monkeypatch.setattr(settings, "notification_failure_rate", 1.0)
    event = notification_service.OrderCompletedEvent(
        order_id=1,
        user_id=10,
        total_amount=25000,
        payment_id=3,
    )

    with pytest.raises(notification_service.NotificationSendError) as exc_info:
        await notification_service.simulate_notification_send(event)

    assert exc_info.value.reason == "SIMULATED_SEND_FAILURE"
