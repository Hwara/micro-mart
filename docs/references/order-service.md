# order-service Reference

## 1. 문서 목적

이 문서는 `order-service`의 주문 생성 Saga, 재고/결제 서비스 호출, NATS 이벤트 발행을 학습하기 위한 서비스별 레퍼런스다.

기준 문서는 다음처럼 사용한다.

- `docs/ERD_structure.md`: `orders`, `order_items`, `OrderStatus`, `SagaStatus`
- `docs/service_function_definition.md`: 주문 API와 product/payment 호출 계약
- `docs/micromart_design.md`: 주문 생성 데이터 플로우와 관찰성 시나리오
- `docs/dev_convention.md`: Saga, 보상 트랜잭션, 내부 호출 규칙

이 문서를 읽고 나면 왜 주문 서비스가 오케스트레이터인지, 어떤 상태를 DB에 남기는지, 실패 시 어떤 보상을 시도하는지 설명할 수 있어야 한다.

## 2. 서비스 역할과 경계

`order-service`는 주문 생성과 조회를 담당하는 Saga 오케스트레이터다. 상품 정보 조회, 주문/주문항목 저장, 재고 차감, 결제 요청, 실패 시 재고 복구, 주문 완료 이벤트 발행을 조율한다.

하지 않는 일은 상품 재고의 직접 변경, 결제 승인 판단, 알림 발송이다. 각각 product-service, payment-service, notification-service에 위임한다.

외부 API는 gateway가 주입한 `X-User-ID`를 신뢰한다. 내부 호출을 받을 전용 API는 현재 없지만, product/payment 호출 시 `X-Internal-Token`을 사용한다.

## 3. 빠른 구조 지도

```text
services/order-service/
├── app/
│   ├── main.py                      # FastAPI 앱, NATS 연결, health
│   ├── config.py                    # DB, 내부토큰, 하위 서비스 URL, NATS 설정
│   ├── database.py                  # SQLAlchemy async DB
│   ├── dependencies.py              # X-User-ID, role, internal token 의존성
│   ├── models.py                    # Order, OrderItem, 상태 Enum, BigIntegerType
│   ├── schemas.py                   # 주문 요청/응답, 중복 product_id 검증
│   ├── nats_client.py               # NATS client 싱글턴
│   ├── routes/orders.py             # HTTP 경계
│   └── services/
│       ├── http_clients.py          # product/payment HTTP 호출과 에러 래핑
│       └── order_service.py         # Saga 오케스트레이션
└── tests/
    ├── test_orders_api.py
    └── test_order_service.py
```

라우터는 사용자 헤더, 페이지네이션, 응답 모델을 처리한다. Saga 흐름과 상태 전이는 `order_service.py`, 하위 서비스 timeout/에러 매핑은 `http_clients.py`가 담당한다.

## 4. 핵심 흐름

주문 생성은 먼저 product-service에서 상품 정보를 조회한다. 존재하지 않거나 비활성 상품이면 Order를 저장하기 전에 실패한다.

상품 정보가 유효하면 `Order(PENDING/STARTED)`와 `OrderItem` 스냅샷을 저장한다. 상품명, 단가, 소계는 주문 시점 값을 저장한다.

재고 차감은 상품별로 순차 처리한다. 각 차감은 product-service 내부 API에 `expected_version`과 함께 요청된다. 실패하면 이미 차감된 항목만 best-effort로 복구하고 주문을 `FAILED`로 저장한다.

재고 차감이 모두 성공하면 `STOCK_DEDUCTED`와 `stock_deducted=True`를 커밋한다. 이후 결제를 요청하고, 결제 실패 시 `STOCK_ROLLBACK_NEEDED`를 먼저 커밋한 뒤 재고 복구를 시도한다.

결제 성공 시 `COMPLETED`, `payment_id`를 저장하고 NATS `order.completed` 이벤트를 best-effort로 발행한다. 이벤트 발행 실패는 주문 완료를 되돌리지 않는다.

## 5. 핵심 설계 결정

| 결정 | 선택 | 대안 | 선택 이유 | 트레이드오프 |
| --- | --- | --- | --- | --- |
| 분산 처리 | Orchestration Saga | 2PC, Choreography | 학습용으로 흐름과 상태를 한 서비스에서 명확히 추적 | order-service에 조율 책임이 집중 |
| 재고 차감 | 순차 처리 | 병렬 처리 | 부분 성공 시 롤백 대상 추적이 단순 | 여러 상품 주문은 지연이 늘 수 있음 |
| 실패 복구 | `STOCK_ROLLBACK_NEEDED` 선커밋 | 메모리에서만 복구 상태 보관 | 서버 크래시 후에도 DB를 보고 복구 가능 | 복구 배치가 아직 없으면 상태가 남을 수 있음 |
| 이벤트 발행 | NATS best-effort | Outbox 패턴 | 현재 범위에서 단순하고 관찰성 실습에 충분 | 발행 실패 시 알림 유실 가능 |
| 조회 로딩 | `selectinload(Order.items)` | lazy load | async SQLAlchemy의 `MissingGreenlet` 방지 | 명시적 eager loading 필요 |
| IDOR 방어 | `order.user_id == X-User-ID` 확인 | order_id만 조회 | 타인 주문 접근 차단 | gateway 헤더 신뢰가 필수 |

## 6. 데이터와 계약

`orders`는 `user_id`, `status`, `total_amount`, `payment_id`, `failure_reason`, `saga_status`, `stock_deducted`를 가진다. `order_items`는 `product_id`, `product_name`, `unit_price`, `quantity`, `discount_amount`, `subtotal`을 가진 불변 스냅샷이다.

엔드포인트 요약:

| Method | Path | 목적 | 인증 |
| --- | --- | --- | --- |
| POST | `/orders` | 주문 생성 Saga 실행 | `X-User-ID` |
| GET | `/orders` | 내 주문 목록 | `X-User-ID` |
| GET | `/orders/{order_id}` | 내 주문 상세 | `X-User-ID` |
| GET | `/health` | NATS 연결 상태 포함 health | 없음 |

하위 호출:

| 대상 | 호출 |
| --- | --- |
| product-service | `GET /products/{id}` |
| product-service | `POST /products/{id}/deduct-stock` + `X-Internal-Token` |
| product-service | `POST /products/{id}/restore-stock` + `X-Internal-Token` |
| payment-service | `POST /payments` + `X-Internal-Token` |
| NATS | `order.completed` publish |

주요 환경변수는 `DATABASE_URL`, `INTERNAL_SERVICE_TOKEN`, `PRODUCT_SERVICE_URL`, `PAYMENT_SERVICE_URL`, `MAX_OPTIMISTIC_RETRY`, `HTTP_TIMEOUT_SECONDS`, `NATS_URL`, `NATS_CONNECT_TIMEOUT_SECONDS`다.

## 7. 관찰성

주요 로그 이벤트는 상품 조회 실패, 주문 생성 완료, 재고 차감 실패, 재고 차감 완료, 결제 실패, 주문 완료, NATS 이벤트 발행 성공/실패다.

메트릭:

| 이름 | 의미 |
| --- | --- |
| `order_created_total` | 주문 생성 요청 수 |
| `order_completed_total` | 주문 완료 수 |
| `order_failed_total` | 주문 실패 수 |
| `order_amount_krw` | 주문 금액 분포 |
| `saga_stock_rollback_total` | 재고 롤백 보상 트랜잭션 수 |

`order_failed_total`은 낮은 카디널리티의 `reason` 레이블을 사용한다. `order_id`, `user_id`, `payment_id`는 로그 필드로만 사용한다.

## 8. 테스트와 검증

대표 검증 명령:

```powershell
pytest services/order-service/tests -q
```

검증 포인트는 주문 생성 happy path, 중복 product_id 422, 상품 조회 실패, 재고 부족/충돌, 결제 거절, 재고 롤백, 타인 주문 접근 403, 목록/상세 조회, NATS 발행 실패 시 주문 완료 유지다.

## 9. 자주 발생한 오류와 트러블슈팅

| 증상 | 원인 | 해결 | 재발 방지 |
| --- | --- | --- | --- |
| `MissingGreenlet` | response 변환 중 lazy load 발생 | `selectinload(Order.items)`로 미리 로드 | 상세 응답 테스트 유지 |
| `STOCK_ROLLBACK_NEEDED` 상태 잔류 | 재고 복구 실패 또는 중간 장애 | product-service 복구 API와 로그 확인 | 향후 복구 배치/알림 필요 |
| `ORDER_STOCK_CONFLICT` | 낙관적 잠금 재시도 초과 | 사용자에게 재시도 안내 | `MAX_OPTIMISTIC_RETRY` 과도 증가 금지 |
| NATS 연결 실패 | 브로커 미기동/URL 오류 | `/health.nats_connected`와 로그 확인 | 이벤트 발행 best-effort 전제 문서화 |
| 타인 주문 조회 가능 | user_id 검증 누락 | `order.user_id`와 헤더 user_id 비교 | IDOR 테스트 유지 |

## 10. 왜 이 설계인가

주문 생성은 MicroMart에서 가장 많은 장애 경로가 만나는 흐름이다. 상품 조회, 재고 차감, 결제, 이벤트 발행이 모두 성공해야 happy path가 완성된다. 그래서 order-service는 단순 CRUD가 아니라 오케스트레이터다.

분산 트랜잭션 대신 Saga를 선택한 이유는 각 서비스 DB를 독립적으로 유지하기 위해서다. 대신 실패 중간 상태를 DB에 남기고, 보상 트랜잭션으로 되돌릴 수 있는 구조를 만든다.

이 설계의 핵심은 “실패를 숨기지 않고 상태로 남긴다”이다. `saga_status`, `stock_deducted`, `failure_reason`은 운영자가 장애 이후 무엇을 복구해야 하는지 판단하게 해준다. NATS 발행을 best-effort로 둔 것도 주문 정합성과 알림 전달을 분리해, 핵심 거래가 부가 이벤트 실패에 끌려가지 않게 하기 위한 선택이다.
