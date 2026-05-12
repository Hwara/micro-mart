# payment-service Reference

## 1. 문서 목적

이 문서는 `payment-service`의 결제 승인/거절 시뮬레이션, Chaos Mode, 환불 설계를 학습하기 위한 서비스별 레퍼런스다.

기준 문서는 다음처럼 사용한다.

- `docs/ERD_structure.md`: `payments`, `refunds`, `PaymentStatus`, `RefundStatus`
- `docs/service_function_definition.md`: 내부 결제/환불 API 계약
- `docs/micromart_design.md`: 주문 Saga에서 결제 서비스의 위치
- `docs/dev_convention.md`: 내부 API 인증, Redis 미사용, 관찰성 규칙

이 문서를 읽고 나면 중복 결제 방지, `PENDING` 선생성, Chaos Mode 실패 경로, 부분 환불의 현재 한계를 설명할 수 있어야 한다.

## 2. 서비스 역할과 경계

`payment-service`는 외부 PG를 대체하는 결제 시뮬레이터다. 주문 결제 요청을 승인하거나 거절하고, 결제 상태 조회와 환불 요청을 처리한다.

모든 `/payments` 엔드포인트는 내부 서비스 전용이며 `X-Internal-Token`이 필수다. 외부 클라이언트가 직접 호출하는 서비스가 아니고, 사용자 JWT를 직접 검증하지 않는다.

Redis와 메시지 큐를 사용하지 않는다. 결제와 환불 기록은 PostgreSQL에만 저장한다.

## 3. 빠른 구조 지도

```text
services/payment-service/
├── app/
│   ├── main.py                         # FastAPI 앱, telemetry/logging, health
│   ├── config.py                       # DB, 내부토큰, Chaos 설정
│   ├── database.py                     # SQLAlchemy async DB
│   ├── dependencies.py                 # verify_internal_service
│   ├── models.py                       # Payment, Refund, 상태 Enum, BigIntegerType
│   ├── schemas.py                      # 결제/환불 요청 응답
│   ├── routes/payments.py              # 내부 API HTTP 경계
│   └── services/payment_service.py     # 결제/환불 상태 전이, Chaos, 메트릭
└── tests/
    ├── test_payments.py
    └── debug/test_minimal.py
```

라우터는 `X-Internal-Token` 의존성과 응답 모델을 담당한다. 중복 결제, Chaos 지연/실패, 환불 가능 금액 계산은 `payment_service.py`에 있다.

## 4. 핵심 흐름

결제 요청은 먼저 `order_id` 중복 여부를 조회한다. 중복이 있으면 `409 DUPLICATE_PAYMENT`를 반환한다. 이후 Chaos latency를 적용하고, `PENDING` Payment 레코드를 먼저 `flush()`하여 요청 접수 기록과 DB unique 제약을 확보한다.

Chaos 실패율에 걸리면 상태를 `REJECTED`로 바꾸고 `processed_at`과 `failure_reason=CHAOS_FAILURE`를 기록한 뒤 `402 PAYMENT_REJECTED`를 반환한다. 성공하면 `APPROVED`, `pg_transaction_id`, `processed_at`을 기록하고 201 응답을 반환한다.

환불은 승인된 결제(`APPROVED`)만 허용한다. 기존 완료 환불 금액을 합산해 잔여 환불 가능 금액을 계산하고, 금액 초과 시 `422 REFUND_AMOUNT_EXCEEDED`를 반환한다. 전액 환불이면 결제 상태를 `REFUNDED`로 변경한다.

## 5. 핵심 설계 결정

| 결정 | 선택 | 대안 | 선택 이유 | 트레이드오프 |
| --- | --- | --- | --- | --- |
| 중복 결제 | 앱 선검사 + `order_id UNIQUE` | 앱 검사만 | 네트워크 재시도와 동시 요청을 DB 레벨까지 방어 | 검사 중복이 있지만 에러 메시지가 명확 |
| 결제 레코드 | `PENDING` 선생성 | 승인 후 생성 | 서버 크래시가 나도 요청 접수 기록이 남음 | 거절된 결제도 DB에 남는다 |
| 장애 실습 | Chaos Mode 내장 | 별도 mock PG | 실패율/지연/슬로우쿼리를 로컬에서 바로 관찰 | 운영에서는 반드시 기본값 비활성 |
| 환불 모델 | `refunds` 별도 테이블 | `payments.refunded_amount` 단일 컬럼 | 부분 환불과 이력 누적이 가능 | 동시 부분 환불 초과 방지는 현재 범위 밖 |
| 내부 인증 | `hmac.compare_digest` 기반 token | 일반 문자열 비교 | 타이밍 공격 가능성을 낮춤 | 토큰 배포/회전 운영이 필요 |

## 6. 데이터와 계약

`payments`는 `order_id`, `user_id`, `amount`, `status`, `pg_transaction_id`, `failure_reason`, `processed_at`을 가진다. `order_id`는 unique다. `refunds`는 `payment_id`, `amount`, `reason`, `status`, `processed_at`을 가진다.

엔드포인트 요약:

| Method | Path | 목적 | 인증 |
| --- | --- | --- | --- |
| POST | `/payments` | 결제 요청 | `X-Internal-Token` |
| GET | `/payments/{payment_id}` | 결제 상태 조회 | `X-Internal-Token` |
| POST | `/payments/{payment_id}/refunds` | 환불 요청 | `X-Internal-Token` |

주요 에러 코드는 `DUPLICATE_PAYMENT`, `PAYMENT_REJECTED`, `REFUND_NOT_ALLOWED`, `REFUND_AMOUNT_EXCEEDED`다.

주요 환경변수는 `DATABASE_URL`, `INTERNAL_SERVICE_TOKEN`, `CHAOS_FAILURE_RATE`, `CHAOS_LATENCY_MS`, `CHAOS_DB_SLOWQUERY`다.

## 7. 관찰성

주요 로그 이벤트는 중복 결제 요청, DB 레벨 중복 차단, Chaos 지연, 결제 거절, 결제 승인, 환불 처리 완료다.

메트릭:

| 이름 | 의미 |
| --- | --- |
| `payment_total` | 결제 요청 수 |
| `payment_approved_total` | 결제 승인 수 |
| `payment_rejected_total` | 결제 거절 수 |
| `payment_amount_krw` | 결제 금액 분포 |
| `payment_processing_latency_ms` | 결제 처리 지연 |
| `refund_total` | 환불 요청 수 |

`payment_rejected_total`은 낮은 카디널리티의 `reason` 레이블을 사용한다. `order_id`, `user_id`, `payment_id`는 로그 필드로만 남긴다.

## 8. 테스트와 검증

대표 검증 명령:

```powershell
pytest services/payment-service/tests -q
```

검증 포인트는 내부 토큰 누락 차단, 결제 승인, Chaos 거절, 중복 결제 409, 결제 조회 404, 환불 불가 상태, 환불 금액 초과, 전액 환불 시 `REFUNDED` 전이다.

## 9. 자주 발생한 오류와 트러블슈팅

| 증상 | 원인 | 해결 | 재발 방지 |
| --- | --- | --- | --- |
| `DUPLICATE_PAYMENT`가 계속 발생 | 같은 `order_id` 재사용 | 테스트 데이터 격리 또는 새 order_id 사용 | 테스트 fixture에서 DB 초기화 |
| SQLite에서 PK 자동 증가 실패 | BigInteger autoincrement 차이 | `BigIntegerType` 사용 | 모델 변경 시 SQLite 테스트 실행 |
| Chaos 설정이 테스트에 반영 안 됨 | `get_settings()` 캐시 | cache clear 또는 객체 속성 monkeypatch | 설정 테스트 패턴 통일 |
| 환불 초과가 허용됨 | 기존 완료 환불 합산 누락 | `RefundStatus.COMPLETED` 합산 후 비교 | 부분 환불 테스트 유지 |
| 내부 API가 403 | `X-Internal-Token` 누락/불일치 | `.env.example` 기준 토큰 주입 | 내부 호출 클라이언트 테스트 유지 |

## 10. 왜 이 설계인가

결제 서비스는 성공보다 실패가 중요한 학습 대상이다. 실제 PG가 없어도 결제 거절, 응답 지연, DB 지연을 재현해야 order-service Saga와 관찰성 스택을 의미 있게 검증할 수 있다.

`PENDING` 선생성은 결제 처리가 “요청 접수”와 “최종 승인/거절”로 나뉜다는 점을 코드에 드러낸다. 이 구분이 있어야 레이턴시를 측정하고 장애 중간 상태를 이해할 수 있다.

현재 환불은 실무 수준의 모든 동시성 문제를 해결하려는 설계가 아니라, 승인 결제에 대한 부분/전액 환불 흐름을 명확히 보여주는 범위다. 복잡한 PG 정산보다 MicroMart의 목표인 실패 경로와 관찰성 학습에 집중한다.
