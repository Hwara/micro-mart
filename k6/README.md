# MicroMart k6 Baseline 부하 테스트

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
