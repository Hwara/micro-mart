# MicroMart — 서비스 기능 정의 문서

> 최종 갱신일: 2026-05-24
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
| `api-gateway` | JWT 검증, 라우팅, Rate Limiting, 요청 진입 제어, 관찰성 메트릭 | 없음 |
| `user-service` | 회원가입, 로그인, JWT 발급, Refresh Token Rotation, 로그아웃 | PostgreSQL, Redis |
| `product-service` | 상품 조회/등록/수정/삭제, 캐시 관리, 재고 차감, 재고 복구 | PostgreSQL, Redis |
| `order-service` | 주문 생성/조회, Saga 오케스트레이션, 재고 차감 및 결제 흐름 조정 | PostgreSQL |
| `payment-service` | 결제 승인/거절 시뮬레이션, Chaos Mode, 환불 처리 | PostgreSQL |
| `notification-service` | 주문 완료 이벤트 소비, 알림 발송 시뮬레이션 | 없음 |

---

## 3. 구현 완료 서비스 기능 정의

### 3.1 api-gateway

#### 역할

`api-gateway`는 외부 클라이언트의 단일 진입점이다. RS256 JWT 로컬 검증, 경로 기반 라우팅(리버스 프록시), Rate Limiting, 요청/응답 구조화 로깅, 관찰성 메트릭 계측을 책임진다. 하위 서비스는 이 gateway를 통해서만 외부 트래픽을 수신하며, JWT를 직접 검증하지 않는다.

#### 저장소

- 없음 (stateless 서비스, DB/Redis 미사용)

#### 파일 구성

```text
services/api-gateway/
├── app/
│   ├── main.py           # FastAPI 앱, lifespan (JWKS 워밍업), 미들웨어 등록
│   ├── config.py         # Settings (JWKS URL, JWT 설정, Rate Limit, HTTP 타임아웃)
│   ├── router.py         # catch-all HTTP 경계, Rate Limit 적용, 404 응답
│   ├── middleware/
│       ├── auth.py       # JWKSCache, verify_jwt, is_public_path
│       ├── metrics.py    # OTel Counter/Histogram 메트릭 정의
│       └── rate_limit.py # SlowAPI Limiter 설정
│   └── services/
│       └── proxy_service.py # get_target_url, proxy_request
├── tests/
│   ├── conftest.py       # RS256 키쌍 동적 생성, make_jwks_response, make_access_token
│   ├── test_health.py    # /health 인증 불필요 검증
│   ├── test_auth.py      # JWT 검증, JWKS 캐시 히트/미스, 만료/서명불일치 케이스
│   └── test_routing.py   # 경로별 라우팅, 쿼리 파라미터/바디 전달, 에러 전파
├── .env.example
├── pytest.ini
└── requirements.txt
```

#### 미들웨어 실행 순서

`add_middleware()`는 역순으로 실행되므로 아래 순서대로 등록한다.

```python
app.add_middleware(RequestLoggingMiddleware)  # ④ 가장 바깥: 요청/응답 구조화 로그
app.add_middleware(MetricsMiddleware)         # ③ 레이턴시 측정 (인증 실패도 포함)
app.add_middleware(AuthMiddleware)            # ② JWT 검증
app.add_middleware(SlowAPIMiddleware)         # ① Rate Limit (가장 먼저 실행)
```

Rate Limit을 가장 먼저 실행하는 이유: 악성 트래픽이 JWT 검증 연산 자체를 유발하는 낭비를 막는다. MetricsMiddleware를 Auth 바깥에 두는 이유: 인증 실패 포함 모든 요청의 레이턴시를 측정해야 한다.

#### 공개 경로 (익명 접근 허용)

| 메서드 | 경로 | 이유 |
| ------ | ---- | ---- |
| ANY | `/health` | k8s liveness probe |
| ANY | `/auth` 및 `/auth/*` | JWT가 없는 상태의 요청 (로그인·회원가입·토큰 재발급) |
| GET | `/products` 및 `/products/*` | 비인증 상품 조회 허용 |

경계 매칭 방식: `/products` 또는 `/products/`로 시작하는 경로만 허용. `/products-old` 같은 유사 경로 오라우팅 방지.

공개 경로에서도 클라이언트가 직접 보낸 `X-User-ID`, `X-User-Role`은 항상 제거한다. 단,
optional auth는 `GET /products` 계열에만 적용한다. 상품 조회 경로에 `Authorization: Bearer ...`가
있으면 JWT를 검증하고 성공 시에만 gateway가 사용자 헤더를 다시 주입한다. `/auth`는 로그인,
재발급, 로그아웃 등 토큰 수명주기를 user-service가 직접 판단해야 하므로 gateway JWT 검증을
건너뛴다.

#### JWKS 캐시

```python
class JWKSCache:
    _keys: dict[str, RSAPublicKey]  # kid → 공개키
    _fetched_at: float              # 마지막 갱신 시각
    _refresh_lock: asyncio.Lock     # 동시 재조회 직렬화
```

- **TTL 기반 캐시**: 기본 3600초, `JWKS_CACHE_TTL_SECONDS` 환경변수로 조정
- **캐시 히트**: TTL 유효 + kid 존재 → 네트워크 요청 없이 즉시 반환
- **캐시 미스**: TTL 만료 또는 kid 미매칭 → user-service `/auth/jwks` 재조회
- **thundering herd 방지**: `asyncio.Lock`으로 동시 재조회 요청 직렬화
- **앱 시작 워밍업**: lifespan에서 `_refresh()` 선제 호출 → 첫 요청 레이턴시 스파이크 방지

#### JWT 검증 흐름

```
1. 요청 진입 시 X-User-ID, X-User-Role 제거
2. `/auth`, `/health` 공개 경로 → 신뢰 헤더 제거 후 gateway JWT 검증 없이 통과
3. `GET /products` + Authorization 없음 → 익명 요청으로 통과
4. 보호 경로 + Authorization 없음 또는 Bearer 아님 → 401 (no_token)
5. 검증 대상 경로에 Bearer 토큰이 있으면 jwt.get_unverified_header()로 kid 추출
6. JWKSCache.get_public_key(kid) → 캐시 히트/미스 처리
7. PyJWT로 서명 + 만료 검증
8. 성공: MutableHeaders로 X-User-ID, X-User-Role 주입
         (클라이언트가 헤더를 직접 심는 위조 시도는 사전 제거 후 gateway 값만 전달)
9. 실패: 401 + code (EXPIRED|INVALID|JWKS_ERROR)
```

#### 라우팅 규칙

| 경로 Prefix | 대상 서비스 | 환경변수 |
| ----------- | ----------- | -------- |
| `/auth` 또는 `/auth/*` | user-service | `USER_SERVICE_URL` |
| `/products` 또는 `/products/*` | product-service | `PRODUCT_SERVICE_URL` |
| `/orders` 또는 `/orders/*` | order-service | `ORDER_SERVICE_URL` |
| 그 외 | 404 NOT_FOUND | — |

- hop-by-hop 헤더(`connection`, `host`, `transfer-encoding` 등)는 프록시 시 제거
- `multi_items()`로 중복 헤더(`Set-Cookie` 등) 보존
- W3C TraceContext 헤더는 `opentelemetry.propagate.inject()`로 하위 서비스에 전파
- `TimeoutException` → 504 GATEWAY_TIMEOUT
- `RequestError` → 503 SERVICE_UNAVAILABLE
- 하위 서비스 4xx/5xx 응답은 마스킹 없이 그대로 전달

#### 엔드포인트

- `GET /health`
  - 기능: 헬스체크 (k8s liveness probe용)
  - 인증: 불필요
  - 응답: `{ "status": "ok", "service": "api-gateway", "jwks_cached_keys": int }`
  - `jwks_cached_keys`: 현재 캐시에 보유 중인 공개키 수 (운영 중 상태 확인용)

#### 관찰성 메트릭

| 메트릭 이름 | 타입 | 레이블 | 설명 |
| ----------- | ---- | ------ | ---- |
| `gateway_requests_total` | Counter | `method`, `path_group`, `status_code` | 전체 인바운드 요청 수 |
| `gateway_request_duration_ms` | Histogram | `method`, `path_group` | 요청 처리 레이턴시 (ms) |
| `gateway_auth_total` | Counter | `result` (success\|no_token\|failure) | JWT 검증 결과 |
| `gateway_auth_failure_total` | Counter | `reason` (expired\|invalid\|jwks_error) | 인증 실패 상세 원인 |
| `gateway_jwks_cache_total` | Counter | `result` (hit\|miss) | JWKS 캐시 히트율 |
| `gateway_rate_limit_total` | Counter | `path_group` | Rate Limit 차단 횟수 |

`path_group` 레이블은 카디널리티 폭발 방지를 위해 그루핑: `/products/12345` → `/products/{id}`.

#### Rate Limiting

- **라이브러리**: SlowAPI (slowapi)
- **기준**: 클라이언트 IP (`get_remote_address`)
- **기본값**: 분당 60 req (`RATE_LIMIT_PER_MINUTE` 환경변수로 조정)
- **저장소**: 인메모리 (단일 인스턴스 환경). 멀티 레플리카 환경에서는 Redis 백엔드 교체 필요
- **초과 시**: 429 응답 + `gateway_rate_limit_total` 카운터 증가

#### 설계 의도

- JWT를 api-gateway에서 한 번만 검증하고 하위 서비스는 헤더를 신뢰한다. 검증 로직 중복을 없애고, 하위 서비스의 관심사를 비즈니스 로직에 집중시킨다.
- JWKS 캐시를 인메모리에 두는 이유: 매 요청마다 user-service에 검증 요청을 보내면 api-gateway가 병목이 되고, user-service가 SPOF가 된다.
- `PyJWT + cryptography` 조합을 선택한 이유: `python-jose`는 유지보수가 사실상 중단되었고, PyJWT는 활발히 관리되는 현업 표준 라이브러리다.
- 클라이언트의 `X-User-ID`/`X-User-Role` 헤더 위조 방어: 요청 진입 시 신뢰 헤더를 제거하고,
  JWT 검증 성공 시에만 `MutableHeaders.__setitem__`으로 gateway 값을 주입한다. public path도
  이 제거 단계를 거치므로, 익명 상품 조회에서 사용자가 `X-User-Role: admin`을 직접 주입할 수 없다.
  `/auth` 경로는 만료 토큰을 포함하더라도 user-service로 전달해 refresh/logout 같은 인증 회복
  흐름을 gateway가 차단하지 않는다.
- `api-gateway`에 DB를 두지 않는 이유: stateless를 유지해야 수평 확장(HPA)이 용이하다. 상태를 Redis나 DB에 두는 순간 레플리카 간 동기화 문제가 발생한다.
- 프록시 로직을 `services/proxy_service.py`로 분리한 이유: 라우터는 HTTP 경계와 Rate Limit만 담당하고, 라우팅 판단·헤더 정리·TraceContext 전파·httpx 예외 매핑은 서비스 계층에서 테스트 가능하게 유지한다.
- 현재 로컬 학습 환경에서는 Access Token에 aud 클레임을 포함하지 않으므로 audience 검증은 비활성화한다. 운영 또는 다중 수신자 토큰 구조로 확장할 경우 aud 클레임 발급 및 JWT_AUDIENCE 검증을 활성화한다.

---

### 3.2 user-service

#### 역할

`user-service`는 사용자 인증과 세션 수명주기를 담당한다. 회원가입, 로그인, Access Token 발급, Refresh Token Rotation, 로그아웃, 공개키 제공을 책임진다.

#### 저장소

- PostgreSQL: 사용자 영속 데이터 저장 (`users`)
- Redis: 기기별 Refresh Token 저장, 세션 무효화 보조 저장소

#### 파일 구성

```text
services/user-service/
├── alembic/
│   ├── env.py
│   └── versions/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py        # Register/Login/Refresh/Logout/Token 응답 스키마
│   ├── auth.py           # JWT/비밀번호/Refresh Token Redis 헬퍼
│   ├── routes/
│   │   └── auth.py       # HTTP 경계
│   └── services/
│       └── auth_service.py # 인증 비즈니스 로직, JWKS 생성
├── .env.example
├── alembic.ini
├── Dockerfile
└── requirements.txt
```

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
    - 중복 이메일 (`409`, 앱 레벨 선검사 + DB UNIQUE 제약)
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
    1. Bearer Access Token의 `sub`와 Refresh Token 소유자 비교
    2. 현재 기기 세션의 Refresh Token 키 삭제
    3. 이미 만료·회전된 Refresh Token은 로그아웃 목적 달성으로 보고 `204` 유지
    4. 토큰 소유자가 다르면 `403` 반환

- `GET /auth/jwks`
  - 기능: RS256 공개키 제공
  - 사용처: `api-gateway`의 JWT 로컬 검증 캐시

#### 설계 의도

- 인증은 user-service에 집중시키고 다른 서비스는 JWT를 직접 검증하지 않는다.
- 공개키 기반 검증으로 gateway가 인증 병목이 되지 않게 한다.
- `token_version`을 통해 강제 로그아웃과 계정 차단을 안전하게 처리한다.
- 라우터와 `auth_service.py`를 분리해 HTTP 요청/응답 경계와 Redis/JWT/DB 상태 전이를 명확히 나눈다.

---

### 3.3 product-service

#### 역할

`product-service`는 상품 카탈로그와 재고를 담당한다. 공개 조회 API와 관리자용 CRUD, 그리고 `order-service`가 호출하는 내부 재고 차감/복구 API를 제공한다.

#### 저장소

- PostgreSQL: 상품 원본 데이터 저장 (`products`)
- Redis: 상품 상세 캐시, Cache-Aside 패턴 적용

#### 파일 구성

```text
services/product-service/
├── alembic/
│   ├── env.py
│   └── versions/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── dependencies.py   # require_admin, verify_internal_service
│   ├── models.py
│   ├── schemas.py
│   ├── cache.py
│   ├── routes/
│   │   └── products.py   # HTTP 경계
│   └── services/
│       └── product_service.py # 상품/재고 비즈니스 로직, 메트릭
├── .env.example
├── alembic.ini
├── Dockerfile
└── requirements.txt
```

#### 주요 데이터

- `products` 테이블은 `name`, `description`, `price`, `stock`, `version`, `is_active`를 관리한다.
- `version`은 낙관적 잠금용이며 재고 차감 시 동시성 충돌을 감지한다.
- `stock >= 0`은 DB 제약으로 강제한다.

#### 엔드포인트

- `GET /products`
  - 기능: 상품 목록 조회
  - 지원: 페이지네이션, `active_only` 필터
  - 권한: 비활성 상품 조회(`active_only=False`)는 admin 전용

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
    1. 단일 UPDATE 쿼리로 낙관적 잠금 + 재고 검사 원자적 처리
    2. `version == expected_version` AND `stock >= quantity` 조건 만족 시 차감
    3. 성공 시 `version` 증가, 캐시 무효화
  - 실패:
    - 재고 부족: `409 INSUFFICIENT_STOCK`
    - 버전 충돌: `409 VERSION_CONFLICT`

- `POST /products/{id}/restore-stock`
  - 기능: 보상 트랜잭션용 내부 재고 복구
  - 인증: `X-Internal-Token`
  - 처리:
    1. `stock += quantity` 원자적 증가 (낙관적 잠금 미적용)
    2. `version` 증가 (변경 이력 추적용)
    3. 성공 시 캐시 무효화
  - 설계 의도: 복구는 단방향 증가 연산으로 경합이 없음. version 충돌로 복구가 막히면 재고 영구 소실 위험이 있으므로 잠금 미적용.
  - 실패: `404` — 상품 없음 또는 비활성

#### 설계 의도

- 상품 조회와 주문용 재고 차감을 한 서비스에 두어 재고 정합성을 한 곳에서 유지한다.
- 삭제는 소프트 삭제로 처리해 주문 이력과 충돌하지 않게 한다.
- 고부하 환경에서 락 경합을 줄이기 위해 낙관적 잠금을 사용한다.
- 라우터를 얇게 유지하고 `product_service.py`에 Cache-Aside, 권한 분기, 재고 차감/복구, 메트릭 계측을 모아 테스트 가능성을 높인다.

---

### 3.4 payment-service

#### 역할

`payment-service`는 외부 PG를 흉내 내는 결제 시뮬레이터다. 결제 승인/거절, 지연, 장애 주입, 환불을 담당한다. 모든 엔드포인트는 `X-Internal-Token` 인증이 필수인 내부 전용 API다.

#### 저장소

- PostgreSQL: `payments`, `refunds`

#### 파일 구성

```text
services/payment-service/
├── alembic/
│   ├── env.py
│   └── versions/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── dependencies.py
│   ├── models.py
│   ├── schemas.py
│   ├── routes/
│   │   └── payments.py       # 내부 API HTTP 경계
│   └── services/
│       └── payment_service.py # 결제/환불 상태 전이, Chaos Mode, 메트릭
├── tests/
├── .env.example
├── alembic.ini
├── pytest.ini
└── requirements.txt
```

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
- 라우터와 `payment_service.py`를 분리해 `X-Internal-Token` 인증 경계와 결제/환불 상태 전이를 명확히 나눈다.

---

### 3.5 order-service

#### 역할

`order-service`는 시스템의 오케스트레이터다. 주문 생성, 주문 조회, 재고 차감 요청, 결제 요청, 주문 저장, 이벤트 발행을 한 흐름으로 조율한다.

#### 저장소

- PostgreSQL: `orders`, `order_items`
- NATS: `order.completed` 이벤트 발행 (notification-service 소비)
- Redis: 사용하지 않음 (`database.py`에 Redis 설정 없음)

#### 핵심 데이터

- `orders`: 사용자 ID, 총액, 주문 상태, Saga 상태, 실패 원인, 결제 ID
- `order_items`: 상품 ID, 상품명 스냅샷, 단가 스냅샷, 수량, 할인액, 소계

#### 파일 구성

```text
services/order-service/
├── alembic/
│   ├── env.py
│   └── versions/
├── app/
│   ├── __init__.py
│   ├── main.py           # FastAPI 앱, lifespan (NATS 초기화/종료), 헬스체크
│   ├── config.py         # Settings (product/payment URL, NATS URL, HTTP timeout 등)
│   ├── database.py       # SQLAlchemy async engine, DBSession
│   ├── dependencies.py   # get_current_user_id, verify_internal_service
│   ├── models.py         # Order, OrderItem, OrderStatus, SagaStatus, BigIntegerType
│   ├── schemas.py        # OrderCreateRequest, OrderResponse, OrderListResponse
│   ├── nats_client.py    # NATS 싱글턴 (set/get/clear)
│   ├── routes/
│   │   └── orders.py     # POST /orders, GET /orders, GET /orders/{id}
│   └── services/
│       ├── http_clients.py   # product/payment HTTP 클라이언트 (타임아웃, 에러 래핑)
│       └── order_service.py  # Saga 오케스트레이션 비즈니스 로직
├── tests/
├── .env.example
├── alembic.ini
├── pytest.ini
└── requirements.txt
```

#### 엔드포인트

- `POST /orders`
  - 기능: 주문 생성 (Saga 오케스트레이션 실행)
  - 인증: gateway가 전달한 `X-User-ID` 헤더 (바디 수신 금지)
  - 입력: `items: [{product_id, quantity}]` (동일 product_id 중복 불가, 수량 1~100)
  - 처리:
    1. 상품 정보 일괄 조회 (가격·활성화 여부 확인)
    2. 총액 계산 후 Order + OrderItems DB 저장 (`PENDING` / `STARTED`)
    3. 재고 차감 순차 처리 (실패 시 이미 차감된 재고 즉시 롤백)
    4. `STOCK_DEDUCTED` 상태 커밋
    5. 결제 요청
    6. 성공 시 `COMPLETED` + NATS `order.completed` 발행
    7. 결제 실패 시 재고 롤백 후 `FAILED`
  - 응답: 주문 상세 (`OrderResponse`, items 포함)
  - 실패 응답:
    - `404` — 존재하지 않는 상품
    - `402` — 결제 거절
    - `409` — 재고 부족 또는 낙관적 락 충돌
    - `422` — 비활성 상품 또는 중복 product_id
    - `503/504` — 하위 서비스 불가 또는 타임아웃

- `GET /orders`
  - 기능: 내 주문 목록 조회
  - 인증: `X-User-ID` 헤더
  - 지원: 페이지네이션 (`page`, `page_size`), 최신 주문 먼저 정렬
  - 응답: `OrderListResponse` 목록 (items 제외, 요약 응답)

- `GET /orders/{order_id}`
  - 기능: 주문 상세 조회
  - 인증: `X-User-ID` 헤더
  - 응답: `OrderResponse` (items 포함, selectinload)
  - 실패 응답:
    - `403` — 타인 주문 접근 시도 (IDOR 방어)
    - `404` — 주문 없음

- `GET /health`
  - 기능: 헬스체크 (k8s liveness probe용)
  - 응답: 서비스 상태 + NATS 연결 상태 (`nats_connected`)

#### Saga 오케스트레이션 상태 전이

```text
STARTED
  → STOCK_DEDUCTED   (stock_deducted = True 커밋)
  → PAYMENT_REQUESTED
  → COMPLETED

결제 실패 시:
PAYMENT_REQUESTED
  → STOCK_ROLLBACK_NEEDED  (먼저 커밋 — 장애 복구 배치 스캔 근거)
  → STOCK_ROLLED_BACK      (롤백 성공)
     OR STOCK_ROLLBACK_NEEDED (롤백 실패, best-effort)
  → FAILED
```

#### 낙관적 잠금 재시도 전략

- 재고 차감 시 `VERSION_CONFLICT(409)` 수신 시 상품을 재조회하여 최신 `version`을 확보 후 재시도
- 최대 `max_optimistic_retry`(기본값: 3)회 반복, 초과 시 `ORDER_STOCK_CONFLICT(409)` 반환
- 설정: `MAX_OPTIMISTIC_RETRY` 환경변수로 조정 가능

#### 관찰성 메트릭

| 메트릭 이름 | 타입 | 설명 |
| ----------- | ---- | ---- |
| `order_created_total` | Counter | 주문 생성 요청 총 횟수 |
| `order_completed_total` | Counter | 주문 완료 횟수 |
| `order_failed_total` | Counter | 주문 실패 횟수 (`reason` 레이블) |
| `order_amount_krw` | Histogram | 주문 금액 분포 (원단위) |
| `saga_stock_rollback_total` | Counter | 재고 롤백 보상 트랜잭션 횟수 |

#### NATS 이벤트

- `order.completed` 이벤트 발행 (notification-service 소비)
- 페이로드: `{ order_id, user_id, total_amount, payment_id }`
- best-effort: NATS 연결 실패 또는 발행 실패 시 주문은 `COMPLETED` 유지, 로그만 기록
- 향후 outbox 패턴으로 교체하면 at-least-once 보장 가능

#### 설계 의도

- 분산 트랜잭션 대신 Orchestration Saga를 사용해 복구 가능한 실패 흐름을 만든다.
- 상품명과 단가를 스냅샷으로 저장해 이후 상품 변경과 무관하게 주문 이력을 보존한다.
- `STOCK_ROLLBACK_NEEDED`를 결제 실패 즉시 커밋해, 서버 크래시 시에도 배치 잡이 미완료 보상 트랜잭션을 감지·재실행할 수 있다.
- NATS 커넥션을 싱글턴으로 관리해 요청마다 연결을 생성하는 오버헤드를 없앤다.

---

## 4. 이벤트 소비 서비스 기능 정의

### 4.1 notification-service

#### 역할

`notification-service`는 `order-service`가 best-effort로 발행하는 NATS `order.completed` 이벤트를 소비하고, 주문 완료 알림 발송을 시뮬레이션한다. 실제 이메일/SMS provider 연동, 알림 이력 저장, 사용자 연락처 조회는 하지 않으며, 성공/실패/지연을 로그와 메트릭으로 관찰하는 데 집중한다.

#### 저장소

- 없음 (DB/Redis 미사용)

#### 파일 구성

```text
services/notification-service/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI 앱, lifespan(NATS 연결/구독), 헬스체크
│   ├── config.py                  # Settings (NATS, 발송 지연/실패율, OTel)
│   ├── schemas.py                 # OrderCompletedEvent
│   ├── nats_client.py             # NATS 싱글턴 (set/get/clear)
│   └── services/
│       └── notification_service.py # 메시지 검증, 발송 시뮬레이션, 로그/메트릭
├── tests/
├── Dockerfile
├── .env.example
├── pytest.ini
└── requirements.txt
```

#### NATS 구독

- Subject: `order.completed`
- Payload:

```json
{
  "order_id": 1,
  "user_id": 10,
  "total_amount": 25000,
  "payment_id": 3
}
```

- `extra="ignore"` 정책으로 향후 payload 필드가 추가되어도 기존 소비자가 즉시 깨지지 않게 한다.
- NATS 연결 실패 시 앱 기동은 유지하고 `/health.nats_connected=false`와 warning 로그로 드러낸다.
- JetStream durable consumer, DLQ, retry queue는 현재 범위에 포함하지 않는다.

#### 엔드포인트

- `GET /health`
  - 기능: 헬스체크
  - 응답: `{ "status": "ok", "service": "notification-service", "nats_connected": bool, "subject": "order.completed" }`
  - 외부 클라이언트용 비즈니스 API는 제공하지 않는다.

#### 실패 처리 정책

| reason | 의미 |
| ------ | ---- |
| `INVALID_JSON` | 메시지 bytes가 UTF-8 JSON으로 파싱되지 않음 |
| `INVALID_PAYLOAD` | JSON은 유효하지만 `OrderCompletedEvent` 스키마를 만족하지 않음 |
| `SIMULATED_SEND_FAILURE` | 설정된 실패율에 따른 알림 발송 시뮬레이션 실패 |
| `UNEXPECTED_ERROR` | 예상하지 못한 처리 오류 |

실패한 메시지는 재발행하지 않고, handler 내부에서 예외를 흡수해 프로세스 크래시로 이어지지 않게 한다.

#### 관찰성 메트릭

| 메트릭 이름 | 타입 | 레이블 | 설명 |
| ----------- | ---- | ------ | ---- |
| `notification_message_consumed_total` | Counter | `subject` | NATS 메시지 소비 횟수 |
| `notification_send_success_total` | Counter | `channel` | 알림 발송 성공 횟수 |
| `notification_send_failed_total` | Counter | `reason`, `channel` | 알림 처리 실패 횟수 |
| `notification_processing_latency_ms` | Histogram | `subject` | 메시지 수신부터 처리 완료까지 시간 |
| `notification_send_latency_ms` | Histogram | `channel` | 발송 시뮬레이션 소요 시간 |

초기 `channel` 값은 `email`로 고정한다. `order_id`, `user_id`, `payment_id` 같은 고카디널리티 값은 메트릭 레이블에 넣지 않는다.

---

## 5. 서비스 간 호출 계약

### 주문 생성 Happy Path

1. Client → `api-gateway` (JWT 검증, Rate Limit 체크)
2. `api-gateway` → `order-service` (X-User-ID, X-User-Role 헤더 주입)
3. `order-service` → `product-service` 상품 조회 (`GET /products/{id}`)
4. `order-service` → `order-db` 주문/주문항목 저장 (`PENDING` / `STARTED`)
5. `order-service` → `product-service` 재고 차감 (`POST /products/{id}/deduct-stock`, `X-Internal-Token`)
6. `order-service` → `payment-service` 결제 요청 (`POST /payments`, `X-Internal-Token`)
7. `order-service` → 성공 상태 커밋 후 NATS `order.completed`
8. `notification-service` 소비

### 주문 생성 실패 경로

- 상품 미존재/비활성: 주문 생성 전 즉시 실패 (Order DB 저장 없음)
- 재고 부족: 지금까지 차감된 재고 롤백(`restore-stock`) 후 `FAILED`
- 결제 실패 (`402 PAYMENT_REJECTED`): 재고 롤백 후 FAILED
- 롤백 미완료: `STOCK_ROLLBACK_NEEDED` 상태로 남기고 후속 복구 배치 대상 처리

### api-gateway → 하위 서비스 헤더 계약

```text
# gateway가 검증 후 주입하는 헤더 (하위 서비스가 신뢰하는 헤더)
X-User-ID: {user_id}          # JWT sub claim 값
X-User-Role: {role}            # JWT role claim 값 (customer|admin)
```

### product-service 호출 규격

```python
# order-service → product-service (상품 조회)
GET /products/{product_id}
# 성공 응답 (200)
{ "id": int, "name": str, "price": int, "stock": int, "version": int, "is_active": bool, ... }

# order-service → product-service (재고 차감)
POST /products/{product_id}/deduct-stock
Headers:
  X-Internal-Token: {INTERNAL_SERVICE_TOKEN}
Body:
  { "quantity": int, "expected_version": int }
# 성공 응답 (200)
{ "product_id": int, "remaining_stock": int, "new_version": int }
# 실패 응답 (409)
{ "detail": { "detail": "...", "code": "VERSION_CONFLICT" | "INSUFFICIENT_STOCK" } }

# order-service → product-service (재고 복구, 보상 트랜잭션)
POST /products/{product_id}/restore-stock
Headers:
  X-Internal-Token: {INTERNAL_SERVICE_TOKEN}
Body:
  { "quantity": int }
# 성공 응답 (200)
{ "product_id": int, "remaining_stock": int, "new_version": int }
```

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

## 6. 운영 / 배포 기능 정의

Phase 13~16은 애플리케이션 엔드포인트를 추가하지 않고, 현재 서비스 API와 Kubernetes manifest를
운영 가능한 형태로 검증·배포·관찰하는 범위를 다룬다. 외부 트래픽은 계속 `api-gateway`만 통과해야
하며, `payment-service`, `product-service` 내부 재고 API, `notification-service` 같은 내부 전용
서비스는 직접 외부 노출하지 않는다.

### 6.1 Phase 13 — Alerting 알림

#### 역할

Prometheus Alertmanager와 Grafana/Loki 알림 규칙은 MicroMart의 장애 학습 시나리오를 실제 운영
신호로 바꾸는 역할을 한다. 알림은 새 비즈니스 API를 만들지 않고 기존 OpenTelemetry 메트릭,
구조화 로그, Kubernetes 상태를 기준으로 판단한다. 로컬 학습 환경에서는 빠른 피드백을 위해
대부분의 알림을 `for: 1m`으로 두고, Alertmanager Slack receiver의 `group_wait`도 10초로 줄인다.

#### 알림 대상

| 대상 | 기준 신호 | 의도 |
| ---- | --------- | ---- |
| 결제 지연 | `payment_processing_latency_ms` p99 | 결제 서비스 지연과 주문 전체 지연의 상관관계 확인 |
| 결제 실패율 | `payment_rejected_total` / `payment_total` | Chaos Mode 또는 결제 장애 감지 |
| gateway 5xx | `gateway_requests_total{status_code=~"5.."}` | 외부 진입점 장애 감지 |
| gateway 지연/인증 | `gateway_request_duration_ms`, `gateway_auth_failure_total`, `gateway_auth_total` | 외부 진입점 지연, JWT 실패율, JWKS 장애 감지 |
| Rate Limit 급증 | `gateway_rate_limit_total` | 비정상 고빈도 요청 감지 |
| 주문 실패/완료율 | `order_failed_total`, `order_completed_total`, `order_created_total` | 핵심 주문 플로우 실패율과 완료율 저하 감지 |
| Saga 보상 증가 | `saga_stock_rollback_total` | 결제 실패 또는 Saga 불안정에 따른 재고 롤백 증가 감지 |
| 상품 재고 경합 | `product_stock_conflict_total` | 낙관적 잠금 충돌과 특정 상품 주문 경합 감지 |
| 상품 캐시 효율 저하 | `product_cache_hits_total`, `product_cache_misses_total` | Redis cache-aside 효과 저하와 DB 부하 증가 가능성 감지 |
| notification 실패/지연 | `notification_send_failed_total`, `notification_processing_latency_ms` | 이벤트 소비/알림 처리 실패와 지연 감지 |
| NATS 연결 끊김 | `notification-service /health.nats_connected=false` 또는 관련 로그 | 비동기 이벤트 소비 불가 감지 |
| OTel 수집 중단 | `absent_over_time()` 기반 서비스 핵심 메트릭 미수집 | 관찰성 파이프라인 장애 감지 |

#### 설계 의도

- 알림 레이블에는 `order_id`, `user_id`, `payment_id` 같은 고카디널리티 값을 넣지 않는다.
- Alertmanager receiver는 Slack Incoming Webhook을 사용한다. 실제 webhook URL은 Git에 커밋하지
  않고 Helm 배포 시 `--set-file alertmanager.config.global.slack_api_url=...`로 주입한다.
- 알림은 `docs/references/alerting-reference.md`에 임계값, receiver, troubleshooting 기준을 남긴다.
- 운영자 UI는 Grafana를 사용하되, 알림 판정의 기준은 Prometheus/Alertmanager 규칙으로 둔다.

### 6.2 Phase 14 — CI

#### 역할

GitHub Actions CI는 PR 단계에서 의존성 pin, Python 테스트, 정적 검사, Docker build,
Kubernetes manifest 조합 가능성, 보안/품질 게이트를 검증한다. CI는 클러스터에 직접 배포하지
않으며, 이미지 push, `kubectl apply`, Helm upgrade, Argo CD sync를 수행하지 않는다.

#### 검증 범위

| 범위 | 기준 |
| ---- | ---- |
| 의존성 | 기존 `validate-pinned-versions.yml`로 `requirements/constraints.txt`의 모든 패키지 버전 pin 검증 |
| Python 서비스 | `api-gateway`, `user-service`, `product-service`, `order-service`, `payment-service`, `notification-service` pytest 실행. Alembic setup 검증은 `requirements/migration.txt`를 설치한 테스트 환경에서 수행 |
| 정적 검사 | 루트 `pyproject.toml` 기준 Ruff/Black 적용, mypy는 `shared`와 서비스별 `app` 패키지를 독립 실행 |
| Docker build | `docker/services.yaml` Compose build로 `web-common-base`, `db-common-base`와 서비스 이미지 build graph 확인 |
| Kubernetes | Secret 원문 없이 `kustomize build k8s/services/overlays/local` 실행 |
| Secret scan | Gitleaks로 repository 전체 secret scan 수행 |
| Dependency CVE | pip-audit로 서비스 테스트 환경과 `requirements/constraints.txt` pin 기준 취약점 검사 |
| Python security | Bandit으로 `services`, `shared`, `scripts` 검사. `tests`, `alembic`은 제외하고 medium 이상을 실패 기준으로 사용 |
| Kubernetes lint | kube-linter로 Kustomize 렌더링 결과 검사 |

#### 설계 의도

- 기존 `validate-pinned-versions.yml`은 유지하고, 종합 PR 검증은 `.github/workflows/ci.yml`로 분리한다.
- workflow 권한은 `contents: read`, `pull-requests: read`로 제한한다. Gitleaks Action은 PR commit 목록
  조회를 위해 pull request read 권한이 필요하다.
- local overlay의 실제 secret 파일은 Git에 커밋하지 않는다. Secret은 고정 이름 참조이므로 CI는
  Secret 원문 없이 Kustomize 렌더링 가능 여부를 검증한다.
- Kustomize build는 kube-linter 입력 manifest 생성 단계에서 한 번만 수행한다. 렌더링 실패도
  `security-gates` job 실패로 드러난다.
- CI 실패 원인과 재현 명령은 `docs/references/ci-reference.md`에 기록한다.
- Docker CI는 개별 Dockerfile만 분리 검증하지 않고 Compose build graph를 기준으로 공통 base 이미지와 서비스 이미지의 연결을 함께 확인한다.
- Alembic은 앱 runtime 이미지에 포함하지 않으며, 마이그레이션 명령과 Alembic 관련 테스트는 host/dev/CI 환경에서 `requirements/migration.txt`를 추가 설치해 실행한다.
- CI는 배포 권한을 갖지 않으며, 배포는 Phase 15의 GitOps 경로에서 처리한다.

### 6.3 Phase 15 — GitOps 중심 CD

#### 역할

Argo CD는 Git에 선언된 Kubernetes overlay를 클러스터의 실제 상태와 동기화한다. GitHub Actions는
이미지 빌드와 태그 갱신까지만 담당하고, `kubectl apply` 또는 Helm 직접 배포는 CI에서 수행하지
않는다. 로컬 학습 환경에서는 WSL2 Ubuntu self-hosted runner가 사설 로컬 registry
`172.25.46.10:32000`에 접근 가능한 배포 runner 역할을 맡는다.

#### 배포 흐름

```text
Pull Request → CI 검증 → merge
→ GitHub Actions self-hosted runner 이미지 빌드/푸시
→ Kubernetes local overlay image tag 갱신 commit
→ Argo CD Application OutOfSync 확인
→ Argo CD manual sync
→ local Kubernetes에 배포
```

#### 운영 인터페이스

| 구성 | 위치 | 기준 |
| ---- | ---- | ---- |
| CD workflow | `.github/workflows/cd-local-gitops.yml` | `main` push, `workflow_dispatch` |
| Runner | WSL2 Ubuntu self-hosted runner | `self-hosted`, `Linux`, `X64` label |
| Image build/push | `docker/services.yaml` | `REGISTRY`, `TAG` 환경변수로 Compose image 이름 제어 |
| Image registry | `172.25.46.10:32000` | `<service-name>:${GITHUB_SHA::12}` |
| Argo CD Application | `gitops/argocd-applications/micro-mart-local.yaml` | `k8s/services/overlays/local`, manual sync |
| Local Secret apply | `scripts/apply_local_k8s_secrets.sh` | Git에 없는 Secret 원문을 고정 이름 Secret으로 선적용 |

#### 설계 의도

- 배포 기준은 클러스터 명령 이력이 아니라 Git 이력이다.
- local overlay는 commit SHA image tag를 사용해 어떤 코드가 배포됐는지 Git 이력으로 추적한다.
- 이미지 빌드와 push는 기존 수동 배포와 같은 `docker/services.yaml`을 사용해 서비스 목록과 image 이름
  규칙이 갈라지지 않게 한다.
- 로컬 registry는 GitHub-hosted runner에서 접근할 수 없으므로 WSL2 Ubuntu self-hosted runner를 사용한다.
- CD workflow는 main 배포 작업을 concurrency group으로 직렬화하고, overlay tag commit 직전
  최신 `origin/main`을 rebase한 뒤 image tag를 다시 설정한다.
- local overlay는 Secret 원문을 Git에 포함하지 않는다. Argo CD가 참조할 Secret은
  `bash scripts/apply_local_k8s_secrets.sh`로 `micro-mart-local` namespace에 먼저 생성한다.
- 로컬 Chaos Mode와 부하 테스트에서는 환경변수 변경을 원하는 시점에 반영해야 하므로 Argo CD automated
  sync를 켜지 않고 manual sync를 기본으로 둔다.
- local/staging/prod overlay를 분리해 환경별 ConfigMap, Secret 참조 방식, image tag, resource 정책을 관리한다.
- sync drift가 발생하면 Argo CD diff로 원인을 확인하고 Git 기준 상태로 복구한다.
- main merge 직후에는 CD workflow가 commit SHA image tag 갱신 commit을 성공시킨 뒤 manual sync한다.
- 내부 전용 서비스는 GitOps 배포 후에도 Gateway API로 직접 노출하지 않는다.

### 6.4 Phase 16 — AWS Cloud Architecture + Terraform

#### 역할

Terraform은 학습용 최소형 AWS EKS 환경을 재현 가능하게 만든다. 애플리케이션 서비스는 Kubernetes
manifest와 GitOps 흐름을 유지하고, 클라우드 리소스는 Terraform state로 관리한다.

#### 기본 구성

| 구성 | 기본 선택 |
| ---- | --------- |
| Kubernetes | EKS + managed node group |
| 네트워크 | VPC, public/private subnet, NAT 구성은 비용을 고려해 단계적으로 결정 |
| DB | RDS PostgreSQL, 서비스별 database 분리 |
| Redis | ElastiCache Redis |
| 메시징 | NATS는 EKS 내부 workload로 배포 |
| Secret | AWS Secrets Manager + External Secrets 또는 IRSA 기반 연동 |
| Terraform state | S3 backend + DynamoDB lock |
| 외부 노출 | AWS Load Balancer Controller 또는 Gateway API 연계 |

#### 설계 의도

- 운영형 HA보다 비용을 의식한 학습용 최소형 구성을 기본값으로 둔다.
- Terraform은 인프라 리소스만 관리하고, 애플리케이션 배포는 Phase 15 GitOps가 담당한다.
- cloud 배포 후에도 서비스 간 DB 공유 금지, 내부 API 직접 노출 금지, secret 하드코딩 금지 원칙을 유지한다.

---

## 7. 문서 운영 원칙

- 구현 완료된 서비스는 실제 코드와 문서를 함께 갱신한다.
- 예정 서비스는 엔드포인트 계약이 바뀌면 먼저 이 문서를 수정한다.
- README는 요약본, 이 문서는 구현 기준서로 유지한다.
- 이 문서는 구현 로드맵이 아니라 서비스 기능과 호출 계약의 기준서로 유지한다.
- 코드 컨벤션 기준은 `dev_convention.md`를 따른다.
- 운영/배포 phase는 애플리케이션 API 계약을 바꾸지 않으면 별도 운영 기능 섹션과 References 문서에
  반영한다.
