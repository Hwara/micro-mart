# shared/telemetry 기술 레퍼런스

> **대상 독자**: MicroMart 프로젝트를 따라해보려는 독자 또는 이 코드가 기억이 안나는 미래의 나
> **최종 수정**: 2026-04-30
> **관련 Phase**: Phase 1

---

## 1. 이 모듈이 존재하는 이유

MicroMart는 6개의 독립적인 마이크로서비스로 구성되어 있다. 각 서비스가 OpenTelemetry 초기화 코드를 개별적으로 작성하면 두 가지 문제가 생긴다.

1. **코드 중복**: 동일한 TracerProvider/MeterProvider 설정 코드가 6곳에 반복된다.
2. **계측 불일치**: 서비스마다 trace_id 포맷이나 로그 구조가 달라지면 Grafana에서 서비스 간 데이터를 연결할 수 없다.

`shared/telemetry`는 이 두 문제를 해결하는 공통 모듈이다. 각 서비스는 초기화 함수 한 번만 호출하면 된다.

```python
# 각 서비스 main.py에서의 사용법
from shared.telemetry import init_logging, init_telemetry

init_logging(service_name="order-service", log_format="json")
init_telemetry(service_name="order-service", db_engine=engine)
```

---

## 2. 파일 구성

```
shared/telemetry/
├── __init__.py          # 외부 공개 인터페이스 정의
├── setup.py             # OTel TracerProvider, MeterProvider 초기화
├── custom_logging.py    # structlog JSON 설정, trace_id 자동 주입
└── middleware.py        # FastAPI 요청/응답 로깅 미들웨어
```

> ⚠️ **파일명 주의**: `logging.py`라는 이름은 사용하면 안 된다.
> Python 표준 라이브러리의 `logging` 모듈과 이름이 충돌하여
> `AttributeError: partially initialized module 'logging'` 순환 참조 오류가 발생한다.
> 반드시 `custom_logging.py`처럼 다른 이름을 사용할 것.

---

## 3. 의존성

```
# shared/telemetry/requirements.txt
opentelemetry-sdk
opentelemetry-exporter-otlp-proto-grpc
opentelemetry-instrumentation-fastapi   ← FastAPI 결합 허용 (전 서비스 FastAPI 기반)
opentelemetry-instrumentation-sqlalchemy
opentelemetry-instrumentation-httpx
opentelemetry-instrumentation-logging
fastapi
sqlalchemy[asyncio]
httpx
starlette                               ← middleware.py에서 직접 사용
pydantic-settings
structlog
```

**의존성 설계 결정 사항**

이 모듈은 FastAPI, SQLAlchemy, httpx에 결합되어 있다. 의도적인 선택이다.
MicroMart의 모든 서비스가 동일한 기술 스택을 사용하므로 추상화 레이어를 추가하는 것은
복잡도만 높이는 과도한 설계(over-engineering)로 판단했다.

만약 추후 다른 프레임워크(Django 등)를 도입한다면 아래 구조로 분리를 고려한다.

```
shared/telemetry/core.py    ← 프레임워크 무관 초기화
shared/telemetry/fastapi.py ← FastAPI 전용 계측
```

---

## 4. setup.py — OTel 초기화

### 핵심 개념: OTel 3대 신호

| 신호 | 질문 | 저장소 |
|------|------|--------|
| Traces | 요청이 어떤 경로로 흘렀는가? | Tempo |
| Metrics | 시스템이 지금 얼마나 건강한가? | Prometheus |
| Logs | 각 시점에 무슨 일이 있었는가? | Loki |

세 신호는 `trace_id`로 연결된다. Grafana에서 에러 로그를 클릭하면 해당 trace_id의 전체 분산 트레이스로 이동할 수 있다.

### `init_telemetry()` 함수 인자

| 인자 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `service_name` | str | ✅ | Grafana에서 서비스를 구분하는 식별자 |
| `db_engine` | AsyncEngine | ❌ | SQLAlchemy 엔진. 전달 시 DB 쿼리 자동 계측 |
| `settings` | TelemetrySettings | ❌ | 없으면 환경변수에서 자동 로딩 |

### 환경변수

| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTel Collector 주소 |
| `LOG_FORMAT` | `pretty` | `json`(운영) or `pretty`(로컬 개발) |
| `SERVICE_VERSION` | `0.1.0` | 서비스 버전 태그 |

### 자동 계측 동작 방식

`FastAPIInstrumentor().instrument()`를 호출하면 FastAPI의 모든 라우트 핸들러에
자동으로 Span이 생성된다. 코드를 수정하지 않아도 된다.

`HTTPXClientInstrumentor().instrument()`는 특히 중요하다.
서비스 간 HTTP 호출 시 W3C TraceContext 헤더(`traceparent`)를 자동으로 주입하여
서비스 A → 서비스 B → 서비스 C로 이어지는 분산 트레이스가 단일 trace_id로 연결된다.

```
order-service → httpx 요청 → product-service
     │                              │
     └── traceparent 헤더 자동 주입 ──┘
         같은 trace_id로 Span 연결됨
```

---

## 5. custom_logging.py — 구조화 로깅

### trace_id 자동 주입 원리

structlog는 로그를 출력하기 전에 "프로세서 체인"을 순서대로 실행한다.
`_add_otel_context` 함수가 이 체인에 등록되어 모든 로그 호출 시 자동으로 실행된다.

```python
span = trace.get_current_span()
span_context = span.get_span_context()

if span_context.is_valid:
    event_dict["trace_id"] = format(span_context.trace_id, "032x")
    event_dict["span_id"] = format(span_context.span_id, "016x")
```

Span 내부에서 출력된 로그에는 trace_id가 포함되고,
Span 외부(백그라운드 작업 등)에서 출력된 로그에는 포함되지 않는다.

### 로그 출력 형식

**LOG_FORMAT=pretty (로컬 개발)**

```
2026-04-30T11:00:00Z [info] 주문 완료  order_id=42  trace_id=a1b2c3  service=order-service
```

**LOG_FORMAT=json (운영, Loki 수집)**

```json
{
  "timestamp": "2026-04-30T11:00:00Z",
  "level": "info",
  "service": "order-service",
  "trace_id": "a1b2c3def456",
  "span_id": "789xyz",
  "event": "주문 완료",
  "order_id": 42
}
```

### 알려진 제약사항: add_logger_name 사용 불가

`structlog.stdlib.add_logger_name` 프로세서는 stdlib Logger의 `.name` 속성을 읽는다.
그러나 이 모듈은 `PrintLoggerFactory`를 사용하므로 해당 속성이 없어 `AttributeError`가 발생한다.

**해결책**: `add_logger_name`을 프로세서 체인에서 제거한다.
서비스명은 `bind_contextvars(service=service_name)`으로 동일하게 주입된다.

```python
# ❌ 사용 금지
shared_processors = [
    structlog.stdlib.add_logger_name,  # PrintLoggerFactory와 충돌
    ...
]

# ✅ 올바른 방법
structlog.contextvars.bind_contextvars(service=service_name)
```

---

## 6. middleware.py — 요청/응답 로깅

### 미들웨어란?

요청이 실제 비즈니스 로직(라우터 핸들러)에 도달하기 전과 후에 실행되는 레이어다.
`call_next(request)` 호출을 기준으로 선처리/후처리 구간이 나뉜다.

```python
async def dispatch(self, request, call_next):
    # ── 선처리: 요청 핸들러 실행 전 ──
    start_time = time.perf_counter()
    logger.info("요청 수신", ...)

    response = await call_next(request)  # ← 실제 핸들러 실행

    # ── 후처리: 요청 핸들러 실행 후 ──
    logger.info("요청 완료", duration_ms=..., status_code=...)
    return response
```

### 로그 레벨 분기 기준

| 상태 코드 | 로그 레벨 | 의미 |
|-----------|-----------|------|
| 2xx / 3xx | `info` | 정상 |
| 4xx | `warning` | 클라이언트 오류 |
| 5xx | `error` | 서버 오류 |

### 각 서비스에 등록하는 방법

```python
# 각 서비스의 main.py
from fastapi import FastAPI
from shared.telemetry import RequestLoggingMiddleware

app = FastAPI()
app.add_middleware(RequestLoggingMiddleware)
```

`add_middleware()`로 등록된 미들웨어는 모든 라우트에 자동 적용된다.
개별 라우트 핸들러에 중복 코드를 넣을 필요가 없다.

---

## 7. 동작 확인 방법

OTel Collector가 없는 로컬 환경에서도 초기화 오류 없이 동작한다.
Exporter가 연결에 실패해도 앱은 정상 실행된다 (백그라운드에서 재시도).

```bash
# 프로젝트 루트에서 실행
python shared/telemetry/test_telemetry.py
```

**정상 출력 확인 포인트**

- `service=test-service`가 모든 로그 줄에 자동으로 포함되는가?
- Span 내부 로그에 `trace_id`가 포함되고, Span 외부 로그에는 없는가?

---

## 8. 자주 발생하는 오류

| 오류 메시지 | 원인 | 해결 방법 |
|-------------|------|-----------|
| `AttributeError: 'PrintLogger' object has no attribute 'name'` | 프로세서 체인에 `add_logger_name` 포함됨 | `shared_processors`에서 해당 줄 제거 |
| `AttributeError: partially initialized module 'logging'` | 파일명을 `logging.py`로 지음 | 파일명을 `custom_logging.py` 등으로 변경 |
| `Failed to export traces` (로그에 경고) | OTel Collector 미실행 | 로컬 개발 시 무시 가능. docker-compose 구성 후 해결됨 |
