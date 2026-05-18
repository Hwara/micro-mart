# MicroMart k6 부하 테스트

이 디렉터리는 Kubernetes local 환경에서 주요 주문 흐름의 정상 상태 baseline을 측정하기 위한 k6 스크립트를 담고 있습니다.

```text
api-gateway -> order-service -> product-service -> payment-service -> NATS -> notification-service
```

## 사전 조건

- Kubernetes 서비스가 `micro-mart-local` namespace에 배포되어 있어야 합니다.
- 공용 인프라는 `micro-mart` namespace에서 정상 동작해야 합니다.
- Observability 스택이 metrics, logs, traces를 수집 중이어야 합니다.
- Payment Chaos Mode는 꺼둡니다.
  - `CHAOS_FAILURE_RATE=0`
  - `CHAOS_LATENCY_MS=0`
  - `CHAOS_DB_SLOWQUERY=false`
- Gateway rate limit은 비활성화하거나 선택한 VU 수에 맞게 충분히 높게 설정합니다.
- 로컬 머신에 k6가 설치되어 있어야 합니다.

## 테스트 상품 준비

`productdb`에 재고가 충분한 테스트 상품을 넣습니다.

```bash
cat k6/setup/seed-products.sql | kubectl -n micro-mart exec -i statefulset/postgresql -- psql -U postgres -d productdb
```

스크립트는 이름이 `k6-baseline-`으로 시작하는 상품만 사용합니다. 특정 상품 ID 풀을 직접 지정하려면 `PRODUCT_IDS`를 전달하면 됩니다.

```bash
-e PRODUCT_IDS=1,2,3
```

## Gateway 노출

```bash
kubectl -n micro-mart-local port-forward svc/api-gateway 8080:8000
```

기본 `BASE_URL`은 `http://localhost:8080`입니다.

## Smoke Test

부하 테스트 전에 smoke test를 먼저 실행합니다.

```bash
k6 run -e BASE_URL=http://localhost:8080 k6/scenarios/smoke.js
```

Smoke test는 아래 항목을 확인합니다.

- gateway health
- baseline 사용자 회원가입/로그인
- seed된 상품 조회 및 상세 조회
- 주문 1건 생성 성공

## Baseline Run

```bash
k6 run -e BASE_URL=http://localhost:8080 k6/scenarios/baseline_order_flow.js
```

기본 profile은 다음과 같습니다.

| Stage | Duration | Target |
| --- | ---: | ---: |
| Ramp up | 1m | 20 VUs |
| Steady | 5m | 20 VUs |
| Ramp down | 1m | 0 VUs |

필요하면 profile 값을 환경변수로 조정할 수 있습니다.

```bash
k6 run \
  -e BASE_URL=http://localhost:8080 \
  -e K6_TARGET_VUS=10 \
  -e K6_RAMP_UP=30s \
  -e K6_STEADY=2m \
  -e K6_RAMP_DOWN=30s \
  k6/scenarios/baseline_order_flow.js
```

## Thresholds

Baseline 기준 threshold는 아래와 같습니다.

- `http_req_failed < 1%`
- `http_req_duration p(95) < 1000ms`
- `checks rate > 99%`
- `order_create p(95) < 1000ms`

주문 iteration은 `POST /orders`가 `201`을 반환하고, 주문 상태가 `COMPLETED`이며, `payment_id`가 있을 때만 성공으로 봅니다.

## Grafana 확인 항목

Baseline 실행 중이나 실행 후에는 k6 출력과 아래 지표를 함께 비교합니다.

- Prometheus: `gateway_requests_total`
- Prometheus: `gateway_request_duration_ms`
- Prometheus: `order_completed_total`
- Prometheus: `order_failed_total`
- Prometheus: `payment_approved_total`
- Tempo: 주문 trace에 gateway, order, product, payment, notification span이 이어지는지 확인
- Loki: 로그에 `service`, `trace_id`, `span_id`, `event` 필드가 유지되는지 확인

기대하는 baseline 결과는 낮은 error rate, 안정적인 p95 latency, 증가하는 `order_completed_total`, 그리고 비즈니스 실패 메트릭이 늘지 않는 상태입니다.

## Stock Contention Run

정상 baseline 이후에는 단일 상품에 동시 주문을 집중시켜 낙관적 잠금 경합을 관찰합니다.
이 테스트는 재고 부족이 아니라 `VERSION_CONFLICT`와 재시도 비용을 보기 위한 시나리오이므로
충분한 재고를 가진 전용 상품을 사용합니다.

```bash
cat k6/setup/seed-stock-contention.sql | kubectl -n micro-mart exec -i statefulset/postgresql -- psql -U postgres -d productdb
```

```bash
k6 run -e BASE_URL=http://localhost:8080 k6/scenarios/stock_contention_order_flow.js
```

기본 profile은 다음과 같습니다.

| Stage | Duration | Target |
| --- | ---: | ---: |
| Ramp up | 30s | 20 VUs |
| Steady | 3m | 20 VUs |
| Ramp down | 30s | 0 VUs |

필요하면 profile 값을 환경변수로 조정할 수 있습니다.

```bash
k6 run \
  -e BASE_URL=http://localhost:8080 \
  -e K6_CONTENTION_TARGET_VUS=20 \
  -e K6_CONTENTION_RAMP_UP=10s \
  -e K6_CONTENTION_STEADY=1m \
  -e K6_CONTENTION_RAMP_DOWN=10s \
  k6/scenarios/stock_contention_order_flow.js
```

특정 상품 ID를 직접 지정하려면 `PRODUCT_IDS`의 첫 번째 값을 사용합니다.

```bash
k6 run -e BASE_URL=http://localhost:8080 -e PRODUCT_IDS=123 k6/scenarios/stock_contention_order_flow.js
```

Stock contention 기준 threshold는 아래와 같습니다.

- `http_req_failed < 2%`
- `checks rate > 98%`
- `order_create_contention p(95) < 1500ms`

Grafana에서는 baseline 지표에 더해 아래 항목을 함께 확인합니다.

- Prometheus: `product_stock_conflict_total`
- Prometheus: `product_stock_deduct_total`
- Prometheus: `order_completed_total`
- Prometheus: `order_failed_total`
- Prometheus: `gateway_request_duration_ms`
- Tempo: 일부 주문 trace에서 product 재조회와 재시도로 지연이 늘어나는지 확인

## Payment Failure Chaos Run

결제 실패 Chaos 테스트는 payment-service의 결제 거절이 Saga 보상 트랜잭션과
관찰성 지표에 어떻게 드러나는지 확인합니다. 실행 전 payment-service에 실패율을 설정합니다.

```text
CHAOS_FAILURE_RATE=0.3
CHAOS_LATENCY_MS=0
CHAOS_DB_SLOWQUERY=false
```

```bash
k6 run -e BASE_URL=http://localhost:8080 k6/scenarios/payment_failure_chaos_order_flow.js
```

이 시나리오는 `201`과 `402 PAYMENT_REJECTED`를 모두 기대 응답으로 취급합니다.

확인 항목:

- k6: `order_create_payment_failure` p95, `201`/`402` 비율
- Prometheus: `payment_rejected_total{reason="chaos"}`
- Prometheus: `saga_stock_rollback_total`
- Prometheus: `order_failed_total`
- Tempo: 결제 거절 trace에서 재고 복구 span이 이어지는지 확인

## Payment Latency Chaos Run

결제 지연 Chaos 테스트는 payment-service 지연이 주문 전체 p95/p99에 어떻게 전파되는지 확인합니다.
실행 전 payment-service에 지연만 설정합니다.

```text
CHAOS_FAILURE_RATE=0
CHAOS_LATENCY_MS=2000
CHAOS_DB_SLOWQUERY=false
```

```bash
k6 run -e BASE_URL=http://localhost:8080 k6/scenarios/payment_latency_chaos_order_flow.js
```

확인 항목:

- k6: `order_create_payment_latency` p95
- Prometheus: `payment_processing_latency_ms`
- Prometheus: `gateway_request_duration_ms`
- Prometheus: `order_completed_total`
- Tempo: payment-service span이 주문 trace의 주요 지연 구간인지 확인

## Auth And Rate Limit Run

인증 실패와 Rate Limit 테스트는 gateway가 보호 경로의 잘못된 인증 요청을 401로 차단하고,
고빈도 public 요청을 429로 제한하는지 확인합니다. Rate Limit을 관찰하려면
`RATE_LIMIT_PER_MINUTE`를 테스트 VU 수에 맞게 낮춥니다.

```bash
k6 run -e BASE_URL=http://localhost:8080 k6/scenarios/auth_rate_limit_flow.js
```

확인 항목:

- k6 setup: `auth_missing_token_setup` 401
- k6 setup: `auth_invalid_token_setup` 401
- k6 steady: `auth_missing_token`, `auth_invalid_token` 401 또는 429
- k6: `rate_limit_probe` 200 또는 429
- Prometheus: `gateway_auth_failure_total`
- Prometheus: `gateway_rate_limit_total`

## Mixed Read/Order Run

조회 혼합 트래픽 테스트는 상품 조회, 주문 조회, 주문 생성을 섞어 정상 주문 단일 시나리오보다
현실적인 baseline을 관찰합니다. Payment Chaos Mode는 꺼둔 상태에서 실행합니다.

```text
CHAOS_FAILURE_RATE=0
CHAOS_LATENCY_MS=0
CHAOS_DB_SLOWQUERY=false
```

```bash
k6 run -e BASE_URL=http://localhost:8080 k6/scenarios/mixed_read_order_flow.js
```

기본 비율은 상품 목록 45%, 상품 상세 25%, 주문 목록 15%, 주문 상세 10%, 주문 생성 5%입니다.

확인 항목:

- k6: endpoint tag별 latency
- Prometheus: `gateway_requests_total` path group 분포
- Prometheus: `product_cache_hits_total` / `product_cache_misses_total`
- Prometheus: `order_completed_total`
- Tempo: 읽기 요청과 주문 생성 요청의 trace 길이 차이
