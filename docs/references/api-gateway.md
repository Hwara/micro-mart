# api-gateway Reference

## 1. 문서 목적

이 문서는 `api-gateway`의 JWT 검증, 라우팅, Rate Limiting, 관찰성 경계를 학습하기 위한 서비스별 레퍼런스다.

기준 문서는 다음처럼 사용한다.

- `docs/service_function_definition.md`: gateway 공개 경로, 라우팅, 헤더 계약
- `docs/micromart_design.md`: 전체 인증/프록시 아키텍처
- `docs/dev_convention.md`: 외부/내부 API 경계와 보안 규칙

이 문서를 읽고 나면 gateway가 왜 stateless여야 하는지, 왜 클라이언트 신뢰 헤더를 제거하는지, 왜 JWKS 캐시가 필요한지 설명할 수 있어야 한다.

## 2. 서비스 역할과 경계

`api-gateway`는 외부 클라이언트의 단일 진입점이다. RS256 JWT 로컬 검증, 경로 기반 리버스 프록시, IP 기반 Rate Limiting, 요청/응답 로그와 메트릭을 담당한다.

DB와 Redis를 사용하지 않는다. 회원가입/로그인 로직은 `user-service`, 상품/주문 비즈니스 로직은 각 하위 서비스가 담당한다.

gateway가 하위 서비스에 전달하는 사용자 신뢰 경계는 `X-User-ID`, `X-User-Role`이다. 클라이언트가 직접 보낸 동일 헤더는 모든 경로에서 먼저 제거한다.

## 3. 빠른 구조 지도

```text
services/api-gateway/
├── app/
│   ├── main.py                         # FastAPI 앱, 미들웨어, JWKS 워밍업, health
│   ├── config.py                       # 하위 서비스 URL, JWT, timeout, rate limit
│   ├── router.py                       # catch-all 라우터
│   ├── middleware/
│   │   ├── auth.py                     # JWKSCache, verify_jwt, public path 판단
│   │   ├── metrics.py                  # gateway Counter/Histogram
│   │   └── rate_limit.py               # SlowAPI limiter
│   └── services/proxy_service.py       # 라우팅 대상, 헤더 정리, TraceContext 전파
└── tests/
    ├── conftest.py
    ├── test_auth.py
    ├── test_health.py
    └── test_routing.py
```

`main.py`는 보안 미들웨어와 관찰성 미들웨어의 실행 순서를 고정한다. 실제 프록시 HTTP 호출과 hop-by-hop 헤더 제거는 `proxy_service.py`가 담당한다.

## 4. 핵심 흐름

요청은 Rate Limit, Auth, Metrics, Request Logging 순서로 처리된다. `add_middleware()` 등록은 역순 실행이므로 코드에서는 `RequestLoggingMiddleware`, `MetricsMiddleware`, `AuthMiddleware`, `SlowAPIMiddleware` 순서로 추가한다.

공개 경로는 `/health`, `/auth`, `/auth/*`, `GET /products`, `GET /products/*`다. `/auth`는 토큰 재발급과 로그아웃 흐름을 user-service가 직접 판단해야 하므로 gateway JWT 검증을 건너뛴다.

`GET /products` 계열은 optional auth를 지원한다. Bearer 토큰이 없으면 익명으로 통과하고, 토큰이 있으면 검증한다. 검증 실패를 익명 요청으로 낮추지 않고 401을 반환한다.

보호 경로는 Bearer 토큰이 없으면 401, 검증 실패면 401, 성공하면 `sub`와 `role`을 `X-User-ID`, `X-User-Role`로 주입한다.

프록시 단계에서는 `/auth`는 user-service, `/products`는 product-service, `/orders`는 order-service로 전달한다. W3C TraceContext를 주입하고, 하위 서비스 timeout은 504, 연결 실패는 503으로 변환한다.

## 5. 핵심 설계 결정

| 결정 | 선택 | 대안 | 선택 이유 | 트레이드오프 |
| --- | --- | --- | --- | --- |
| 인증 검증 위치 | gateway 단일 검증 | 각 서비스 JWT 검증 | 인증 중복을 줄이고 하위 서비스를 비즈니스 로직에 집중 | gateway가 신뢰 경계의 핵심이 됨 |
| JWKS | 인메모리 TTL 캐시 | 매 요청 user-service 조회 | user-service 병목과 SPOF화를 방지 | 키 회전은 TTL/kid miss 정책에 의존 |
| 헤더 신뢰 | 기존 `X-User-*` 제거 후 재주입 | 클라이언트 헤더 유지 | 사용자/role 위조 방지 | 미들웨어에서 ASGI scope 헤더를 직접 다룸 |
| Rate Limit 순서 | JWT 검증 전 | JWT 검증 후 | 악성 요청이 서명 검증 비용을 유발하지 않게 함 | 차단 요청은 auth 상세를 알 수 없음 |
| 응답 전달 | 하위 서비스 4xx/5xx 그대로 전달 | gateway 표준 에러로 마스킹 | 서비스별 에러 코드를 클라이언트와 테스트가 그대로 확인 | 외부 응답 정책 통일은 약함 |

## 6. 데이터와 계약

gateway는 영속 데이터가 없다.

라우팅 계약:

| Prefix | Target |
| --- | --- |
| `/auth`, `/auth/*` | `USER_SERVICE_URL` |
| `/products`, `/products/*` | `PRODUCT_SERVICE_URL` |
| `/orders`, `/orders/*` | `ORDER_SERVICE_URL` |
| 그 외 | 404 |

하위 서비스 신뢰 헤더:

```text
X-User-ID: {jwt.sub}
X-User-Role: {jwt.role|customer}
```

주요 환경변수는 `USER_SERVICE_URL`, `PRODUCT_SERVICE_URL`, `ORDER_SERVICE_URL`, `JWKS_URL`, `JWT_ALGORITHM`, `JWT_AUDIENCE`, `JWKS_CACHE_TTL_SECONDS`, `HTTP_TIMEOUT_SECONDS`, `RATE_LIMIT_PER_MINUTE`다.

## 7. 관찰성

메트릭:

| 이름 | 의미 |
| --- | --- |
| `gateway_requests_total` | 인바운드 요청 수 |
| `gateway_request_duration_ms` | 요청 처리 지연 |
| `gateway_auth_total` | 인증 결과 |
| `gateway_auth_failure_total` | 인증 실패 사유 |
| `gateway_jwks_cache_total` | JWKS 캐시 hit/miss |
| `gateway_rate_limit_total` | Rate Limit 차단 |

`path_group`은 `/products/{id}`, `/orders/{id}`처럼 그룹화한다. 실제 ID를 레이블에 넣지 않는다.

주요 로그는 JWKS 캐시 갱신/미스, JWT 검증 실패, Rate Limit 초과, 라우팅 대상 없음, 하위 서비스 timeout/연결 실패다.

## 8. 테스트와 검증

대표 검증 명령:

```powershell
pytest services/api-gateway/tests -q
```

검증 포인트는 `/health` 공개 접근, JWKS 캐시 hit/miss, 만료/위조 JWT 401, optional auth 상품 조회, 신뢰 헤더 제거/재주입, prefix 경계(`/products-old` 오라우팅 방지), query/body 전달, timeout/connection error 매핑이다.

## 9. 자주 발생한 오류와 트러블슈팅

| 증상 | 원인 | 해결 | 재발 방지 |
| --- | --- | --- | --- |
| 첫 요청 JWT 검증 지연 | JWKS 캐시 미워밍 | lifespan `_refresh()` 확인 | `/health.jwks_cached_keys` 확인 |
| `/products-old`가 product로 라우팅 | 단순 startswith 사용 | `/products` 또는 `/products/` 경계 검사 | 라우팅 테스트 유지 |
| 클라이언트 role 위조 | `X-User-Role` 제거 누락 | 모든 경로에서 신뢰 헤더 삭제 후 재주입 | 헤더 위조 테스트 유지 |
| 상품 공개 조회가 401 | optional auth 조건 오류 | `GET /products` 계열만 토큰 없음 통과 | public path 테스트 유지 |
| Trace가 서비스 간 끊김 | propagate inject 누락 | 프록시 헤더에 TraceContext 주입 | Tempo에서 gateway→service span 확인 |

## 10. 왜 이 설계인가

gateway는 편의용 프록시가 아니라 시스템의 외부 신뢰 경계다. 그래서 DB 없이 stateless로 두고, 인증 검증과 사용자 헤더 주입을 한 곳에서 수행한다.

JWKS 캐시는 성능 최적화이면서 장애 격리 장치다. 매 요청마다 user-service에 공개키를 물어보면 인증 서비스가 전체 트래픽의 병목이 된다. 캐시 hit/miss를 메트릭으로 남기는 이유도 키 회전과 장애 시점을 관찰하기 위해서다.

가장 중요한 보안 판단은 “클라이언트 입력은 신뢰하지 않는다”이다. public path에서도 `X-User-ID`, `X-User-Role`을 제거하는 이유는 익명 상품 조회 같은 경로를 통해 하위 서비스에 위조된 권한이 전달되는 일을 막기 위해서다.
