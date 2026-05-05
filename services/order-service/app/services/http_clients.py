"""
order-service → 외부 서비스 HTTP 클라이언트

설계 원칙:
- 명시적 timeout 강제 (dev_convention.md §12)
- 재시도 가능/불가 오류 구분:
    재고 부족(422), 버전 충돌(409): 재시도 금지 → 즉시 실패
    네트워크 오류(httpx.TimeoutException): 재시도 가능하지만 Saga 특성상 비재시도로 처리
    (재시도 시 stock_deducted 상태 추적이 복잡해지므로 이번 설계에서는 단순화)
- 호출 실패는 호출자(order_service.py)가 Saga 상태로 처리
"""

import httpx
import structlog

from ..config import get_settings

log = structlog.get_logger(__name__)


# 낙관적 잠금 충돌 시 최대 재시도 횟수
# 3회 이상이면 해당 상품에 극심한 경합이 있다는 의미 → 포기하고 실패 처리
# TODO: settings로 보내 환경변수로 변경할 수 있도록 할 것
MAX_OPTIMISTIC_RETRY = 3


class ProductServiceError(Exception):
    """product-service 호출 실패를 래핑하는 예외."""

    def __init__(self, message: str, code: str = "PRODUCT_SERVICE_ERROR", status_code: int = 500):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class PaymentServiceError(Exception):
    """payment-service 호출 실패를 래핑하는 예외."""

    def __init__(self, message: str, code: str = "PAYMENT_SERVICE_ERROR", status_code: int = 500):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


async def get_product(product_id: int) -> dict:
    """
    product-service에서 상품 정보 조회.

    주문 생성 시 가격·활성화 여부 확인용.
    반환: { id, name, price, stock, is_active }
    """
    settings = get_settings()
    url = f"{settings.product_service_url}/products/{product_id}"

    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            resp = await client.get(url)
    except httpx.TimeoutException as e:
        log.error("product-service 조회 타임아웃", product_id=product_id)
        raise ProductServiceError(
            f"상품 조회 중 타임아웃이 발생했습니다. (product_id={product_id})",
            code="PRODUCT_SERVICE_TIMEOUT",
            status_code=504,
        ) from e
    except httpx.RequestError as e:
        log.error("product-service 연결 실패", product_id=product_id, error=str(e))
        raise ProductServiceError(
            "상품 서비스에 연결할 수 없습니다.",
            code="PRODUCT_SERVICE_UNAVAILABLE",
            status_code=503,
        ) from e

    if resp.status_code == 404:
        raise ProductServiceError(
            f"존재하지 않는 상품입니다. (product_id={product_id})",
            code="PRODUCT_NOT_FOUND",
            status_code=404,
        )
    if resp.status_code != 200:
        log.error("product-service 조회 실패", product_id=product_id, http_status=resp.status_code)
        raise ProductServiceError(
            "상품 정보를 가져오지 못했습니다.",
            code="PRODUCT_SERVICE_ERROR",
            status_code=resp.status_code,
        )

    return resp.json()


async def deduct_stock(product_id: int, quantity: int, expected_version: int) -> None:
    """
    product-service 재고 차감 요청 (낙관적 잠금 포함).

    VERSION_CONFLICT(409) 시 재시도 전략:
    - 상품을 재조회해 최신 version 확보 후 재시도
    - 최대 MAX_OPTIMISTIC_RETRY(3)회 반복
    - 모두 실패 시 ORDER_STOCK_CONFLICT 에러 발생

    """
    settings = get_settings()
    url = f"{settings.product_service_url}/products/{product_id}/deduct-stock"
    headers = {"X-Internal-Token": settings.internal_service_token}

    current_version = expected_version

    for attempt in range(1, MAX_OPTIMISTIC_RETRY + 1):
        body = {"quantity": quantity, "expected_version": current_version}

        try:
            async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
                resp = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as e:
            log.error("재고 차감 타임아웃", product_id=product_id, quantity=quantity)
            raise ProductServiceError(
                "재고 차감 중 타임아웃이 발생했습니다.",
                code="STOCK_DEDUCT_TIMEOUT",
                status_code=504,
            ) from e
        except httpx.RequestError as e:
            log.error("재고 차감 연결 실패", product_id=product_id, error=str(e))
            raise ProductServiceError(
                "상품 서비스에 연결할 수 없습니다.",
                code="PRODUCT_SERVICE_UNAVAILABLE",
                status_code=503,
            ) from e

        if resp.status_code == 200:
            log.info("재고 차감 성공", product_id=product_id, quantity=quantity)
            return

        # 실패 응답 파싱 후 원인 코드 추출
        try:
            error_detail = resp.json().get("detail", {})
            code = (
                error_detail.get("code", "STOCK_DEDUCT_ERROR")
                if isinstance(error_detail, dict)
                else "STOCK_DEDUCT_ERROR"
            )
        except Exception:
            code = "STOCK_DEDUCT_ERROR"

        if code == "VERSION_CONFLICT":
            # 낙관적 잠금 충돌 -> 최신 version 재조회 후 재시도
            log.warning(
                "낙관적 잠금 충돌 — 재조회 후 재시도",
                product_id=product_id,
                attempt=attempt,
                tried_version=current_version,
            )
            if attempt < MAX_OPTIMISTIC_RETRY:
                try:
                    # 최신 상태 재조회해서 version 갱신
                    fresh = await get_product(product_id)
                    current_version = fresh["version"]
                    log.info(
                        "재조회 완료 — 새 version으로 재시도",
                        product_id=product_id,
                        new_version=current_version,
                        attempt=attempt,
                    )
                    continue  # 재시도
                except ProductServiceError as e:
                    raise ProductServiceError(
                        f"버전 충돌 후 재조회 실패: {e}",
                        code="PRODUCT_SERVICE_ERROR",
                        status_code=503,
                    ) from e
            else:
                # MAX_OPTIMISTIC_RETRY 소진 → 경합이 너무 심한 상태
                log.error(
                    "낙관적 잠금 재시도 횟수 초과",
                    product_id=product_id,
                    max_retry=MAX_OPTIMISTIC_RETRY,
                )
                raise ProductServiceError(
                    f"재고 차감 충돌이 {MAX_OPTIMISTIC_RETRY}회 반복됐습니다. "
                    + "잠시 후 다시 시도해주세요.",
                    code="ORDER_STOCK_CONFLICT",
                    status_code=409,
                )

        elif code == "INSUFFICIENT_STOCK":
            # 재고 부족 → 재시도 불가, 즉시 실패
            log.warning(
                "재고 부족",
                product_id=product_id,
                quantity=quantity,
            )
            raise ProductServiceError(
                f"재고가 부족합니다. (product_id={product_id})",
                code="INSUFFICIENT_STOCK",
                status_code=409,
            )

        else:
            # 그 외 오류 (404, 500 등)
            log.error(
                "재고 차감 실패",
                product_id=product_id,
                http_status=resp.status_code,
                code=code,
            )
            raise ProductServiceError(
                f"재고 차감 실패: {code}",
                code=code,
                status_code=resp.status_code,
            )

    raise ProductServiceError("재고 차감 실패", code="STOCK_DEDUCT_ERROR", status_code=500)


async def restore_stock(product_id: int, quantity: int) -> bool:
    """
    product-service 재고 복구 요청 (보상 트랜잭션).

    낙관적 잠금 미적용:
    - 복구는 단방향 증가 연산 → 경합 없음
    - version 충돌로 복구가 막히면 재고 영구 소실 위험

    best-effort: 실패 시 예외를 흡수하고 로그만 남김.
    호출자(order_service.py)가 saga_status로 복구 배치 대상 처리.
    """
    settings = get_settings()
    url = f"{settings.product_service_url}/products/{product_id}/restore-stock"
    headers = {"X-Internal-Token": settings.internal_service_token}
    body = {"quantity": quantity}

    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            resp = await client.post(url, json=body, headers=headers)

        if resp.status_code == 200:
            log.info("재고 복구 성공 (보상 트랜잭션)", product_id=product_id, quantity=quantity)
            return True

        log.error(
            "재고 복구 실패 (보상 트랜잭션)",
            product_id=product_id,
            quantity=quantity,
            http_status=resp.status_code,
        )
        return False
    except Exception as e:
        # 보상 트랜잭션 실패는 별도 복구 배치가 처리 — 여기선 로그만 남김
        log.error(
            "재고 복구 예외 발생 (보상 트랜잭션)",
            product_id=product_id,
            quantity=quantity,
            error=str(e),
        )
        return False


async def request_payment(order_id: int, user_id: int, amount: int) -> dict:
    """
    payment-service 결제 요청 (내부 API).

    service_function_definition.md §5 호출 규격 준수:
    POST /payments, X-Internal-Token 필수
    성공: 201, { id, status: "APPROVED", pg_transaction_id, ... }
    실패: 402 PAYMENT_REJECTED
    """
    settings = get_settings()
    url = f"{settings.payment_service_url}/payments"
    headers = {"X-Internal-Token": settings.internal_service_token}
    body = {"order_id": order_id, "user_id": user_id, "amount": amount}

    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.TimeoutException as e:
        log.error("결제 요청 타임아웃", order_id=order_id, amount=amount)
        raise PaymentServiceError(
            "결제 요청 중 타임아웃이 발생했습니다.",
            code="PAYMENT_TIMEOUT",
            status_code=504,
        ) from e
    except httpx.RequestError as e:
        log.error("결제 서비스 연결 실패", order_id=order_id, error=str(e))
        raise PaymentServiceError(
            "결제 서비스에 연결할 수 없습니다.",
            code="PAYMENT_SERVICE_UNAVAILABLE",
            status_code=503,
        ) from e

    if resp.status_code == 201:
        log.info("결제 승인", order_id=order_id, amount=amount)
        return resp.json()

    # 실패 원인 코드 추출 (service_function_definition.md 응답 형식)
    try:
        outer = resp.json().get("detail", {})
        code = (
            outer.get("code", "PAYMENT_REJECTED") if isinstance(outer, dict) else "PAYMENT_REJECTED"
        )
    except Exception:
        code = "PAYMENT_REJECTED"

    log.warning(
        "결제 거절",
        order_id=order_id,
        amount=amount,
        http_status=resp.status_code,
        code=code,
    )
    raise PaymentServiceError(
        f"결제가 거절되었습니다: {code}",
        code=code,
        status_code=resp.status_code,
    )
