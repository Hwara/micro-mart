# MicroMart — ERD 설계 문서

> 최종 확정일: 2026-05-05
> 설계 기준: MSA Database per Service 원칙
> 서비스 간 물리적 FK 없음 — 논리적 ID 참조만 사용

---

## 설계 원칙

| 원칙 | 내용 |
| ------ | ------ |
| DB 분리 | 서비스마다 독립 PostgreSQL 인스턴스 (`user-db`, `product-db`, `order-db`, `payment-db`) |
| 서비스 간 참조 | 물리적 FK 금지 — `user_id`, `product_id` 등 ID 값만 보관, 일관성은 HTTP 호출로 관리 |
| PK 타입 | 모든 테이블 `BigInteger` + `autoincrement=True` |
| Timestamp | `created_at` → `server_default=func.now()`, `updated_at` → `onupdate=func.now()` (DB 서버 시간 기준, NTP drift 방지) |
| 소프트 삭제 | 물리 삭제 대신 `is_active = False` (주문 이력 보존) |
| Status 타입 | Python `str + enum.Enum` 다중 상속 → SQLAlchemy `String` 컬럼에 저장 (타입 안전성 확보) |

---

## Enum 정의

모든 status 필드는 각 서비스의 `models.py` 상단에 아래 Enum을 정의한다.

```python
import enum

# order-service/app/models.py
class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"                       # 주문 요청됨 (초기 상태)
    STOCK_DEDUCTED = "STOCK_DEDUCTED"         # 재고 차감 완료
    PAYMENT_REQUESTED = "PAYMENT_REQUESTED"   # 결제 요청 중
    COMPLETED = "COMPLETED"                   # 결제 완료, 주문 확정
    FAILED = "FAILED"                         # 최종 실패 (보상 트랜잭션 완료 후)
    CANCELLED = "CANCELLED"                   # 사용자 직접 취소

class SagaStatus(str, enum.Enum):
    STARTED = "STARTED"                               # Saga 시작
    STOCK_DEDUCTED = "STOCK_DEDUCTED"                 # ① 재고 차감 성공
    PAYMENT_REQUESTED = "PAYMENT_REQUESTED"           # ② 결제 요청 완료
    COMPLETED = "COMPLETED"                           # ③ 전체 흐름 완료
    STOCK_ROLLBACK_NEEDED = "STOCK_ROLLBACK_NEEDED"   # 결제 실패 → 재고 롤백 필요
    STOCK_ROLLED_BACK = "STOCK_ROLLED_BACK"           # 재고 롤백 완료
    FAILED = "FAILED"                                 # 복구 불가 최종 실패

# payment-service/app/models.py
class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"       # 결제 요청 접수
    APPROVED = "APPROVED"     # 결제 승인
    REJECTED = "REJECTED"     # 결제 거절 (Chaos Mode 포함)
    REFUNDED = "REFUNDED"     # 환불 완료

class RefundStatus(str, enum.Enum):
    PENDING = "PENDING"       # 환불 요청 접수
    COMPLETED = "COMPLETED"   # 환불 완료
    FAILED = "FAILED"         # 환불 실패
```

> ⚠️ order-service와 payment-service에서는 SQLite 테스트 환경의 BigInteger autoincrement 미지원 문제를 해결하기 위해
> `BigIntegerType` 커스텀 TypeDecorator를 사용한다.
> PostgreSQL에서는 `BigInteger`로, SQLite(테스트)에서는 `Integer`로 자동 분기된다.

---

## user-db (user-service)

### `users` 테이블

| 컬럼 | 타입 | 제약 | 설명 |
| ------ | ------ | ------ | ------ |
| `id` | BigInteger | PK, AI | |
| `email` | String | UNIQUE, NOT NULL, INDEX | 로그인 식별자 |
| `hashed_password` | String | NOT NULL | bcrypt 해시 |
| `role` | String | NOT NULL, DEFAULT `'customer'` | `'customer'` \| `'admin'` |
| `token_version` | Integer | NOT NULL, DEFAULT `0` | 강제 로그아웃용. 비밀번호 변경·계정 차단 시 +1 → 이전 Refresh Token 전체 무효화 |
| `is_active` | Boolean | NOT NULL, DEFAULT `true` | 소프트 삭제 |
| `created_at` | DateTime(tz) | NOT NULL, server_default | |
| `updated_at` | DateTime(tz) | NOT NULL, onupdate | |

설계 결정 이유

- `token_version`을 Redis가 아닌 DB에 보관하는 이유: Redis는 휘발성이므로 재시작 시 버전 정보가 소실되어 강제 로그아웃이 우회될 수 있음. DB에 영속화하여 신뢰성 확보.

---

## product-db (product-service)

### `products` 테이블

| 컬럼 | 타입 | 제약 | 설명 |
| ------ | ------ | ------ | ------ |
| `id` | BigInteger | PK, AI | |
| `name` | String(200) | NOT NULL, INDEX | |
| `description` | Text | NULLABLE | |
| `price` | Integer | NOT NULL | 원단위 정수 (부동소수점 금액 오차 방지) |
| `stock` | Integer | NOT NULL, DEFAULT `0`, CHECK(`stock >= 0`) | DB 레벨 음수 재고 방지 |
| `version` | Integer | NOT NULL, DEFAULT `1` | 낙관적 잠금용. 재고 차감마다 +1. `WHERE version = :expected` 충돌 감지 → `409 VERSION_CONFLICT` |
| `is_active` | Boolean | NOT NULL, DEFAULT `true` | 소프트 삭제. 물리 삭제 시 order_items의 product_id 참조가 끊기므로 금지 |
| `created_at` | DateTime(tz) | NOT NULL, server_default | |
| `updated_at` | DateTime(tz) | NOT NULL, onupdate | |

설계 결정 이유

- `price`를 Integer(원단위)로 저장하는 이유: Float/Decimal의 부동소수점 오차가 금액 계산 시 실제 버그로 이어짐. 원단위 정수로 저장하고 표시 시 변환하는 것이 현업 표준.
- 낙관적 잠금 vs 비관적 잠금: 고트래픽 재고 차감에서 `SELECT FOR UPDATE`(비관적 잠금)는 락 경합으로 처리량이 급락함. 낙관적 잠금은 충돌 시 재시도 비용이 있지만 평균 처리량이 높음.

---

## order-db (order-service)

### `orders` 테이블

| 컬럼 | 타입 | 제약 | 설명 |
|  ------ | ------ | ------ | ------ |
| `id` | BigInteger | PK, AI | |
| `user_id` | BigInteger | NOT NULL, INDEX | user-service `users.id` 논리적 참조 |
| `status` | String(OrderStatus) | NOT NULL | 주문 상태. Enum 값만 허용 |
| `total_amount` | Integer | NOT NULL | 주문 시점 총액 스냅샷 (원단위). 이후 상품 가격 변경에 영향받지 않음 |
| `payment_id` | BigInteger | NULLABLE | payment-service `payments.id` 논리적 참조. 결제 완료 후 기입 |
| `failure_reason` | String(200) | NULLABLE | 실패 원인 분류 문자열. 관찰성(Loki) 메트릭 레이블용 |
| `saga_status` | String(SagaStatus) | NOT NULL, DEFAULT `'STARTED'` | Orchestration Saga 상태 추적. 보상 트랜잭션 판단 근거 |
| `stock_deducted` | Boolean | NOT NULL, DEFAULT `false` | 재고 차감 완료 여부. 결제 실패 시 보상 트랜잭션(재고 복구) 실행 여부 판단 |
| `created_at` | DateTime(tz) | NOT NULL, server_default | |
| `updated_at` | DateTime(tz) | NOT NULL, onupdate | |

설계 결정 이유

- `saga_status` + `stock_deducted` 분리 이유: 서버 재시작, 네트워크 단절 등 **장애 복구 시 어느 단계까지 진행됐는지** DB만 보고 판단하기 위함. 장애 복구 배치 잡이 `saga_status = 'STOCK_ROLLBACK_NEEDED'`인 행을 스캔하여 보상 트랜잭션을 재실행할 수 있음.

### `order_items` 테이블

| 컬럼 | 타입 | 제약 | 설명 |
| ------ | ------ | ------ | ------ |
| `id` | BigInteger | PK, AI | |
| `order_id` | BigInteger | NOT NULL, INDEX, **FK → orders.id** | 동일 DB 내 물리적 FK 허용 |
| `product_id` | BigInteger | NOT NULL | product-service `products.id` 논리적 참조 |
| `product_name` | String(200) | NOT NULL | **주문 시점 상품명 스냅샷**. 이후 상품명 변경·삭제에 영향받지 않음 |
| `unit_price` | Integer | NOT NULL | **주문 시점 단가 스냅샷**. 정산·환불 기준가 |
| `quantity` | Integer | NOT NULL, CHECK(`quantity > 0`) | 단건 최대 100개 제한 (schemas.py 검증) |
| `discount_amount` | Integer | NOT NULL, DEFAULT `0` | 쿠폰·프로모션 할인액. 향후 기능 확장 대비 |
| `subtotal` | Integer | NOT NULL | `unit_price * quantity - discount_amount`. 파생값이지만 할인 적용 후 실결제액이 수식과 다를 수 있어 명시적 저장 |
| `created_at` | DateTime(tz) | NOT NULL, server_default | |

> ⚠️ `order_items`에는 `updated_at`이 없다. 주문 생성 후 변경되지 않는 **불변 데이터**이므로 의도적으로 제외.
> 실수로 수정이 발생해도 감지 불가 → 불변성 강제 효과.

설계 결정 이유

- 스냅샷 저장 이유: MSA에서 product-service DB는 order-service에서 직접 조회 불가. 상품이 삭제되거나 가격이 변경되어도 주문 당시 데이터로 **CS 처리, 정산, 환불**이 가능해야 함.
- 중복 product_id 입력 차단: `OrderCreateRequest.check_duplicate_product_ids` validator로 동일 요청 내 중복 상품 ID를 `422`로 차단. 중복 시 총액 계산 오류 및 이중 재고 차감 방지.

---

## payment-db (payment-service)

### `payments` 테이블

| 컬럼 | 타입 | 제약 | 설명 |
| ------ | ------ | ------ | ------ |
| `id` | BigInteger | PK, AI | |
| `order_id` | BigInteger | NOT NULL, **UNIQUE**, INDEX | order-service `orders.id` 논리적 참조. UNIQUE로 중복 결제 DB 레벨 방지 |
| `user_id` | BigInteger | NOT NULL, INDEX | user-service `users.id` 논리적 참조 |
| `amount` | Integer | NOT NULL | 결제 금액 (원단위) |
| `status` | String(PaymentStatus) | NOT NULL, DEFAULT `'PENDING'` | 결제 상태 |
| `pg_transaction_id` | String(100) | NULLABLE | 가상 PG 트랜잭션 ID. 실 PG 연동 시 외부 트랜잭션 추적용 |
| `failure_reason` | String(200) | NULLABLE | Chaos Mode 포함 실패 원인 |
| `processed_at` | DateTime(tz) | NULLABLE | 실제 결제 승인/거절 처리 시각. `created_at`과 구분하여 결제 레이턴시 측정 |
| `created_at` | DateTime(tz) | NOT NULL, server_default | |
| `updated_at` | DateTime(tz) | NOT NULL, onupdate | |

설계 결정 이유

- `order_id UNIQUE` 이유: 네트워크 재시도로 인한 중복 결제 요청이 들어와도 DB 레벨에서 멱등성을 강제. PG 시뮬레이션이지만 실 PG 연동 시나리오와 동일한 방어 구조 적용.
- `processed_at` 분리 이유: `created_at`은 결제 레코드 생성 시각, `processed_at`은 실제 PG 응답 수신 시각. 두 값의 차이가 **결제 레이턴시** 관찰성 지표가 됨.
- `PENDING` 선생성 이유: 처리 전 레코드를 먼저 생성해 서버 크래시 시에도 요청 접수 기록이 남도록 함.

### `refunds` 테이블

| 컬럼 | 타입 | 제약 | 설명 |
| ------ | ------ | ------ | ------ |
| `id` | BigInteger | PK, AI | |
| `payment_id` | BigInteger | NOT NULL, INDEX, **FK → payments.id** | 동일 DB 내 물리적 FK 허용 |
| `amount` | Integer | NOT NULL | 환불 금액. 부분 환불 지원 (`amount ≤ payments.amount`) |
| `reason` | String(500) | NULLABLE | 환불 사유 |
| `status` | String(RefundStatus) | NOT NULL, DEFAULT `'PENDING'` | 환불 처리 상태 |
| `processed_at` | DateTime(tz) | NULLABLE | 실제 환불 처리 시각 |
| `created_at` | DateTime(tz) | NOT NULL, server_default | |

> ⚠️ `refunds`에는 `updated_at`이 없다. 환불 처리는 `processed_at`으로 완료 시각을 기록하며, 생성 후 수정되지 않는 이력 데이터다.

---

## 서비스 간 논리적 참조 관계

```text
[user-db]        [order-db]                          [product-db]   [payment-db]
─────────        ─────────────────────────           ────────────   ──────────────────
users            orders         order_items          products       payments    refunds
  id ◄────────── user_id          product_id ──────► id              user_id ──► users.id
                 id ◄──(1:N)───── order_id                           order_id(UNIQUE)
                 id ────────────────────────────────────────────►    id ◄─(1:N)─ payment_id
                 payment_id ◄──────────────────────────────────── id

── 실선 : 물리적 FK (동일 DB 내)
──► 화살표 : 논리적 참조 (서비스 간, HTTP 호출로 일관성 관리)
```

---

## 주문 생성 Saga 상태 전이

```text
[orders.saga_status 전이도]

STARTED
  │
  ├─ 재고 차감 성공 ──► STOCK_DEDUCTED  (stock_deducted = true)
  │                          │
  │                    결제 요청 ──► PAYMENT_REQUESTED
  │                                      │
  │                          결제 성공 ──► COMPLETED
  │                          결제 실패 ──► STOCK_ROLLBACK_NEEDED
  │                                              │
  │                               재고 롤백 완료 ──► STOCK_ROLLED_BACK
  │                                                        │
  ├─ 재고 차감 실패 ──► FAILED                        ──► FAILED
```

---

## 변경 이력

| 날짜 | 변경 내용 |
| ------ | ----------- |
| 2026-05-03 | 최초 ERD 확정 (user, product, order, payment, refunds) |
| 2026-05-04 | payment-service 구현 완료 반영: `BigIntegerType` 커스텀 타입 추가 주석, `payments.status` DEFAULT `'PENDING'` 명시, `refunds.updated_at` 부재 설계 의도 추가, `PENDING` 선생성 설계 의도 추가 |
| 2026-05-05 | order-service 구현 완료 반영: `BigIntegerType` 적용 범위를 order-service까지 확장 명시, `order_items.quantity` 단건 최대 100개 제한 추가, 중복 product_id 차단 설계 의도 추가 |
