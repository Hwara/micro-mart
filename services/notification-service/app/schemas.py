"""notification-service NATS 이벤트 스키마."""

from pydantic import BaseModel, ConfigDict, Field


class OrderCompletedEvent(BaseModel):
    """order-service가 발행하는 order.completed 이벤트 payload."""

    model_config = ConfigDict(extra="ignore")

    order_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    total_amount: int = Field(ge=0)
    payment_id: int = Field(gt=0)
