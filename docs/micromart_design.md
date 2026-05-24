# MicroMart — 시스템 설계 문서

> Kubernetes 기반 관찰성 스택(Prometheus, Grafana, Loki, Tempo) 학습용
> 이커머스 주문 관리 마이크로서비스 애플리케이션

---

## 1. 프로젝트 개요

### 목적

LGTM(Loki, Grafana, Tempo, Prometheus) 관찰성 스택을 깊이 학습하기 위한 대상 애플리케이션이다. 서비스 간 연쇄 호출, 비동기 메시지, 의도적 장애 주입(Chaos Mode)을 통해 분산 트레이싱·메트릭·로그 수집의 실제 시나리오를 경험한다.

### 기술 스택

| 항목 | 선택 | 이유 |
| ------ | ------ | ------ |
| 언어 / 프레임워크 | Python 3.12 + FastAPI 0.136.1 | 코드량 최소화, OpenTelemetry SDK 성숙도 높음 |
| 데이터 검증 / 설정 | Pydantic 2.13.4 + pydantic-settings 2.14.0 | 요청/응답 검증, 환경변수 타입 검증 |
| ASGI 기반 | Starlette 1.0.1 | FastAPI 기반 ASGI 런타임 |
| ORM | SQLAlchemy 2.0 async | 비동기 DB 세션, Mapped 타입 안전성 |
| DB 마이그레이션 | Alembic 1.18.4 | 서비스별 PostgreSQL schema 변경 이력 관리 |
| 로깅 | structlog 25.5.0 | JSON 구조화 로그, traceId/spanId 자동 주입 |
| 데이터베이스 | PostgreSQL 16 (서비스별 DB 분리) | MSA 원칙 준수, 서비스 간 DB 공유 금지 |
| 캐시 | Redis 7.4.x (redis.asyncio) | Refresh Token 저장, product-service Cache-Aside |
| 메시지 큐 | NATS | 경량, Kubernetes 네이티브, 비동기 트레이스 전파 실습 |
| HTTP 클라이언트 | httpx | 비동기, OTel 자동 계측, 서비스 간 호출 및 리버스 프록시 |
| Rate Limiting | SlowAPI | IP 기반, FastAPI 통합 용이, 인메모리 저장소 |
| JWT 검증 | PyJWT + cryptography | RS256 공개키 검증, python-jose 대비 유지보수 활성화 |
| 관찰성 SDK | OpenTelemetry 1.41.1 / instrumentation 0.62b1 | OTLP trace/metric/log 수집, FastAPI/SQLAlchemy/httpx 자동 계측 |
| 컨테이너 | Docker | 서비스별 독립 Dockerfile |
| 오케스트레이션 | Kubernetes | 관찰성 스택 Helm 배포 환경 |
| 부하 생성 | k6 | 시나리오 스크립트, Grafana 연동 |

---

## 2. 서비스 구성

### 전체 아키텍처

```mermaid
flowchart LR
    K6["🖥 Client / k6"]
    GW["api-gateway :8000\nJWT 검증 · 라우팅"]

    subgraph SERVICES["Application Services"]
        US["user-service :8001\n회원가입 · JWT · Refresh Token"]
        PS["product-service :8002\n상품 CRUD · Redis Cache · 재고 차감"]
        OS["order-service :8003 ★\n주문 · 오케스트레이션"]
        PAY["payment-service :8004\nPG 시뮬 · Chaos Mode"]
        NS["notification-service\nNATS 소비 · 알림 발송"]
    end

    subgraph MQ["Message Queue"]
        NATS(["NATS"])
    end

    subgraph OBS["Observability"]
        direction LR
        OTEL["OTel Collector"]
        TEMPO["Tempo"]
        PROM["Prometheus"]
        ALERT["Alertmanager"]
        LOKI["Loki"]
        GRAF["📊 Grafana"]
    end

    subgraph DELIVERY["Delivery / Cloud"]
        GHA["GitHub Actions\nCI · 이미지 빌드"]
        ARGO["Argo CD\nGitOps Sync"]
        TF["Terraform\nAWS IaC"]
        AWS["AWS EKS\nRDS · ElastiCache"]
    end

    K6 --> GW
    GW --> US & PS & OS

    OS -->|재고 차감| PS
    OS -->|결제 요청| PAY
    OS -->|order.completed| NATS
    NATS --> NS

    SERVICES -- OTLP --> OTEL
    OTEL --> TEMPO & PROM & LOKI
    PROM --> ALERT
    TEMPO & PROM & LOKI --> GRAF
    GHA --> ARGO
    ARGO --> AWS
    TF --> AWS
```

### 서비스별 상세

#### api-gateway (포트 8000) ✅ 구현 완료

- **역할**: 단일 진입점, RS256 JWT 로컬 검증, 라우팅(리버스 프록시), Rate Limiting, 요청/응답 로깅, 관찰성 메트릭
- **DB**: 없음 (stateless)
- **파일 구성**:
  - `main.py` — FastAPI 앱, lifespan(JWKS 워밍업), 미들웨어 등록 순서 관리
  - `config.py` — JWKS URL, JWT 설정, Rate Limit, HTTP 타임아웃 등
  - `router.py` — catch-all HTTP 경계, Rate Limit, 미등록 경로 404
  - `services/proxy_service.py` — 경로 prefix 기반 라우팅, hop-by-hop 헤더 제거, TraceContext 전파, httpx 예외 매핑
  - `middleware/auth.py` — JWKSCache 클래스, verify_jwt, is_public_path
  - `middleware/metrics.py` — OTel Counter/Histogram 메트릭 정의
  - `middleware/rate_limit.py` — SlowAPI Limiter 설정
- **미들웨어 실행 순서** (add_middleware 역순 실행):

  ```text
  ① SlowAPIMiddleware    — Rate Limit 체크 (가장 먼저)
  ② AuthMiddleware       — JWT 검증, X-User-ID/Role 헤더 주입
  ③ MetricsMiddleware    — 레이턴시 측정 (인증 실패 포함 모든 요청)
  ④ RequestLoggingMiddleware — 요청/응답 구조화 로그 (가장 바깥)
  ```

- **공개 경로(익명 접근 허용)**:
  - `(ANY) /health` — k8s liveness probe
  - `(ANY) /auth/*` — 로그인·회원가입·토큰 재발급
  - `(GET) /products` 및 `GET /products/*` — 비인증 상품 조회
- **public optional auth**:
  - 모든 요청에서 클라이언트가 보낸 `X-User-ID`, `X-User-Role`은 먼저 제거한다.
  - `GET /products` 계열은 Bearer 토큰이 없으면 익명으로 통과한다.
  - `GET /products` 계열에 Bearer 토큰이 있으면 검증하고, 성공 시에만 사용자 헤더를 주입한다.
  - 상품 조회의 Bearer 토큰 검증 실패는 익명 요청으로 낮추지 않고 `401`로 반환한다.
  - `/auth`는 토큰 재발급·로그아웃 흐름을 user-service가 판단해야 하므로 gateway JWT 검증을 건너뛴다.
- **JWKS 캐시 설계**:
  - 최초 요청 또는 TTL 만료 시 user-service `/auth/jwks` 조회
  - 기본 TTL: 3600초 (환경변수 `JWKS_CACHE_TTL_SECONDS`로 조정)
  - kid 미매칭 시에도 JWKS 재조회 (키 로테이션 대응)
  - `asyncio.Lock`으로 동시 재조회 요청 직렬화 (thundering herd 방지)
  - 앱 시작 시 lifespan에서 캐시 워밍업 (첫 요청 레이턴시 스파이크 방지)
- **라우팅 규칙**:
  - `/auth` 또는 `/auth/*` → user-service
  - `/products` 또는 `/products/*` → product-service
  - `/orders` 또는 `/orders/*` → order-service
  - 미등록 경로 → `404 NOT_FOUND`
- **관찰성 포인트**:

| 메트릭 이름 | 타입 | 레이블 | 설명 |
| ----------- | ---- | ------ | ---- |
| `gateway_requests_total` | Counter | `method`, `path_group`, `status_code` | 전체 인바운드 요청 수 |
| `gateway_request_duration_ms` | Histogram | `method`, `path_group` | 요청 처리 레이턴시 (ms) |
| `gateway_auth_total` | Counter | `result` (success\|no_token\|failure) | JWT 검증 결과 |
| `gateway_auth_failure_total` | Counter | `reason` (expired\|invalid\|jwks_error) | JWT 검증 실패 상세 |
| `gateway_jwks_cache_total` | Counter | `result` (hit\|miss) | JWKS 캐시 히트율 |
| `gateway_rate_limit_total` | Counter | `path_group` | Rate Limit 차단 횟수 |

- **path_group 카디널리티 관리**: `/products/12345` → `/products/{id}` 로 그루핑. Prometheus 레이블에 실제 ID가 들어가면 시계열 폭발 발생.

#### user-service (포트 8001)

- **역할**: 회원가입, 로그인, JWT 발급(RS256), Refresh Token Rotation, token_version 관리
- **DB**: `user-db` (PostgreSQL)
- **Redis**:
  - `refresh:user:{id}:{device}` — 정방향 키 (user_id→token)
  - `refresh:token:{token}` — 역방향 키 (token→user_id, 재사용 감지용 tombstone)
  - `user:{id}:token_version` — 강제 로그아웃 버전 관리
- **관찰성 포인트**: 로그인 성공/실패 카운터(`login_total`), 신규 가입 카운터(`register_total`), 토큰 재발급 카운터(`token_refresh_total`)
- **엔드포인트**:
  - `POST /auth/register` — 회원가입
  - `POST /auth/login` — 로그인 (Access Token + Refresh Token 발급)
  - `POST /auth/refresh` — Access Token 재발급 (Refresh Token Rotation)
  - `POST /auth/logout` — 로그아웃 (기기별 Refresh Token 삭제)
  - `GET  /auth/jwks` — RS256 공개키 반환 (api-gateway 캐싱용)
- **구조**: 라우터는 `routes/auth.py`, 비즈니스 로직은 `services/auth_service.py`, 요청/응답 스키마는 `schemas.py`로 분리

#### product-service (포트 8002)

- **역할**: 상품 카탈로그와 재고를 담당. 공개 조회 API와 관리자용 CRUD, 그리고 `order-service`가 호출하는 내부 재고 차감/복구 API를 제공.
- **DB**: `product-db` (PostgreSQL) + `product-cache` (Redis, Cache-Aside 패턴)
- **낙관적 잠금**: 재고 차감 시 `version` 필드로 동시 요청 충돌 감지, `409 VERSION_CONFLICT` 반환
- **관찰성 포인트**: 캐시 히트율(`product_cache_hits_total` / `misses_total`), 재고 부족 이벤트(`product_stock_insufficient_total`), 낙관적 잠금 충돌(`product_stock_conflict_total`)
- **엔드포인트**:
  - `GET  /products` — 상품 목록 (페이지네이션, active_only 필터)
  - `GET  /products/{id}` — 상품 상세 (Cache-Aside)
  - `POST /products` — 상품 등록 (admin 전용)
  - `PUT  /products/{id}` — 상품 수정 (admin 전용, 캐시 무효화)
  - `DELETE /products/{id}` — 소프트 삭제 (admin 전용)
  - `POST /products/{id}/deduct-stock` — 재고 차감 (내부 서비스 전용, `X-Internal-Token` 인증)
  - `POST /products/{id}/restore-stock` — 재고 복구 보상 트랜잭션 (내부 서비스 전용, `X-Internal-Token` 인증)
- **구조**: `routes/products.py`는 HTTP 경계만 담당하고, Cache-Aside·권한 분기·재고 로직은 `services/product_service.py`에 둔다.

#### order-service (포트 8003) ⭐ 핵심 서비스

- **역할**: 주문 생성·조회, product-service 재고 차감 호출, payment-service 결제 호출, NATS 이벤트 발행
- **DB**: `order-db` (PostgreSQL)
- **Redis**: 사용하지 않음 (Redis 설정 없음)
- **NATS**: `order.completed` 이벤트 발행 — best-effort (발행 실패 시 주문은 `COMPLETED` 유지, 로그 기록)
- **핵심 설계**: Orchestration Saga 패턴으로 단계별 상태(`saga_status`)와 보상 트랜잭션을 관리
- **ERD**: `orders`, `order_items` 테이블 사용. 상품명·단가를 주문 시점 스냅샷으로 저장
- **관찰성 포인트**:
  - `order_created_total` — 주문 생성 요청 총 횟수
  - `order_completed_total` — 주문 완료 횟수
  - `order_failed_total` — 주문 실패 횟수 (`reason` 레이블)
  - `order_amount_krw` — 주문 금액 분포 히스토그램 (원단위)
  - `saga_stock_rollback_total` — 재고 롤백 보상 트랜잭션 횟수
- **엔드포인트**:
  - `POST /orders` — 주문 생성 (Saga 오케스트레이션, `X-User-ID` 헤더)
  - `GET  /orders` — 내 주문 목록 (페이지네이션, 최신순)
  - `GET  /orders/{id}` — 주문 상세 (items 포함, IDOR 방어)
  - `GET  /health` — 헬스체크 (NATS 연결 상태 포함)
- **낙관적 잠금 재시도**: `VERSION_CONFLICT` 시 상품 재조회 후 최대 `max_optimistic_retry`(기본 3)회 재시도

#### payment-service (포트 8004)

- **역할**: 외부 PG를 흉내 내는 결제 시뮬레이터. 결제 승인/거절, 지연, 장애 주입, 환불 처리. 모든 엔드포인트는 `X-Internal-Token` 인증이 필수인 내부 전용 API.
- **DB**: `payment-db` (PostgreSQL)
- **ERD**: `payments`, `refunds` 테이블 사용. `payments.order_id`는 UNIQUE로 중복 결제 방지
- **관찰성 포인트**:
  - `payment_total` — 결제 요청 총 횟수
  - `payment_approved_total` — 결제 승인 횟수
  - `payment_rejected_total` — 결제 거절 횟수 (Chaos Mode 포함, `reason` 레이블)
  - `payment_amount_krw` — 결제 금액 분포 히스토그램 (원단위)
  - `payment_processing_latency_ms` — 결제 처리 레이턴시 히스토그램 (ms)
  - `refund_total` — 환불 요청 총 횟수
- **엔드포인트**:
  - `POST /payments` — 결제 요청 (내부 전용, 중복 결제 앱+DB 이중 차단)
  - `GET  /payments/{id}` — 결제 상태 조회 (내부 전용)
  - `POST /payments/{id}/refunds` — 환불 요청 (부분 환불 지원, 내부 전용)
- **헬스체크**: `GET /health` — Chaos Mode 설정 상태 포함 응답
- **구조**: `routes/payments.py`는 `X-Internal-Token` 보호와 응답 모델만 담당하고, 상태 전이·Chaos Mode·메트릭은 `services/payment_service.py`에 둔다.

**Chaos Mode 환경변수:**

```text
CHAOS_FAILURE_RATE=0.3  # 30% 확률로 결제 실패
CHAOS_LATENCY_MS=2000   # 결제 응답 2초 지연
CHAOS_DB_SLOWQUERY=true # DB 슬로우쿼리 시뮬레이션
```

#### notification-service

- **역할**: NATS `order.completed` 이벤트 소비, 주문 완료 알림 발송 시뮬레이션
- **DB/Redis**: 없음 (stateless consumer)
- **NATS**: core NATS `order.completed` 구독. 연결 실패 시에도 앱은 기동하고 `/health.nats_connected=false`로 노출.
- **헬스체크**: `GET /health` — 서비스 상태, NATS 연결 상태, 구독 subject 반환
- **관찰성 포인트**:
  - `notification_message_consumed_total` — NATS 메시지 소비 횟수
  - `notification_send_success_total` — 발송 시뮬레이션 성공 횟수
  - `notification_send_failed_total` — invalid JSON/payload, 시뮬레이션 실패, 예상치 못한 오류 횟수
  - `notification_processing_latency_ms` — 메시지 처리 전체 지연
  - `notification_send_latency_ms` — 발송 시뮬레이션 지연
- **범위 제외**: 실제 이메일/SMS provider, 알림 이력 DB, user-service 연락처 조회, JetStream durable consumer, DLQ, retry queue

---

## 3. 핵심 데이터 플로우 — 주문 생성

```text
Client → api-gateway POST /orders (JWT 포함)
api-gateway → (JWT 검증, Rate Limit 체크)
api-gateway → order-service X-User-ID 헤더 + traceId 전파
order-service → product-service 상품 정보 조회 (GET /products/{id})
order-service → order-db 주문/주문항목 생성 (PENDING / STARTED)
order-service → product-service 재고 차감 (POST /products/{id}/deduct-stock, X-Internal-Token)
order-service → payment-service 결제 요청 (POST /payments, X-Internal-Token)
payment-service → order-service 결제 승인/거절 응답
order-service → 실패 시 재고 롤백 (POST /products/{id}/restore-stock), 성공 시 주문 상태 COMPLETED 커밋
order-service → NATS order.completed 이벤트 발행 (best-effort)
NATS → notification-service 이벤트 소비, 알림 발송 시뮬레이션
```

Tempo는 전체 구간을 단일 트레이스로 표현하고, 각 서비스는 개별 Span으로 시각화된다.

### Saga 상태 전이

```text
STARTED
  → STOCK_DEDUCTED    (stock_deducted = True 커밋)
  → PAYMENT_REQUESTED
  → COMPLETED

결제 실패 시:
STARTED
  → STOCK_DEDUCTED
  → PAYMENT_REQUESTED
  → STOCK_ROLLBACK_NEEDED   (즉시 커밋 — 배치 복구 대상 스캔 근거)
  → STOCK_ROLLED_BACK       (롤백 성공)
     OR STOCK_ROLLBACK_NEEDED (롤백 실패, best-effort 유지)
  → FAILED
```

---

## 4. 인증 설계

- **패턴**: Short Access Token + Refresh Token + Token Versioning
- **알고리즘**: RS256 (개인키는 user-service만 보유, 공개키는 api-gateway 캐싱)

### 토큰 구성

| 토큰 | TTL | 저장 위치 |
| ------ | ----- | ----------- |
| Access Token | 15분 | 클라이언트 메모리 또는 HttpOnly Cookie |
| Refresh Token | 7일 | Redis (서버), HttpOnly Cookie (클라이언트) |

### Redis 저장 구조

```text
refresh:user:{id}:{device} → 정방향 키 (user_id→token), Refresh Token 값 (기기별 세션)
refresh:token:{token} → 역방향 키 (token→user_id, 재사용 감지용 tombstone)
user:{id}:token_version → 버전 번호
```

### 이벤트별 처리

| 이벤트 | 처리 |
| -------- | ------ |
| 일반 로그아웃 | 해당 기기 Refresh Token 키 삭제 |
| Refresh Token 재사용 감지 | 해당 유저의 모든 세션 즉시 강제 종료 |
| 비밀번호 변경 / 강제 차단 | `token_version` +1, 모든 기기 Refresh Token 삭제 |

### api-gateway JWT 검증 흐름

```text
1. 요청 진입 시 X-User-ID, X-User-Role 제거
2. `/auth`, `/health` 공개 경로 → gateway JWT 검증 없이 통과
3. `GET /products` + Bearer 토큰 없음 → 익명 요청으로 통과
4. 보호 경로 + Bearer 토큰 없음 → 401 반환
5. 검증 대상 경로에 Bearer 토큰이 있으면 jwt.get_unverified_header()로 kid 추출 (네트워크 요청 없음)
6. JWKSCache.get_public_key(kid)
   ├─ 캐시 유효 + kid 존재 → 즉시 반환 (캐시 히트)
   └─ 캐시 만료 또는 kid 없음 → user-service /auth/jwks 재조회 (캐시 미스)
7. PyJWT로 서명 + 만료 검증
8. 성공: X-User-ID, X-User-Role 헤더 주입 후 하위 서비스로 전달
9. 실패: 401 반환 (reason: expired|invalid|jwks_error)
```

---

## 5. 데이터 모델 설계

상세 스키마는 `ERD_structure.md`를 기준 문서로 사용한다.

### 핵심 설계 원칙

- 서비스별 DB 분리, 서비스 간 물리적 FK 금지
- DB schema 변경 이력은 DB 보유 서비스별 Alembic migration으로 관리
- 주문 데이터는 스냅샷 저장(`product_name`, `unit_price`, `total_amount`)
- 재고 차감은 낙관적 잠금(`version`) 사용
- 결제는 `payments.order_id UNIQUE`로 멱등성 보장
- 환불은 `refunds` 테이블로 분리하여 부분 환불 확장 가능

### 주문 관련 테이블

- `orders`: 주문 헤더, 사용자 ID, 결제 ID, 주문 상태, Saga 상태, 실패 원인 저장
- `order_items`: 주문 항목, 상품 스냅샷, 할인 금액, 소계 저장

### 결제 관련 테이블

- `payments`: 결제 레코드, 승인/거절 상태, PG 트랜잭션 ID, 처리 시각 저장
- `refunds`: 환불 레코드, 부분 환불 금액, 환불 상태 저장

---

## 6. 관찰성 계측 패턴

### OpenTelemetry 초기화 (모든 서비스 공통)

```python
# 트레이싱: OTLP → OTel Collector → Tempo
# 메트릭: OTLP → OTel Collector → Prometheus Remote Write
# 로깅: structlog JSON → OTel LogRecord → OTel Collector → Loki
```

### Kubernetes 관찰성 배포 흐름

Kubernetes 로컬 환경에서는 애플리케이션 서비스가 OTLP gRPC(`4317`)로
`otel-collector.micro-mart.svc.cluster.local`에 trace, metric, log를 전송한다.
OTel Collector는 Helm values 설정에 따라 trace는 Tempo, metric은 Prometheus Remote Write,
log는 Loki OTLP endpoint로 전달한다. Grafana는 Prometheus, Loki, Tempo datasource를
프로비저닝하여 메트릭, 로그, 트레이스를 한 화면에서 조회한다.

### Alerting / Delivery / Cloud 확장 방향

Phase 13 이후의 운영 확장은 애플리케이션 API를 늘리는 대신 배포와 관찰성 경계를 강화한다.
Alertmanager는 Prometheus 알림 규칙을 받아 결제 지연/실패율, gateway 5xx와 인증 실패, rate
limit 급증, 주문 실패율과 완료율 저하, Saga 보상 트랜잭션 증가, 상품 재고 경합, 캐시 미스율 증가,
notification 실패/지연, OTel 수집 중단을 Slack으로 알린다. NATS 연결 끊김은 현재 별도 Prometheus
metric 없이 notification-service `/health.nats_connected=false`와 Loki warning 로그로 확인한다.
GitHub Actions는 테스트와 이미지 빌드 검증을 담당한다. Phase 15의 로컬 CD workflow는 WSL2 Ubuntu
self-hosted runner에서 이미지를 `172.25.46.10:32000` registry로 push하고 local overlay image tag를
commit SHA로 갱신한다. Argo CD는 Git에 선언된 Kubernetes overlay를 클러스터 상태와 동기화하되,
로컬 환경에서는 Chaos 테스트 배포 타이밍을 통제하기 위해 manual sync를 기본으로 둔다. AWS 배포는 Terraform으로 VPC, EKS, RDS PostgreSQL, ElastiCache Redis,
Secret 관리, Terraform remote backend를 구성하는 학습용 최소형 EKS 아키텍처를 기본값으로 한다.

### Loki 로그 필드

```json
{
  "timestamp": "2026-05-02T10:00:00Z",
  "level": "error",
  "service": "order-service",
  "trace_id": "abc123",
  "span_id": "def456",
  "user_id": "123",
  "event": "payment_failed",
  "message": "결제 서비스 응답 없음"
}
```

`trace_id` 필드로 Grafana에서 Loki 로그 → Tempo 트레이스로 바로 점프 가능하다.

---

## 7. 관찰성 학습 시나리오

| 시나리오 | 트리거 | 관찰 방법 |
| ---------- | -------- | ----------- |
| 결제 서비스 간헐적 실패 | `CHAOS_FAILURE_RATE=0.5` | Tempo 에러 트레이스 + Loki 에러 로그 |
| 결제 서비스 지연 | `k6/scenarios/payment_latency_chaos_order_flow.js` + `CHAOS_LATENCY_MS=3000` | Grafana P99 급등 + 알럿 발동 |
| 결제 실패 보상 트랜잭션 | `k6/scenarios/payment_failure_chaos_order_flow.js` + `CHAOS_FAILURE_RATE` | `saga_stock_rollback_total`, `payment_rejected_total` 증가 |
| 재고 부족 | 상품 재고 소진 | order-service 비즈니스 에러 메트릭 |
| 낙관적 잠금 충돌 | `k6/scenarios/stock_contention_order_flow.js`로 단일 상품에 동시 주문 요청 | `product_stock_conflict_total` 메트릭 급등 |
| 인증 실패 / Rate Limit | `k6/scenarios/auth_rate_limit_flow.js` | `gateway_auth_failure_total`, `gateway_rate_limit_total` 증가 |
| 조회 혼합 트래픽 | `k6/scenarios/mixed_read_order_flow.js` | path group별 gateway latency와 product cache hit/miss 비교 |
| DB 커넥션 풀 고갈 | product-service 부하 증가 | DB pool 메트릭 + 연쇄 에러 트레이스 |
| 알림 소비 지연 | `NOTIFICATION_SEND_DELAY_MS` 증가 | `notification_processing_latency_ms`, `notification_send_latency_ms` 상승 |
| 알림 발송 실패 | `NOTIFICATION_FAILURE_RATE` 증가 | `notification_send_failed_total{reason="SIMULATED_SEND_FAILURE"}` 증가 + Loki warning 로그 |
| 알림 payload 오류 | 잘못된 `order.completed` 메시지 발행 | `notification_send_failed_total{reason="INVALID_JSON\|INVALID_PAYLOAD"}` 증가 |
| Saga 보상 트랜잭션 | 결제 거절 발생 | `saga_stock_rollback_total` 증가 + Tempo 롤백 스팬 |
| Rate Limit 발동 | 고빈도 요청 | `gateway_rate_limit_total` + 429 응답율 급등 |
| JWT 위조/만료 | 잘못된 토큰 전달 | `gateway_auth_failure_total{reason="expired\|invalid"}` |
| JWKS 캐시 미스 | user-service 재기동 또는 키 로테이션 | `gateway_jwks_cache_total{result="miss"}` 증가 |
| 알럿 발동 | 결제 지연/실패율, gateway 5xx/인증 실패, 주문 실패율/완료율, 재고 경합, 캐시 미스율, notification 실패, OTel 수집 중단 | Prometheus alert rule → Alertmanager Slack receiver → Grafana 대시보드 패널 확인 |
| CI 실패 | 테스트 실패, 버전 pin 누락, Ruff/Black/mypy 실패, Docker build 실패, kustomize build 실패, secret/CVE/security lint 실패 | GitHub Actions job 로그와 실패 단계 확인 |
| GitOps sync drift | 클러스터에서 수동으로 Deployment/ConfigMap 변경 | Argo CD OutOfSync 상태와 diff 확인 후 Git 기준으로 복구 |
| AWS 배포 관찰 | Terraform으로 EKS/RDS/ElastiCache 배포 후 서비스 트래픽 발생 | CloudWatch/EKS 상태, Grafana 대시보드, 서비스 health probe 확인 |

---

## 8. 프로젝트 디렉토리 구조

```text
micro-mart/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   ├── PULL_REQUEST_TEMPLATE/
│   └── workflows/
│       ├── cd-local-gitops.yml
│       ├── ci.yml
│       └── validate-pinned-versions.yml
├── services/
│   ├── api-gateway/
│   │   ├── app/
│   │   │   ├── __init__.py
│   │   │   ├── main.py           # FastAPI 앱, lifespan, 미들웨어 등록 순서
│   │   │   ├── config.py         # JWKS URL, JWT 설정, Rate Limit, HTTP 타임아웃
│   │   │   ├── router.py         # catch-all HTTP 경계, Rate Limit
│   │   │   ├── middleware/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── auth.py       # JWKSCache, verify_jwt, is_public_path
│   │   │   │   ├── metrics.py    # OTel 메트릭 정의 (Counter/Histogram)
│   │   │   │   └── rate_limit.py # SlowAPI Limiter
│   │   │   └── services/
│   │   │       ├── __init__.py
│   │   │       └── proxy_service.py
│   │   ├── tests/
│   │   │   ├── __init__.py
│   │   │   ├── conftest.py       # RS256 키쌍 생성, JWKS mock 헬퍼
│   │   │   ├── test_health.py
│   │   │   ├── test_auth.py      # JWT 검증, 캐시 히트/미스, 만료/위조 케이스
│   │   │   └── test_routing.py   # 경로별 라우팅, 쿼리 전달, 에러 전파
│   │   ├── .env.example
│   │   ├── pytest.ini
│   │   └── requirements.txt
│   ├── user-service/
│   │   ├── alembic/
│   │   │   ├── env.py
│   │   │   └── versions/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   ├── models.py
│   │   │   ├── schemas.py
│   │   │   ├── auth.py
│   │   │   ├── routes/
│   │   │   │   └── auth.py
│   │   │   └── services/
│   │   │       └── auth_service.py
│   │   ├── Dockerfile
│   │   ├── .env.example
│   │   ├── alembic.ini
│   │   └── requirements.txt
│   ├── product-service/
│   │   ├── alembic/
│   │   │   ├── env.py
│   │   │   └── versions/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   ├── dependencies.py
│   │   │   ├── models.py
│   │   │   ├── schemas.py
│   │   │   ├── cache.py
│   │   │   ├── routes/
│   │   │   │   └── products.py
│   │   │   └── services/
│   │   │       └── product_service.py
│   │   ├── Dockerfile
│   │   ├── .env.example
│   │   ├── alembic.ini
│   │   └── requirements.txt
│   ├── payment-service/
│   │   ├── alembic/
│   │   │   ├── env.py
│   │   │   └── versions/
│   │   ├── app/
│   │   │   ├── __init__.py
│   │   │   ├── main.py
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   ├── models.py
│   │   │   ├── schemas.py
│   │   │   ├── dependencies.py
│   │   │   ├── routes/
│   │   │   │   └── payments.py
│   │   │   └── services/
│   │   │       └── payment_service.py
│   │   ├── tests/
│   │   │   ├── conftest.py
│   │   │   └── test_payments.py
│   │   ├── .env.example
│   │   ├── alembic.ini
│   │   ├── pytest.ini
│   │   └── requirements.txt
│   ├── order-service/
│   │   ├── alembic/
│   │   │   ├── env.py
│   │   │   └── versions/
│   │   ├── app/
│   │   │   ├── __init__.py
│   │   │   ├── main.py
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   ├── models.py
│   │   │   ├── schemas.py
│   │   │   ├── dependencies.py
│   │   │   ├── nats_client.py
│   │   │   ├── routes/
│   │   │   │   └── orders.py
│   │   │   └── services/
│   │   │       ├── http_clients.py
│   │   │       └── order_service.py
│   │   ├── tests/
│   │   ├── .env.example
│   │   ├── alembic.ini
│   │   ├── pytest.ini
│   │   └── requirements.txt
│   └── notification-service/
│       ├── app/
│       │   ├── __init__.py
│       │   ├── main.py
│       │   ├── config.py
│       │   ├── schemas.py
│       │   ├── nats_client.py
│       │   └── services/
│       │       ├── __init__.py
│       │       └── notification_service.py
│       ├── tests/
│       ├── Dockerfile
│       ├── .env.example
│       ├── pytest.ini
│       └── requirements.txt
├── shared/
│   ├── __init__.py
│   └── telemetry/
│       ├── __init__.py
│       ├── setup.py
│       ├── config.py
│       ├── middleware.py
│       ├── custom_logging.py
│       ├── test_telemetry.py
│       └── requirements.txt
├── scripts/
│   ├── generate_keys.py
│   ├── image_build_push.bat
│   ├── apply_local_k8s_secrets.sh
│   └── validate_pinned_versions.py
├── docker/
│   ├── init-scripts/
│   │   └── init-db.sql
│   ├── infra.yaml
│   ├── observability.yaml
│   ├── services.yaml
│   └── .env.example
├── k8s/
│   ├── README.md
│   ├── argocd/
│   │   ├── README.md
│   │   ├── argocd-values.yaml
│   │   ├── argocd-gateway.yaml
│   │   └── argocd-http-route.yaml
│   ├── db/
│   │   ├── README.md
│   │   ├── postgresql-config.yaml.example
│   │   └── redis.yaml
│   ├── gateway/
│   │   ├── README.md
│   │   ├── micro-mart-gateway.yaml
│   │   ├── micro-mart-httproute.yaml
│   │   ├── grafana-gateway.yaml
│   │   └── grafana-httproute.yaml
│   ├── metallb/
│   │   ├── README.md
│   │   ├── ip-address-pool.yaml
│   │   └── l2-advertisement.yaml
│   ├── namespaces/
│   │   └── namespace.yaml
│   ├── nats/
│   │   └── nats.yaml
│   ├── observability/
│   │   ├── README.md
│   │   ├── grafana-values.yaml
│   │   ├── loki-values.yaml
│   │   ├── otel-collector-values.yaml
│   │   ├── prometheus-values.yaml
│   │   └── tempo-values.yaml
│   └── services/
│       ├── base/
│       │   ├── api-gateway/
│       │   ├── user-service/
│       │   ├── product-service/
│       │   ├── order-service/
│       │   ├── payment-service/
│       │   ├── notification-service/
│       │   └── kustomization.yaml
│       └── overlays/
│           └── local/
│               ├── config/
│               ├── secrets/
│               ├── namespace.yaml
│               └── kustomization.yaml
├── gitops/
│   └── argocd-applications/
│       └── micro-mart-local.yaml
├── docs/
│   ├── dev_convention.md
│   ├── service_function_definition.md
│   ├── micromart_design.md
│   ├── ERD_structure.md
│   ├── postman/
│   │   └── micromart_postman_collection.json
│   └── references/
│       ├── init-develop-environment.md
│       ├── shared-telemetry-reference.md
│       ├── api-gateway.md
│       ├── user-service.md
│       ├── product-service.md
│       ├── order-service.md
│       ├── payment-service.md
│       └── notification-service.md
├── pyproject.toml
├── requirements/
│   ├── constraints.txt
│   ├── service-common.txt
│   └── test-common.txt
├── .pre-commit-config.yaml
└── README.md
```

---

## 9. Kubernetes 배포 구성

로컬 Kubernetes 배포는 애플리케이션, 인프라, 관찰성 스택을 분리해 관리한다.

- 애플리케이션 서비스 6개는 `k8s/services/base/<service>/`에 `Deployment`, `Service`,
  `kustomization.yaml`을 두고, `k8s/services/overlays/local/`에서 ConfigMap, namespace,
  image tag를 조합한다.
- local overlay의 namespace는 `micro-mart-local`이다. base manifest에는 `micro-mart`가
  적혀 있지만 overlay가 최종 namespace를 덮어쓴다.
- local Secret은 Git에 원문을 올리지 않고 `scripts/apply_local_k8s_secrets.sh`로 고정 이름의
  Kubernetes Secret을 먼저 생성한다. Argo CD는 Secret 원문을 생성하지 않고, base Deployment가
  이미 존재하는 Secret 이름을 참조한다.
- local overlay는 기본 수동 배포에서는 `172.25.46.10:32000/<service-name>:local` 이미지 주소를
  사용할 수 있고, Phase 15 CD workflow가 실행되면 `172.25.46.10:32000/<service-name>:<commit-sha>`
  형태로 image tag가 갱신된다. 이미지 registry나 태그를 바꾸면 overlay의 `images` 설정도 함께 바꾼다.
- 각 애플리케이션 Deployment는 `/health`를 liveness/readiness probe로 사용한다.
- 애플리케이션 컨테이너는 non-root UID/GID `10001`로 실행하고,
  `readOnlyRootFilesystem`, privilege escalation 금지, capability drop,
  `seccompProfile: RuntimeDefault`를 기본 보안 기준으로 둔다. 런타임 쓰기 경로는 `/tmp`
  `emptyDir`처럼 명시적 volume으로 제공한다.
- 애플리케이션 컨테이너 리소스는 임시 기준으로 `requests.cpu=50m`,
  `requests.memory=128Mi`, `limits.memory=256Mi`를 둔다. CPU limit은 k6 부하 테스트로
  실제 사용량을 확인한 뒤 결정한다.
- PostgreSQL은 Bitnami Helm chart로 `micro-mart` namespace에 배포한다. chart 설정은
  `userdb`만 기본 생성하므로 `productdb`, `orderdb`, `paymentdb`는 별도 psql 작업으로
  생성한다.
- Redis와 NATS는 로컬 단일 인스턴스 manifest(`k8s/db/redis.yaml`, `k8s/nats/nats.yaml`)로
  `micro-mart` namespace에 배포한다. Redis는 `redis:8.6.3`과 PVC `128Mi`를 사용하고,
  NATS는 `nats:2.14.0`에서 JetStream을 켠 뒤 `/tmp/nats`에 PVC `1Gi`를 연결한다.
- OTel Collector는 `micro-mart` namespace에 Helm으로 배포하고, Prometheus, Grafana, Loki,
  Tempo는 `monitoring` namespace에 Helm values 파일로 배포한다.
- 로컬 외부 노출은 MetalLB와 Envoy Gateway 기반 Gateway API로 구성한다. MetalLB는
  `172.25.46.100-172.25.46.200` 대역을 Layer 2 모드로 광고하고, Envoy Gateway가 생성하는
  LoadBalancer Service에 외부 IP를 할당한다.
- `api-gateway`는 `micro-mart-local` namespace의 `micro-mart-gateway`와
  `micro-mart-http-route`를 통해 외부에서 접근한다. Grafana는 `monitoring` namespace의
  `grafana-gateway`와 `grafana-http-route`를 통해 접근한다.
- Argo CD UI는 `argocd` namespace에서 Helm으로 설치하고, `argocd-gateway`와
  `argocd-http-route`로 HTTPS 노출한다. Gateway TLS에는 Helm chart의 Opaque `argocd-secret`을
  직접 사용하지 않고 `kubernetes.io/tls` 타입 `argocd-gateway-tls` Secret을 별도로 둔다.
- 외부 클라이언트용 애플리케이션 트래픽은 계속 `api-gateway`를 단일 진입점으로 사용한다.
  `payment-service`, `notification-service` 같은 내부 전용 서비스는 Gateway API로 직접
  노출하지 않는다.

---

## 10. 구현 순서

1. ✅ **공통 기반** — `shared/telemetry/`, structlog JSON 설정
2. ✅ **user-service** — JWT 발급, Refresh Token Rotation, token_version 관리
3. ✅ **product-service** — 상품 CRUD, Redis 캐싱, 낙관적 잠금 재고 차감·복구
4. ✅ **payment-service** — 결제 시뮬레이션, Chaos Mode, 부분 환불 구현
5. ✅ **order-service** — 오케스트레이터, Saga 패턴, 서비스 간 호출, NATS 이벤트 발행
6. ✅ **api-gateway** — JWT 검증 미들웨어(JWKS 캐시), 리버스 프록시, Rate Limiting, 관찰성 메트릭
7. ✅ **로컬 통합 Compose** — infra/observability/services 분리 구성
8. ✅ **notification-service** — NATS 소비, 알림 발송 시뮬레이션, 관찰성 메트릭
9. ✅ **Kubernetes 매니페스트** — Deployment, Service, ConfigMap, 고정 Secret 참조, local Kustomize overlay
10. ✅ **k6 부하 스크립트** — Kubernetes local baseline 주문 생성 부하 시나리오 추가
11. ✅ **Kubernetes 외부 노출** — MetalLB, Envoy Gateway, Gateway API로 api-gateway와 Grafana 노출
12. ✅ **서비스별 DB 마이그레이션** — user/product/order/payment-service에 Alembic 초기 revision 추가
13. ✅ **Alerting 알림** — Prometheus alert rule, Alertmanager Slack receiver, 로컬 학습용 빠른 감지 기준 정의
14. ✅ **CI** — GitHub Actions 기반 의존성/테스트/정적 검사/이미지/Kustomize/보안 게이트 자동화
15. ✅ **GitOps 중심 CD** — WSL2 self-hosted runner 이미지 push, commit SHA tag 갱신, Argo CD manual sync
16. ⏳ **AWS Cloud + Terraform** — 학습용 최소형 EKS, RDS, ElastiCache, Secret, remote backend 설계 및 배포

---

## 11. 참조 문서

| 문서 | 역할 |
| -------------------------------- | ---------------------------- |
| `ERD_structure.md` | 최종 데이터 모델, 제약 조건, Saga 상태 전이 |
| `service_function_definition.md` | 서비스별 기능 정의, 엔드포인트 계약, 호출 흐름 |
| `dev_convention.md` | 코드 생성 컨벤션, 네이밍 규칙, 파일 구조 템플릿, 서비스 간 호출 규칙 |

> `micromart_design.md`는 프로젝트 전체 구조와 설계 의도를 설명하는 상위 문서이며, DB 스키마 상세는 `ERD_structure.md`를 기준으로 유지한다.
