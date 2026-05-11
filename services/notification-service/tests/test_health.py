import pytest
from app.main import app
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_health_response_includes_nats_status():
    """GET /health returns service status without requiring NATS."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "notification-service",
        "nats_connected": False,
        "subject": "order.completed",
    }
