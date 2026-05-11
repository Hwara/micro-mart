import pytest
from app.schemas import OrderCompletedEvent
from pydantic import ValidationError


def test_order_completed_event_accepts_valid_payload():
    """Valid order.completed payload is accepted."""
    event = OrderCompletedEvent.model_validate(
        {
            "order_id": 1,
            "user_id": 10,
            "total_amount": 25000,
            "payment_id": 3,
        }
    )

    assert event.order_id == 1
    assert event.user_id == 10
    assert event.total_amount == 25000
    assert event.payment_id == 3


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("order_id", 0),
        ("user_id", 0),
        ("total_amount", -1),
        ("payment_id", 0),
    ],
)
def test_order_completed_event_rejects_invalid_numeric_bounds(field_name, value):
    """Numeric business identifiers and amount enforce documented bounds."""
    payload = {
        "order_id": 1,
        "user_id": 10,
        "total_amount": 25000,
        "payment_id": 3,
    }
    payload[field_name] = value

    with pytest.raises(ValidationError):
        OrderCompletedEvent.model_validate(payload)


def test_order_completed_event_ignores_extra_fields():
    """Extra fields do not break consumers when event payload expands."""
    event = OrderCompletedEvent.model_validate(
        {
            "order_id": 1,
            "user_id": 10,
            "total_amount": 25000,
            "payment_id": 3,
            "future_field": "ignored",
        }
    )

    assert not hasattr(event, "future_field")
