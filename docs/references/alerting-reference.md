# Alerting Reference

> 관련 Phase: Phase 13

## Role description

Alerting은 MicroMart의 관찰성 메트릭과 로그를 운영 신호로 바꾸는 단계다. Prometheus alert rule은
장애 조건을 판정하고, Alertmanager는 receiver와 알림 라우팅을 담당한다. Grafana는 알림이 발생한
시점의 메트릭, 로그, 트레이스를 함께 확인하는 운영 화면으로 사용한다.

## File structure

```text
k8s/observability/
├── prometheus-values.yaml       # Prometheus와 Alertmanager Helm values
├── grafana-values.yaml          # datasource, dashboard, 알림 확인 화면
├── loki-values.yaml             # Loki ruler/API 사용 가능 설정
├── secrets/
│   └── slack-webhook-url.txt.example
└── dashboard/
    └── micromart-observability-overview.json

docs/references/
└── alerting-reference.md
```

## Key design decisions

- 알림 판정은 기존 비즈니스 메트릭을 우선 사용한다.
- 결제 지연은 `payment_processing_latency_ms` p99, 결제 실패율은
  `payment_rejected_total`과 `payment_total` 비율로 판단한다.
- gateway 장애는 `gateway_requests_total{status_code=~"5.."}`와
  `gateway_rate_limit_total` 증가를 본다.
- notification 장애는 `notification_send_failed_total`과
  `notification_processing_latency_ms`를 본다.
- NATS 연결 끊김은 현재 Prometheus metric을 새로 만들지 않고 notification-service `/health`의
  `nats_connected=false` 또는 관련 warning 로그로 확인한다.
- OTel 수집 중단은 서비스별 핵심 메트릭이 일정 시간 사라지는 조건으로 판단한다.
- `order_id`, `user_id`, `payment_id` 같은 고카디널리티 값은 알림 레이블에 넣지 않는다.
- Alertmanager receiver는 Slack Incoming Webhook을 사용한다. 실제 webhook URL은
  `k8s/observability/secrets/slack-webhook-url.txt`에 로컬로만 보관하고, Helm 배포 시
  `--set-file alertmanager.config.global.slack_api_url=...`로 주입한다.
- Slack 채널 기본값은 `#micro-mart-alerts`이며, Alertmanager label은 `severity`, `service`,
  `category`만 사용한다.
- Slack 메시지 본문에는 `alertname`, `service`, `severity`, `category`, `summary`, `description`을
  포함한다. Prometheus Helm chart는 Alertmanager config 값을 그대로 전달하므로 Alertmanager
  template 문법을 직접 작성한다.

## Alert rules

현재 임계 시간은 로컬 학습 환경 기준이다. 빠른 피드백을 위해 대부분의 알림은 `for: 1m`, 완료율과
캐시 미스율처럼 10분 window를 보는 알림은 `for: 2m`, metric 미수집은 `absent_over_time(...[3m])`
+ `for: 1m`으로 둔다. staging/prod에서는 일시적 배포, scrape 지연, 트래픽 변동을 흡수하도록 더 긴
`for`와 `repeat_interval`을 사용한다.

| Alert | 기준 | 기본 임계값 | 의도 |
| ----- | ---- | ----------- | ---- |
| `PaymentP99LatencyHigh` | `payment_processing_latency_ms_milliseconds_bucket` p99 | 3000ms 초과 1분 | 결제 지연과 주문 지연 상관관계 확인 |
| `PaymentFailureRateHigh` | `payment_rejected_total / payment_total` | 20% 초과 1분 | Chaos Mode 또는 결제 장애 감지 |
| `Gateway5xxRateHigh` | `gateway_requests_total{status_code=~"5.."}` 비율 | 5% 초과 1분 | 외부 진입점 장애 감지 |
| `GatewayRateLimitSpike` | `gateway_rate_limit_total` rate | 초당 0.1 초과 1분 | 비정상 고빈도 요청 감지 |
| `GatewayAuthFailureSpike` | `gateway_auth_failure_total / gateway_auth_total` | 20% 초과 1분 | JWT 위조, 만료 토큰 폭증, 클라이언트 인증 오류 감지 |
| `GatewayJWKSFailureSpike` | `gateway_auth_failure_total{reason="jwks_error"}` | 0 초과 1분 | JWKS 조회/검증 실패로 정상 사용자 인증이 막히는 상황 감지 |
| `OrderFailureRateHigh` | `order_failed_total / order_created_total` | 10% 초과 1분 | 주문 생성 실패율 증가 감지 |
| `OrderCompletionDrop` | `order_completed_total / order_created_total` | 80% 미만 2분 | 주문 요청 대비 완료율 저하 감지 |
| `SagaRollbackSpike` | `saga_stock_rollback_total` rate | 초당 0.05 초과 1분 | 결제 실패 또는 Saga 불안정으로 인한 보상 트랜잭션 증가 감지 |
| `ProductStockConflictSpike` | `product_stock_conflict_total` rate | 초당 0.1 초과 1분 | 낙관적 잠금 충돌 증가와 주문 경합 감지 |
| `ProductCacheMissRateHigh` | `product_cache_misses_total / (hits + misses)` | 80% 초과 2분 | Redis cache-aside 효과 저하와 DB 부하 증가 가능성 감지 |
| `NotificationSendFailures` | `notification_send_failed_total` rate | 0 초과 1분 | 이벤트 소비 후 알림 처리 실패 감지 |
| `NotificationP95LatencyHigh` | `notification_processing_latency_ms_milliseconds_bucket` p95 | 3000ms 초과 1분 | 알림 소비/처리 지연 감지 |
| `PaymentMetricsMissing` | `absent_over_time(payment_total[3m])` | 3분 미수집 + 1분 | 결제 서비스 또는 OTel metric 파이프라인 이상 감지 |
| `GatewayMetricsMissing` | `absent_over_time(gateway_requests_total[3m])` | 3분 미수집 + 1분 | gateway 또는 OTel metric 파이프라인 이상 감지 |
| `NotificationMetricsMissing` | `absent_over_time(notification_message_consumed_total[3m])` | 3분 미수집 + 1분 | notification-service metric 유입 중단 감지 |

## Validation

```bash
helm template prometheus prometheus-community/prometheus -n monitoring -f k8s/observability/prometheus-values.yaml --set-file alertmanager.config.global.slack_api_url=k8s/observability/secrets/slack-webhook-url.txt
```

Prometheus 배포 후에는 `Status > Rules`에서 `micromart.phase13.alerts` 그룹을 확인하고,
Alertmanager UI에서 firing/resolved 알림이 Slack receiver로 라우팅되는지 확인한다.

시나리오 검증은 기존 k6 스크립트를 사용한다.

- 결제 지연: `k6/scenarios/payment_latency_chaos_order_flow.js`
- 결제 실패율: `k6/scenarios/payment_failure_chaos_order_flow.js`
- Rate Limit: `k6/scenarios/auth_rate_limit_flow.js`
- notification 실패: `NOTIFICATION_FAILURE_RATE`를 높이고 주문 완료 이벤트 발생

## Common errors and troubleshooting

- 알림이 발동하지 않으면 Prometheus에 대상 metric series가 존재하는지 Explore에서 먼저 확인한다.
- p99 알림이 비어 있으면 histogram bucket series(`*_bucket`)가 수집되는지 확인한다.
- Alertmanager UI에 알림이 없으면 Prometheus rule 로딩 상태와 rule expression 문법을 확인한다.
- Slack 메시지가 오지 않으면 `slack-webhook-url.txt`의 실제 URL, Alertmanager receiver 상태,
  Slack 앱의 채널 권한을 순서대로 확인한다.
- Grafana 패널과 알림 값이 다르면 같은 PromQL과 같은 time range를 사용했는지 확인한다.
- notification/NATS 알림이 과도하게 발생하면 NATS 재연결 대기 시간과 alert `for` 시간을 늘린다.

## Why this design was chosen

MicroMart의 목적은 LGTM 학습이므로 단순 인프라 uptime보다 주문, 결제, 알림 흐름의 실패를 빠르게
발견하는 알림이 더 유용하다. 기존 메트릭을 우선 사용하면 서비스 코드 변경 없이 Phase 13을 시작할
수 있고, 새 메트릭이 필요한 경우에만 작은 범위로 추가할 수 있다. Slack receiver는 실제 운영 알림
흐름을 연습할 수 있지만 webhook URL은 Git에 남기지 않아 secret 관리 원칙을 지킨다.
