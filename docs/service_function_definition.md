# MicroMart — 서비스 기능 정의 문서

> 최종 갱신일: 2026-05-04
> 목적: 서비스별 책임, 엔드포인트, 내부 동작, 서비스 간 호출 계약을 구현 전에 명확히 고정하기 위한 기능 정의 문서

---

## 1. 문서 목적

이 문서는 MicroMart의 각 서비스가 **무엇을 책임지고**, **어떤 입력을 받아**, **어떤 방식으로 처리하고**, **다른 서비스와 어떤 계약으로 통신하는지**를 정의한다.

다음과 같이 각 문서의 역할을 구분한다.

| 문서 | 역할 |
| -------------------------------- | --------------------------------------- |
| `ERD_structure.md` | DB 스키마, 제약 조건, 상태 전이, 설계 이유 |
| `service_function_definition.md` | 서비스별 기능 정의, 엔드포인트 계약, 호출 흐름, 실패 시 처리 기준 |
| `micromart_design.md` | 아키텍처 개요, 서비스별 역할 개요, 인증 설계 |
| `dev_convention.md` | 코드 작성 컨벤션, 파일 구조, 서비스 간 호출 규칙, 보안 규칙 |

---

## 2. 전체 서비스 책임

| 서비스 | 핵심 책임 | 저장소 |
| -------- | ----------- | -------- |
| `api-gateway` | JWT 검증, 라우팅, Rate Limiting, 요청 진입 제어 | 없음 |
| `user-service` | 회원가입, 로그인, JWT 발급, Refresh Token Rotation, 로그아웃 | PostgreSQL, Redis |
| `product-service` | 상품 조회/등록/수정/삭제, 캐시 관리, 재고 차감 | PostgreSQL, Redis |
| `order-service` | 주문 생성/조회, Saga 오케스트레이션, 재고 차감 및 결제 흐름 조정 | PostgreSQL |
| `payment-service` | 결제 승인/거절 시뮬레이션, Chaos Mode, 환불 처리 | PostgreSQL |
| `notification-service` | 주문 완료 이벤트 소비, 알림 발송 시뮬레이션 | 없음 |

---

## 3. 구현 완료 서비스 기능 정의

### 3.1 user-service

#### 역할

`user-service`는 사용자 인증과 세션 수명주기를 담당한다. 회원가입, 로그인, Access Token 발급, Refresh Token Rotation, 로그아웃, 공개키 제공을 책임진다.

#### 저장소

- PostgreSQL: 사용자 영속 데이터 저장 (`users`)
- Redis: 기기별 Refresh Token 저장, 세션 무효화 보조 저장소

#### 주요 데이터

- `users` 테이블은 `email`, `hashed_password`, `role`, `token_version`, `is_active`를 관리한다. `token_version`은 비밀번호 변경이나 강제 차단 시 이전 토큰을 전체 무효화하기 위한 필드다.

#### 엔드포인트

- `POST /auth/register`
  - 기능: 회원가입
  - 입력: 이메일, 비밀번호 등 사용자 생성 정보
  - 처리:
    1. 이메일 중복 검사
    2. 비밀번호 해시 저장
    3. 기본 역할은 `customer`
    4. 사용자 생성 후 응답 반환
  - 실패:
    - 중복 이메일
    - 유효성 검증 실패

- `POST /auth/login`
  - 기능: 로그인
  - 처리:
    1. 이메일로 사용자 조회
    2. 비밀번호 검증
    3. RS256 Access Token 발급
    4. Refresh Token 발급
    5. Redis에 `refresh:user:{id}:{device}` 형태로 저장
  - 결과: Access Token + Refresh Token 반환

- `POST /auth/refresh`
  - 기능: Access Token 재발급
  - 처리:
    1. 전달받은 Refresh Token 검증
    2. Redis 저장값 비교
    3. Rotation 적용, 기존 토큰 폐기 후 신규 Refresh Token 재저장
    4. 새 Access Token 발급
  - 실패:
    - 만료/불일치/재사용 감지 시 세션 무효화

- `POST /auth/logout`
  - 기능: 로그아웃
  - 처리:
    1. 현재 기기 세션의 Refresh Token 키 삭제
    2. 이후 재발급 차단

- `GET /auth/jwks`
  - 기능: RS256 공개키 제공
  - 사용처: `api-gateway`의 JWT 로컬 검증 캐시

#### 설계 의도

- 인증은 user-service에 집중시키고 다른 서비스는 JWT를 직접 검증하지 않는다.
- 공개키 기반 검증으로 gateway가 인증 병목이 되지 않게 한다.
- `token_version`을 통해 강제 로그아웃과 계정 차단을 안전하게 처리한다.

---

### 3.2 product-service

#### 역할

`product-service`는 상품 카탈로그와 재고를 담당한다. 공개 조회 API와 관리자용 CRUD, 그리고 `order-service`가 호출하는 내부 재고 차감 API를 제공한다.

#### 저장소

- PostgreSQL: 상품 원본 데이터 저장 (`products`)
- Redis: 상품 상세 캐시, Cache-Aside 패턴 적용

#### 주요 데이터

- `products` 테이블은 `name`, `description`, `price`, `stock`, `version`, `is_active`를 관리한다.
- `version`은 낙관적 잠금용이며 재고 차감 시 동시성 충돌을 감지한다.
- `stock >= 0`은 DB 제약으로 강제한다.

#### 엔드포인트

- `GET /products`
  - 기능: 상품 목록 조회
  - 지원: 페이지네이션, `active_only` 필터

- `GET /products/{id}`
  - 기능: 상품 상세 조회
  - 처리:
    1. Redis 캐시 조회
    2. miss면 DB 조회
    3. 응답 직렬화 후 캐시 저장
  - 목적: 조회 트래픽 절감

- `POST /products`
  - 기능: 상품 등록
  - 권한: admin 전용

- `PUT /products/{id}`
  - 기능: 상품 수정
  - 처리: DB 업데이트 후 캐시 무효화
  - 권한: admin 전용

- `DELETE /products/{id}`
  - 기능: 상품 삭제
  - 실제 동작: 물리 삭제가 아니라 `is_active = false` 처리
  - 권한: admin 전용

- `POST /products/{id}/deduct-stock`
  - 기능: 주문용 내부 재고 차감
  - 인증: `X-Internal-Token`
  - 처리:
    1. 현재 상품 조회
    2. 재고 수량 확인
    3. `version` 기반 낙관적 잠금 업데이트
    4. 성공 시 `version` 증가
  - 실패:
    - 재고 부족
    - 버전 충돌 시 `409 VERSION_CONFLICT`

#### 설계 의도

- 상품 조회와 주문용 재고 차감을 한 서비스에 두어 재고 정합성을 한 곳에서 유지한다.
- 삭제는 소프트 삭제로 처리해 주문 이력과 충돌하지 않게 한다.
- 고부하 환경에서 락 경합을 줄이기 위해 낙관적 잠금을 사용한다.

---

### 3.3 payment-service

#### 역할

`payment-service`는 외부 PG를 흉내 내는 결제 시뮬레이터다. 결제 승인/거절, 지연, 장애 주입, 환불을 담당한다. 모든 엔드포인트는 `X-Internal-Token` 인증이 필수인 내부 전용 API다.

#### 저장소

- PostgreSQL: `payments`, `refunds`

#### 주요 데이터

- `payments.order_id`는 UNIQUE여야 한다 — DB 레벨 중복 결제 멱등성 보장.
- `processed_at`은 실제 처리 완료 시점을 기록한다 (`created_at`과 차이 = 결제 레이턴시).
- `refunds`는 부분 환불 확장을 고려해 별도 테이블로 분리한다.

#### 엔드포인트

- `POST /payments`
  - 기능: 주문 결제 요청
  - 인증: `X-Internal-Token` 필수
  - 입력: `order_id`, `user_id`, `amount`
  - 처리:
    1. 중복 결제 앱 레벨 선검사 (`order_id` 조회 → `409 DUPLICATE_PAYMENT`)
    2. Chaos Mode 지연 적용 (`CHAOS_LATENCY_MS`)
    3. `PENDING` 상태로 Payment 레코드 생성 및 `flush` (DB UNIQUE 제약 이중 차단)
    4. Chaos Mode 실패율 평가 (`CHAOS_FAILURE_RATE`)
    5. Chaos DB 슬로우쿼리 시뮬레이션 (`CHAOS_DB_SLOWQUERY`)
    6. 승인: `APPROVED` + `pg_transaction_id` 생성, `processed_at` 기록
    7. 거절: `REJECTED` + `failure_reason=CHAOS_FAILURE`, `402` 반환
  - 실패 응답:
    - `409 DUPLICATE_PAYMENT` — 중복 결제
    - `402 PAYMENT_REJECTED` — Chaos Mode 거절

- `GET /payments/{payment_id}`
  - 기능: 결제 상태 조회
  - 인증: `X-Internal-Token` 필수
  - 실패: `404` — 결제 내역 없음

- `POST /payments/{payment_id}/refunds`
  - 기능: 환불 요청 (부분 환불 지원)
  - 인증: `X-Internal-Token` 필수
  - 입력: `amount`, `reason`
  - 처리:
    1. 결제 내역 조회
    2. `APPROVED` 상태인지 확인 (`PENDING`/`REJECTED`/`REFUNDED`는 환불 불가)
    3. 기존 `COMPLETED` 환불 합산 후 잔여 환불 가능 금액 계산
    4. 환불 금액 초과 검증
    5. `Refund` 레코드 생성 (`status=COMPLETED`, `processed_at` 즉시 기록)
    6. 전액 환불 시 `payments.status`를 `REFUNDED`로 변경
  - 실패 응답:
    - `400 REFUND_NOT_ALLOWED` — 환불 불가 상태
    - `422 REFUND_AMOUNT_EXCEEDED` — 환불 금액 초과

- `GET /health`
  - 기능: 헬스체크 (k8s liveness probe용)
  - 응답: 서비스 상태 + 현재 Chaos Mode 설정값 포함

#### 관찰성 메트릭

| 메트릭 이름 | 타입 | 설명 |
| ----------- | ---- | ---- |
| `payment_total` | Counter | 결제 요청 총 횟수 |
| `payment_approved_total` | Counter | 결제 승인 횟수 |
| `payment_rejected_total` | Counter | 결제 거절 횟수 (`reason` 레이블) |
| `payment_amount_krw` | Histogram | 결제 금액 분포 (원단위) |
| `payment_processing_latency_ms` | Histogram | 결제 처리 레이턴시 (ms) |
| `refund_total` | Counter | 환불 요청 총 횟수 |

#### Chaos Mode

- `CHAOS_FAILURE_RATE` — 0.0~1.0 (0.3 = 30% 확률 거절)
- `CHAOS_LATENCY_MS` — 결제 처리 전 강제 지연 (밀리초), `asyncio.sleep`으로 비동기 처리
- `CHAOS_DB_SLOWQUERY` — DB 슬로우쿼리 시뮬레이션 (`random.uniform(1.0, 3.0)` 지연)

#### 설계 의도

- 실제 PG 연동 전 단계에서 결제 실패율, 레이턴시, 장애 상황을 관찰성 실습에 활용한다.
- `order_id UNIQUE`로 중복 결제를 DB 레벨에서 차단하고, 앱 레벨 선검사로 에러 응답 코드를 명확히 한다.
- `processed_at`을 `created_at`과 분리해 결제 레이턴시를 메트릭으로 관찰 가능하게 한다.
- `PENDING` 상태로 레코드를 선생성해, 서버 크래시 시에도 요청 접수 기록이 남도록 한다.
- Redis를 사용하지 않아 `database.py`에 Redis 설정이 없다 (dev_convention.md 준수).

---

## 4. 예정 서비스 기능 정의

### 4.1 api-gateway

#### 역할

- 외부 클라이언트의 단일 진입점
- JWT 로컬 검증
- 서비스별 라우팅
- Rate Limiting
- 요청/응답 로깅

#### 핵심 동작

1. `Authorization` 헤더에서 JWT 추출
2. user-service가 제공한 JWKS 기반 서명 검증
3. 성공 시 `X-User-ID`, `X-User-Role` 헤더 추가
4. 하위 서비스로 프록시

#### 비기능 요구

- 하위 서비스는 JWT를 직접 검증하지 않는다.
- 인증 실패와 권한 실패를 gateway에서 선제 차단한다.

---

### 4.2 order-service

#### 역할

`order-service`는 시스템의 오케스트레이터다. 주문 생성, 주문 조회, 재고 차감 요청, 결제 요청, 주문 저장, 이벤트 발행을 한 흐름으로 조율한다.

#### 저장소

- PostgreSQL: `orders`, `order_items`

#### 핵심 데이터

- `orders`: 사용자 ID, 총액, 주문 상태, Saga 상태, 실패 원인, 결제 ID
- `order_items`: 상품 ID, 상품명 스냅샷, 단가 스냅샷, 수량, 할인액, 소계

#### 예상 엔드포인트

- `POST /orders`
  - 기능: 주문 생성
  - 입력: 상품 목록, 수량
  - 인증: gateway가 전달한 `X-User-ID`
  - 처리:
    1. 주문 요청 검증
    2. 상품별 재고 차감 요청
    3. 결제 요청
    4. 성공 시 주문/주문항목 저장
    5. `order.completed` 이벤트 발행

- `GET /orders`
  - 기능: 내 주문 목록 조회

- `GET /orders/{id}`
  - 기능: 주문 상세 조회

#### Saga 오케스트레이션

- 상태 전이:
  - `STARTED`
  - `STOCK_DEDUCTED`
  - `PAYMENT_REQUESTED`
  - `COMPLETED`
- 결제 실패 시:
  - `STOCK_ROLLBACK_NEEDED`
  - `STOCK_ROLLED_BACK`
  - `FAILED`

#### 실패 처리 원칙

- 재고 차감 실패 시 즉시 주문 실패
- 결제 실패 시 재고 롤백 시도
- 롤백 필요 여부는 `stock_deducted`와 `saga_status`로 판단

#### 설계 의도

- 분산 트랜잭션 대신 Orchestration Saga를 사용해 복구 가능한 실패 흐름을 만든다.
- 상품명과 단가를 스냅샷으로 저장해 이후 상품 변경과 무관하게 주문 이력을 보존한다.

---

### 4.3 notification-service

#### 역할

- NATS에서 `order.completed` 이벤트 소비
- 이메일/SMS 발송 시뮬레이션
- 성공/실패 로그 기록

#### 특징

- DB는 두지 않는다.
- 관찰성 측면에서 소비 지연, 실패율, 적체를 중점 관찰한다.

---

## 5. 서비스 간 호출 계약

### 주문 생성 Happy Path

1. Client → `api-gateway`
2. `api-gateway` → `order-service`
3. `order-service` → `product-service` 재고 차감 (`X-Internal-Token`)
4. `order-service` → `payment-service` 결제 요청 (`X-Internal-Token`)
5. `order-service` → `order-db` 저장
6. `order-service` → NATS `order.completed`
7. `notification-service` 소비

### 주문 생성 실패 경로

- 재고 부족: 주문 즉시 실패
- 결제 실패 (`402 PAYMENT_REJECTED`): 재고 롤백 후 실패
- 롤백 미완료: Saga 상태로 남기고 후속 복구 대상 처리

### payment-service 호출 규격

```python
# order-service → payment-service
POST /payments
Headers:
  X-Internal-Token: {INTERNAL_SERVICE_TOKEN}
Body:
  { "order_id": int, "user_id": int, "amount": int }

# 성공 응답 (201)
{ "id": int, "status": "APPROVED", "pg_transaction_id": "PG-...", ... }

# 실패 응답 (402)
{ "detail": { "detail": "결제가 거절되었습니다.", "code": "PAYMENT_REJECTED" } }
```

---

## 6. 구현 우선순위

1. ⏳ `order-service` — payment/product 호출 계약 확정 후 Saga 구현
2. ⏳ `api-gateway`
3. ⏳ `notification-service`

---

## 7. 문서 운영 원칙

- 구현 완료된 서비스는 실제 코드와 문서를 함께 갱신한다.
- 예정 서비스는 엔드포인트 계약이 바뀌면 먼저 이 문서를 수정한다.
- README는 요약본, 이 문서는 구현 기준서로 유지한다.
- 코드 컨벤션 기준은 `dev_convention.md`를 따른다.
