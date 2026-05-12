# notification-service Reference

## 1. 문서 목적

이 문서는 `notification-service`의 NATS 이벤트 소비, 알림 발송 시뮬레이션, 실패 분류를 학습하기 위한 서비스별 레퍼런스다.

기준 문서는 다음처럼 사용한다.

- `docs/service_function_definition.md`: `order.completed` 이벤트 계약
- `docs/micromart_design.md`: 비동기 이벤트와 관찰성 학습 시나리오
- `docs/dev_convention.md`: NATS consumer, 로그/메트릭 카디널리티 규칙

이 문서를 읽고 나면 왜 이 서비스가 DB 없이 기동하고, NATS 연결 실패를 앱 실패로 보지 않으며, 실패 메시지를 재발행하지 않는지 설명할 수 있어야 한다.

## 2. 서비스 역할과 경계

`notification-service`는 `order-service`가 발행한 NATS `order.completed` 이벤트를 소비하고, 주문 완료 알림 발송을 시뮬레이션한다.

하지 않는 일은 실제 이메일/SMS 발송, 알림 이력 저장, user-service 연락처 조회, JetStream durable consumer, DLQ, retry queue다. 현재 범위는 이벤트 소비와 관찰성 실습이다.

외부 비즈니스 API는 없고 `/health`만 제공한다. DB와 Redis도 사용하지 않는다.

## 3. 빠른 구조 지도

```text
services/notification-service/
├── app/
│   ├── main.py                              # FastAPI 앱, NATS subscribe, health
│   ├── config.py                            # NATS/발송 시뮬레이션/OTel 설정
│   ├── nats_client.py                       # NATS client 싱글턴
│   ├── schemas.py                           # OrderCompletedEvent
│   └── services/notification_service.py     # payload 검증, 발송 시뮬레이션, 메트릭
└── tests/
    ├── test_health.py
    ├── test_main.py
    ├── test_notification_service.py
    └── test_schemas.py
```

`main.py`의 NATS callback은 raw message bytes만 서비스 계층으로 넘긴다. JSON 파싱, Pydantic 검증, 실패 분류, 발송 시뮬레이션은 `notification_service.py`가 담당한다.

## 4. 핵심 흐름

앱 시작 시 lifespan에서 NATS에 연결하고 `NATS_SUBJECT_ORDER_COMPLETED`를 구독한다. 연결이나 구독이 실패해도 서비스는 기동하며, `/health`의 `nats_connected=false`와 warning 로그로 상태를 드러낸다.

메시지를 받으면 bytes를 UTF-8 JSON으로 파싱한다. JSON 파싱 실패는 `INVALID_JSON`, 스키마 검증 실패는 `INVALID_PAYLOAD`로 기록하고 예외를 밖으로 던지지 않는다.

정상 payload는 알림 발송 시뮬레이션을 실행한다. `NOTIFICATION_SEND_DELAY_MS`가 있으면 지연을 넣고, `NOTIFICATION_FAILURE_RATE` 확률에 걸리면 `SIMULATED_SEND_FAILURE`로 실패를 기록한다.

성공과 실패 모두 handler 내부에서 종료되어 NATS callback이 프로세스를 죽이지 않는다.

## 5. 핵심 설계 결정

| 결정 | 선택 | 대안 | 선택 이유 | 트레이드오프 |
| --- | --- | --- | --- | --- |
| 저장소 | DB/Redis 없음 | 알림 이력 DB | 현재 목표는 이벤트 소비와 관찰성 학습 | 발송 이력 조회 기능 없음 |
| NATS 연결 실패 | 앱 기동 유지 | startup 실패 처리 | 관찰성 실습에서 부분 장애를 health/log로 확인 가능 | 이벤트 소비가 중단되어도 프로세스는 살아 있음 |
| 메시지 실패 | 예외 흡수 + 로그/메트릭 | 재시도/DLQ | core NATS와 단순 consumer 범위 유지 | 메시지 유실 가능성을 감수 |
| 스키마 | `extra="ignore"` | strict forbid | 이벤트 payload 확장 시 기존 소비자 호환 | 예상 외 필드 문제를 놓칠 수 있음 |
| 채널 | `email` 고정 | 다중 채널 | 현재는 발송 시뮬레이션만 필요 | 채널 확장은 별도 설계 필요 |

## 6. 데이터와 계약

소비 이벤트:

```json
{
  "order_id": 1,
  "user_id": 10,
  "total_amount": 25000,
  "payment_id": 3
}
```

`OrderCompletedEvent`는 양수 `order_id`, `user_id`, `total_amount`, `payment_id`를 검증하고, 추가 필드는 무시한다.

엔드포인트:

| Method | Path | 목적 |
| --- | --- | --- |
| GET | `/health` | 서비스 상태, NATS 연결 여부, 구독 subject 확인 |

주요 환경변수는 `NATS_URL`, `NATS_SUBJECT_ORDER_COMPLETED`, `NATS_CONNECT_TIMEOUT_SECONDS`, `NOTIFICATION_SEND_DELAY_MS`, `NOTIFICATION_FAILURE_RATE`다.

## 7. 관찰성

주요 로그 이벤트는 `nats_subscription_started`, `nats_connection_failed`, `notification_message_received`, `notification_payload_invalid`, `notification_send_started`, `notification_send_succeeded`, `notification_send_failed`다.

메트릭:

| 이름 | 의미 |
| --- | --- |
| `notification_message_consumed_total` | NATS 메시지 소비 수 |
| `notification_send_success_total` | 알림 발송 성공 수 |
| `notification_send_failed_total` | 알림 처리 실패 수 |
| `notification_processing_latency_ms` | 메시지 수신부터 처리 완료까지 지연 |
| `notification_send_latency_ms` | 발송 시뮬레이션 지연 |

실패 reason은 `INVALID_JSON`, `INVALID_PAYLOAD`, `SIMULATED_SEND_FAILURE`, `UNEXPECTED_ERROR`로 제한한다. `order_id`, `user_id`, `payment_id`는 로그에는 남기지만 메트릭 레이블에는 넣지 않는다.

## 8. 테스트와 검증

대표 검증 명령:

```powershell
pytest services/notification-service/tests -q
```

검증 포인트는 `/health` 응답, NATS URL sanitizing, 연결 실패 시 기동 유지, JSON 파싱 실패, payload 검증 실패, 발송 성공/실패 메트릭, `extra="ignore"` 호환성이다.

## 9. 자주 발생한 오류와 트러블슈팅

| 증상 | 원인 | 해결 | 재발 방지 |
| --- | --- | --- | --- |
| `/health.nats_connected=false` | NATS 연결 실패 또는 구독 실패 | `NATS_URL`, 네트워크, NATS 컨테이너 확인 | health와 warning 로그를 함께 확인 |
| payload 오류가 계속 발생 | 이벤트 필드 누락 또는 타입 불일치 | `OrderCompletedEvent` 계약 확인 | order-service 발행 payload 테스트 유지 |
| 실패 메트릭 레이블이 늘어남 | 예외 메시지를 reason으로 사용 | 고정 reason 상수 사용 | reason 목록을 코드와 문서에 고정 |
| 토큰/계정 정보가 NATS URL 로그에 노출 | URL userinfo 미제거 | `_sanitize_nats_url` 사용 | 로그 테스트에 userinfo 제거 케이스 유지 |

## 10. 왜 이 설계인가

이 서비스는 “알림 기능”보다 “비동기 소비자가 장애를 어떻게 드러내는가”를 배우기 위한 서비스다. 그래서 실제 provider 연동이나 DB 이력을 넣지 않고, 메시지 검증과 관찰성에 집중한다.

NATS 연결 실패를 앱 기동 실패로 만들지 않는 이유는 부분 장애를 관찰하기 위해서다. 서비스가 살아 있지만 이벤트 소비는 불가능한 상태를 `/health`와 로그로 확인하면, Kubernetes와 Grafana에서 어떤 신호를 봐야 하는지 학습할 수 있다.

재시도나 DLQ를 넣지 않은 것도 의도적인 단순화다. 지금 단계에서는 core NATS 소비, payload 검증, 낮은 카디널리티 메트릭이라는 기본기를 먼저 고정하고, 내구성 있는 이벤트 처리는 향후 JetStream/outbox 설계에서 다루는 편이 낫다.
