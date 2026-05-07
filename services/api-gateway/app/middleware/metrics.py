"""
api-gateway 관찰성 메트릭 정의

OpenTelemetry Meter를 사용해 Counter/Histogram을 모듈 레벨에서 정의.
order-service의 order_service.py 패턴과 동일하게 meter.create_*()로 생성.

메트릭 목록:
  gateway_requests_total        - 전체 인바운드 요청 수 (method, path_group, status_code)
  gateway_request_duration_ms   - 요청 처리 레이턴시 분포 (ms)
  gateway_auth_total            - JWT 검증 결과 (result: success | failure)
  gateway_auth_failure_total    - JWT 검증 실패 횟수 (reason 레이블)
  gateway_jwks_cache_total      - JWKS 캐시 히트/미스 (result: hit | miss)
  gateway_rate_limit_total      - Rate Limit 차단 횟수

path_group 레이블 설계:
  /auth, /products, /orders, /health, /unknown
  실제 경로 전체를 레이블로 쓰면 카디널리티 폭발 위험.
  예: /products/12345 → "/products/{id}" 이런 방식으로 그루핑.
"""

from opentelemetry import metrics

meter = metrics.get_meter("api-gateway")

# ── Inbound 트래픽 ────────────────────────────────────────────────
gateway_requests_counter = meter.create_counter(
    "gateway_requests_total",
    description="api-gateway 인바운드 요청 총 횟수 (method, path_group, status_code 레이블)",
)

gateway_request_duration = meter.create_histogram(
    "gateway_request_duration_ms",
    description="api-gateway 요청 처리 레이턴시 분포 (ms)",
    unit="ms",
)

# ── 인증 ─────────────────────────────────────────────────────────
gateway_auth_counter = meter.create_counter(
    "gateway_auth_total",
    description="JWT 검증 결과 횟수 (result: success | no_token | failure)",
)

gateway_auth_failure_counter = meter.create_counter(
    "gateway_auth_failure_total",
    description="JWT 검증 실패 상세 횟수 (reason: expired | invalid | jwks_error)",
)

gateway_jwks_cache_counter = meter.create_counter(
    "gateway_jwks_cache_total",
    description="JWKS 캐시 히트/미스 횟수 (result: hit | miss)",
)

# ── Rate Limiting ─────────────────────────────────────────────────
gateway_rate_limit_counter = meter.create_counter(
    "gateway_rate_limit_total",
    description="Rate Limit 차단 횟수",
)
