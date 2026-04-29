# MicroMart — 시스템 설계 문서

> Kubernetes 기반 관찰성 스택(Prometheus, Grafana, Loki, Tempo) 학습용  
> 이커머스 주문 관리 마이크로서비스 애플리케이션

***

## 1. 프로젝트 개요

### 목적

LGTM(Loki, Grafana, Tempo, Mimir/Prometheus) 관찰성 스택을 깊이 학습하기 위한 대상 애플리케이션이다. 서비스 간 연쇄 호출, 비동기 메시지, 의도적 장애 주입(Chaos Mode)을 통해 분산 트레이싱·메트릭·로그 수집의 실제 시나리오를 경험한다.

### 기술 스택

| 항목 | 선택 | 이유 |
|------|------|------|
| 언어 / 프레임워크 | Python 3.12 + FastAPI | 코드량 최소화, OpenTelemetry SDK 성숙도 높음 |
| 데이터베이스 | PostgreSQL (서비스별 독립) | MSA 원칙 준수, 서비스 간 DB 공유 금지 |
| 캐시 | Redis | Refresh Token 저장, product-service 캐싱 |
| 메시지 큐 | NATS | 경량, Kubernetes 네이티브, 비동기 트레이스 전파 실습 |
| 컨테이너 | Docker | 서비스별 독립 Dockerfile |
| 오케스트레이션 | Kubernetes (k3s 또는 minikube) | 관찰성 스택 Helm 배포 환경 |
| 부하 생성 | k6 | 시나리오 스크립트, Grafana 연동 |

***

## 2. 서비스 구성

### 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                        Kubernetes Cluster                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Namespace: micromart-app                                 │   │
│  │                                                           │   │
│  │   [Client / k6 Load Generator]                           │   │
│  │           │ HTTP                                          │   │
│  │           ▼                                               │   │
│  │   ┌───────────────┐                                      │   │
│  │   │  api-gateway   │  ← JWT 검증(RS256), 라우팅          │   │
│  │   └───────┬───────┘                                      │   │
│  │           │                                               │   │
│  │    ┌──────┼────────────────┐                             │   │
│  │    ▼      ▼                ▼                             │   │
│  │  [user] [product]       [order]                          │   │
│  │  service  service        service ──→ [product-service]   │   │
│  │    │        │ + Redis             ──→ [payment-service]  │   │
│  │  user-db product-db              ──→ NATS               │   │
│  │                order-db    payment-db    │               │   │
│  │                                         ▼               │   │
│  │                              [notification-service]      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Namespace: observability                                 │   │
│  │  OTel Collector → Tempo / Prometheus / Loki → Grafana    │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 서비스별 상세

#### api-gateway (포트 8000)

- **역할**: 단일 진입점, RS256 JWT 로컬 검증, 라우팅, Rate Limiting, 요청/응답 로깅
- **DB**: 없음 (stateless)
- **관찰성 포인트**: 전체 inbound 메트릭, 4xx/5xx 비율, Rate Limit 발동 횟수
- **특이사항**: 검증 통과 후 `X-User-ID`, `X-User-Role` 헤더를 추가하여 하위 서비스로 전달. 하위 서비스는 JWT를 직접 검증하지 않음

#### user-service (포트 8001)

- **역할**: 회원가입, 로그인, JWT 발급(RS256), Refresh Token Rotation, token_version 관리
- **DB**: `user-db` (PostgreSQL)
- **Redis**: `refresh:user:{id}:device` 키로 Refresh Token 저장, `user:{id}:token_version` 저장
- **관찰성 포인트**: 로그인 성공/실패 카운터, 신규 가입 비율, JWT 재발급 빈도

#### product-service (포트 8002)

- **역할**: 상품 목록 조회, 상품 상세, 재고 확인/차감
- **DB**: `product-db` (PostgreSQL) + `product-cache` (Redis)
- **관찰성 포인트**: 캐시 히트율, 재고 부족 이벤트, DB↔캐시 레이턴시 비교

#### order-service (포트 8003) ⭐ 핵심 서비스

- **역할**: 주문 생성·조회, product-service 재고 차감 호출, payment-service 결제 호출, NATS 이벤트 발행
- **DB**: `order-db` (PostgreSQL)
- **관찰성 포인트**: 주문 완료율, 주문 실패 원인 분류, 서비스 간 호출 레이턴시 비교, 분산 트레이스 루트 스팬

#### payment-service (포트 8004)

- **역할**: 결제 승인/거절 처리 (외부 PG 시뮬레이션), Chaos Mode 내장
- **DB**: `payment-db` (PostgreSQL)
- **관찰성 포인트**: 결제 실패율(Chaos Mode 토글), P95/P99 레이턴시, 결제 금액 히스토그램

**Chaos Mode 환경변수:**

```
CHAOS_FAILURE_RATE=0.3    # 30% 확률로 결제 실패
CHAOS_LATENCY_MS=2000     # 결제 응답 2초 지연
CHAOS_DB_SLOWQUERY=true   # DB 슬로우쿼리 시뮬레이션
```

#### notification-service

- **역할**: NATS 메시지 소비, 이메일/SMS 발송 시뮬레이션, 발송 이력 로그 기록
- **DB**: 없음 (로그만 기록)
- **관찰성 포인트**: 메시지 소비 레이턴시, 발송 성공/실패 카운터, 큐 적체 감지

***

## 3. 핵심 데이터 플로우 — 주문 생성

```
1. Client       → api-gateway      POST /api/orders (JWT 포함)
2. api-gateway  → order-service    헤더(X-User-ID)와 함께 전달 (traceId 전파)
3. order-service → product-service 재고 확인 + 차감
4. order-service → payment-service 결제 요청 (실패 시 재고 롤백)
5. order-service → order-db        주문 저장
6. order-service → NATS            order.completed 이벤트 발행
7. NATS          → notification    이벤트 소비, 알림 발송 시뮬레이션
```

Tempo는 1~7 전 구간을 단일 트레이스로 표현하고, 각 서비스는 개별 Span으로 시각화된다.

***

## 4. 인증 설계

### 채택 방식

- **패턴**: Short Access Token + Refresh Token + Token Versioning (방식 A)
- **알고리즘**: RS256 (개인키는 user-service만 보유, 공개키는 api-gateway가 검증용으로 보유)

### 토큰 구성

| 토큰 | TTL | 저장 위치 | 역할 |
|------|-----|-----------|------|
| Access Token | 15분 | 클라이언트 메모리 또는 HttpOnly Cookie | API 인증 |
| Refresh Token | 7일 | Redis (서버), HttpOnly Cookie (클라이언트) | Access Token 재발급 |

### JWT Payload

```json
{
  "sub": "user_123",
  "role": "customer",
  "token_version": 7,
  "iat": 1714000000,
  "exp": 1714000900
}
```

### Redis 저장 구조

```
refresh:user:123:web     → "eyJhbGci..." (기기별 Refresh Token)
user:123:token_version   → 7             (버전 번호)
```

### 이벤트별 처리

| 이벤트 | 처리 방법 |
|--------|-----------|
| 일반 로그아웃 | Redis에서 해당 기기 Refresh Token 키 삭제 |
| 비밀번호 변경 | token_version +1, 모든 기기 Refresh Token 삭제 |
| 계정 강제 차단 | token_version +1, 모든 기기 Refresh Token 삭제 |
| Refresh Token 재사용 감지 | 모든 세션 즉시 강제 종료 |

### Access Token 검증 흐름 (api-gateway)

```
1. 서명 검증 (RS256 공개키, 로컬 — Redis 조회 없음)
2. 만료 시간 확인
3. token_version 확인 (재발급 요청 시에만 Redis 조회)
4. 통과 시 X-User-ID, X-User-Role 헤더 추가 후 하위 서비스로 전달
```

***

## 5. 관찰성 계측 공통 패턴

### OpenTelemetry 초기화 (모든 서비스 공통)

```python
# 트레이싱: OTLP → OTel Collector → Tempo
# 메트릭: Prometheus Exporter (HTTP 자동 + 커스텀)
# 로깅: structlog JSON 포맷 (traceId/spanId 자동 주입 → Loki)
```

### 비즈니스 메트릭 예시 (order-service)

```python
orders_total = Counter(
    "orders_total", "주문 수", ["status", "payment_method"]
)
order_amount = Histogram(
    "order_amount_krw", "주문 금액(원)",
    buckets=[1000, 5000, 10000, 50000, 100000]
)
order_duration = Histogram(
    "order_processing_seconds", "주문 처리 시간(초)"
)
```

### Loki 로그 필드 (JSON 구조화)

```json
{
  "timestamp": "2026-04-29T10:00:00Z",
  "level": "error",
  "service": "order-service",
  "trace_id": "abc123",
  "span_id": "def456",
  "user_id": "123",
  "event": "payment_failed",
  "message": "결제 서비스 응답 없음"
}
```

`trace_id` 필드로 Grafana에서 Loki 로그 → Tempo 트레이스로 바로 점프 가능.

***

## 6. 관찰성 학습 시나리오

| 시나리오 | 트리거 | 관찰 방법 |
|----------|--------|-----------|
| 결제 서비스 간헐적 실패 | `CHAOS_FAILURE_RATE=0.5` | Tempo 에러 트레이스 + Loki 에러 로그 |
| 결제 서비스 지연 | `CHAOS_LATENCY_MS=3000` | Grafana P99 급등 + 알럿 발동 |
| 재고 부족 | 상품 재고 소진 | order-service 비즈니스 에러 메트릭 |
| DB 커넥션 풀 고갈 | product-service 부하 증가 | DB pool 메트릭 + 연쇄 에러 트레이스 |
| 알림 큐 적체 | notification-service 중단 후 재기동 | NATS 메시지 백로그 메트릭 |

***

## 7. 프로젝트 디렉토리 구조

```
micromart/
├── services/
│   ├── api-gateway/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── config.py
│   │   │   ├── middleware/
│   │   │   │   ├── auth.py          ← JWT 검증
│   │   │   │   └── telemetry.py     ← OTel 초기화
│   │   │   └── router.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── user-service/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── models.py            ← users 테이블 (token_version 포함)
│   │   │   ├── auth.py              ← JWT 발급, Refresh Token Rotation
│   │   │   ├── routes/
│   │   │   └── telemetry.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── product-service/
│   ├── order-service/
│   ├── payment-service/
│   └── notification-service/
├── shared/
│   └── telemetry/
│       └── setup.py                 ← OTel 공통 초기화 코드
├── k8s/
│   ├── namespaces.yaml
│   ├── api-gateway/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   └── configmap.yaml
│   ├── user-service/
│   ├── product-service/
│   ├── order-service/
│   ├── payment-service/
│   ├── notification-service/
│   ├── databases/
│   │   ├── user-db.yaml
│   │   ├── product-db.yaml
│   │   ├── order-db.yaml
│   │   └── redis.yaml
│   ├── nats/
│   │   └── nats.yaml
│   └── load-generator/
│       └── k6-job.yaml
├── otel-config/
│   └── otel-collector-config.yaml
└── docker-compose.yaml              ← 로컬 개발용
```

***

## 8. 구현 순서

1. **공통 라이브러리** (`shared/telemetry/`) — OTel 초기화, structlog JSON 설정
2. **user-service** — JWT 발급, Refresh Token Rotation, token_version 관리
3. **product-service** — 상품 CRUD, Redis 캐싱
4. **payment-service** — 결제 시뮬레이션, Chaos Mode 구현
5. **order-service** — 오케스트레이터, 서비스 간 호출, NATS 발행
6. **api-gateway** — JWT 검증 미들웨어, 리버스 프록시
7. **notification-service** — NATS 소비, 비동기 처리
8. **Kubernetes 매니페스트** — Deployment, Service, ConfigMap, Secret
9. **k6 부하 스크립트** — 시나리오별 부하 생성
10. **docker-compose.yaml** — 로컬 통합 테스트 환경
