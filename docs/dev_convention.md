# MicroMart — AI 개발 컨벤션 가이드

> 최종 갱신일: 2026-05-05
> 목적: MicroMart 프로젝트에서 AI/개발자가 일관된 구조와 규칙으로 코드를 작성하도록 하는 기준 문서

---

## 1. 문서 목적

이 문서는 MicroMart 프로젝트에서 서비스별 코드를 작성할 때 따라야 하는 **공통 컨벤션**, **파일 구조 규칙**, **설계 원칙**, **문서 참조 우선순위**를 정의한다.

이 문서는 구현 편의를 위한 코드 스타일 가이드이지만, 도메인 규칙의 기준 문서는 아니다. 모델 제약, 상태값, 엔드포인트 계약은 별도 문서를 우선 참조한다.

---

## 2. 문서 참조 우선순위

코드 작성 전 아래 문서를 순서대로 확인한다.

1. `ERD_structure.md` — 모델, 컬럼, 제약 조건, 상태값 기준
2. `service_function_definition.md` — 서비스별 책임, 엔드포인트 계약, 서비스 간 호출 흐름
3. `micromart_design.md` — 전체 아키텍처와 설계 의도
4. `dev_convention.md` — 코드 작성 컨벤션, 파일 구조, 공통 구현 규칙

> ⚠️ 문서 간 충돌 시, 도메인 규칙은 `ERD_structure.md`와 `service_function_definition.md`를 우선한다.

---

## 3. 공통 원칙

- Python 3.12 + FastAPI 기반으로 구현한다.
- 서비스별 독립 배포를 전제로 하며, 서비스 간 DB 공유를 금지한다.
- 서비스 간 참조는 DB FK가 아니라 HTTP/NATS와 논리적 ID 참조로 처리한다.
- 구현은 Phase 단위로 진행한다.
- 새 기능을 작성할 때는 기존 구현 패턴(user-service, product-service, payment-service, order-service)을 우선 참고한다.
- 코드는 학습용 프로젝트이지만, 현업 수준의 명시성과 유지보수성을 기준으로 작성한다.

---

## 4. Phase 작업 규칙

- 구현은 반드시 Phase 단위로 진행한다.
- Phase 시작 전, 구현 대상의 핵심 개념과 트레이드오프를 먼저 설명한다.
- 코드 작성 후에는 보안, 정합성, 장애 복구 가능성을 한 번 더 검토한다.
- Phase 완료 시 다음 내용을 정리한다.
  - 역할 설명
  - 파일 구성
  - 핵심 설계 결정
  - 자주 발생한 오류 / 트러블슈팅
  - 왜 이렇게 설계했는가

---

## 5. 서비스 디렉토리 표준 구조

각 서비스는 아래 구조를 기본 템플릿으로 사용한다.

```text
services/<service-name>/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   ├── dependencies.py
│   ├── services/
│   ├── routes/
│   └── middleware/
├── Dockerfile
├── .env.example
└── requirements.txt
```

### 서비스별 추가 모듈 예시

비즈니스 로직이 복잡하거나 외부 서비스 호출이 많은 서비스는 아래와 같이 모듈을 분리한다.

| 서비스 | 추가 파일 | 역할 |
|--------|-----------|------|
| `order-service` | `nats_client.py` | NATS 싱글턴 커넥션 관리 (`main.py` 순환 import 방지) |
| `order-service` | `services/http_clients.py` | product/payment 서비스 HTTP 클라이언트 (timeout, 에러 래핑) |
| `order-service` | `services/order_service.py` | Saga 오케스트레이션 비즈니스 로직 |
| `product-service` | `cache.py` | Redis Cache-Aside 헬퍼 |

### 파일 역할

| 파일 | 역할 |
|------|------|
| `main.py` | FastAPI 앱 생성, startup/shutdown, 라우터 등록 |
| `config.py` | 환경변수 설정, `BaseSettings` 기반 설정 로딩 |
| `database.py` | SQLAlchemy async engine, sessionmaker, DB 의존성 |
| `models.py` | SQLAlchemy ORM 모델 |
| `schemas.py` | Pydantic request/response 모델 |
| `dependencies.py` | 공통 Depends, 인증/헤더 검증 의존성 |
| `services/` | 비즈니스 로직 분리 |
| `routes/` | HTTP 라우터 정의 |
| `middleware/` | 서비스 전용 미들웨어 |

> 작은 서비스에서는 `dependencies.py`, `services/`, `middleware/` 일부가 없을 수 있다. 다만 생략 시에도 책임 분리는 유지한다.

---

## 6. `config.py` 규칙

- 모든 설정은 `pydantic-settings` 기반 `Settings` 클래스로 관리한다.
- 환경변수 이름은 대문자 스네이크 케이스를 사용한다.
- 애플리케이션 코드는 `.env` 파일을 직접 읽지 않고 **프로세스 환경변수만** 읽는다.
  Docker Compose의 `env_file`, Kubernetes ConfigMap/Secret, 로컬 실행 스크립트가 `.env`를
  환경변수로 주입하는 책임을 가진다.
- `.env.example`에는 실제 필요한 값만 명시하고, Docker 로컬 통합 실행 기준 예시값을 둔다.
- 운영/개발 환경에서 바뀔 수 있는 값은 하드코딩하지 않는다.
- 보안 민감값(`JWT_PRIVATE_KEY`, `INTERNAL_SERVICE_TOKEN`, DB 비밀번호)은 코드에 직접 넣지 않는다.
- `Settings()` 인스턴스는 가능하면 요청 처리 시점 또는 앱 초기화 시점에 생성한다.
  단, `database.py`의 SQLAlchemy engine/session factory 처럼 애플리케이션 시작 시 반드시 필요한 singleton 리소스는 예외적으로 import 시점에 생성할 수 있다.
  이 경우 필요한 환경변수(`DATABASE_URL` 등)는 반드시 프로세스 시작 전에 주입되어 있어야 한다.
- `get_settings()`를 `@lru_cache`로 감싸고, 필요한 시점(함수/메서드 내부)에서 호출한다.
  `lru_cache` 덕분에 반복 호출 비용이 없으며, 테스트 시 `get_settings.cache_clear()`로
  환경변수 변경을 즉시 반영할 수 있다. FastAPI 공식 문서도 이 패턴을 권장한다.

예시:

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "payment-service"
    debug: bool = False
    database_url: str
    internal_service_token: str

    model_config = SettingsConfigDict(extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

### 서비스별 환경변수 목록

| 서비스 | 환경변수 |
| ------ | -------- |
| `api-gateway` | `SERVICE_NAME`, `SERVICE_VERSION`, `DEBUG`, `LOG_FORMAT`, `USER_SERVICE_URL`, `PRODUCT_SERVICE_URL`, `ORDER_SERVICE_URL`, `JWKS_URL`, `JWT_ALGORITHM`, `JWT_AUDIENCE`, `JWKS_CACHE_TTL_SECONDS`, `HTTP_TIMEOUT_SECONDS`, `RATE_LIMIT_PER_MINUTE`, `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE` |
| `user-service` | `SERVICE_NAME`, `SERVICE_VERSION`, `DEBUG`, `LOG_FORMAT`, `DATABASE_URL`, `REDIS_URL`, `JWT_PRIVATE_KEY_FILE`, `JWT_PUBLIC_KEY_FILE`, `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`, `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE` |
| `product-service` | `SERVICE_NAME`, `SERVICE_VERSION`, `DEBUG`, `LOG_FORMAT`, `DATABASE_URL`, `REDIS_URL`, `REDIS_SOCKET_CONNECT_TIMEOUT`, `REDIS_SOCKET_TIMEOUT`, `INTERNAL_SERVICE_TOKEN`, `PRODUCT_CACHE_TTL`, `DEFAULT_PAGE_SIZE`, `MAX_PAGE_SIZE`, `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE` |
| `order-service` | `SERVICE_NAME`, `SERVICE_VERSION`, `DEBUG`, `LOG_FORMAT`, `DATABASE_URL`, `INTERNAL_SERVICE_TOKEN`, `PRODUCT_SERVICE_URL`, `PAYMENT_SERVICE_URL`, `MAX_OPTIMISTIC_RETRY`, `HTTP_TIMEOUT_SECONDS`, `NATS_URL`, `NATS_CONNECT_TIMEOUT_SECONDS`, `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE` |
| `payment-service` | `SERVICE_NAME`, `SERVICE_VERSION`, `DEBUG`, `LOG_FORMAT`, `DATABASE_URL`, `INTERNAL_SERVICE_TOKEN`, `CHAOS_FAILURE_RATE`, `CHAOS_LATENCY_MS`, `CHAOS_DB_SLOWQUERY`, `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE` |
| `shared/telemetry` | `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE`, `LOG_FORMAT`, `SERVICE_VERSION` |

---

## 7. `database.py` 규칙

- SQLAlchemy 2.0 async 스타일을 사용한다.
- 세션 의존성은 `AsyncSession` 기반 generator로 제공한다.
- `expire_on_commit=False`를 기본값으로 사용한다.
- 공통 타입 별칭 `DBSession`을 사용해 라우터 시그니처를 단순화한다.
- Redis는 **사용하는 서비스만** 정의한다. Redis가 필요 없는 서비스는 `config.py`와
  `database.py`에 Redis 설정을 추가하지 않는다.

  > 현재 Redis 사용 서비스: `user-service`, `product-service`
  > Redis 미사용 서비스: `order-service`, `payment-service`, `notification-service`

예시:

```python
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 의존성 주입용 DB 세션 생성기.

    테스트 시 app.dependency_overrides[get_db]로 교체해 사용한다.
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


DBSession = Annotated[AsyncSession, Depends(get_db)]
```

> ⚠️ `engine`은 모듈 임포트 시 생성되므로, 테스트에서 DB URL을 바꾸려면
> `get_db`를 통째로 `dependency_overrides`로 교체하는 방식을 사용한다.
> DB URL 자체를 바꿔야 하는 테스트는 별도 엔진을 생성해 오버라이드한다.

### 테스트 환경 주의사항

`database.py`는 import 시점에 SQLAlchemy engine을 생성할 수 있다.
따라서 pytest에서는 `app.database` 또는 `app.main` import 전에
필수 환경변수(`DATABASE_URL`, `INTERNAL_SERVICE_TOKEN` 등)를 먼저 주입해야 한다.

권장 패턴:

```python
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)

from app.main import app
```

---

## 8. `models.py` 규칙

- SQLAlchemy 2.0의 `Mapped[...]` + `mapped_column()` 스타일을 사용한다.
- PK는 특별한 사유가 없으면 `BigInteger` + `autoincrement=True`를 사용한다.
- SQLite 테스트 환경 호환이 필요한 서비스는 `BigIntegerType` 커스텀 TypeDecorator를 사용한다.
  PostgreSQL에서는 `BigInteger`, SQLite(테스트)에서는 `Integer`로 자동 분기된다.
  현재 적용 서비스: `payment-service`, `order-service`
- 모든 테이블은 `created_at`, `updated_at` 정책을 명확히 가져간다.
- `created_at`은 `server_default=func.now()`를 사용한다.
- `updated_at`은 `onupdate=func.now()`를 사용한다.
- 불변 데이터 테이블(`order_items`, `refunds`)은 `updated_at`을 두지 않는다. 의도적 제외임을 주석 또는 docstring에 명시한다.
- 동일 서비스 DB 내 관계만 물리적 FK를 허용한다.
- 서비스 간 참조(`user_id`, `product_id`, `payment_id`)는 물리적 FK를 두지 않는다.
- 서비스 간 데이터 정합성은 HTTP 호출과 도메인 로직으로 관리한다.
- 소프트 삭제가 필요한 엔티티는 `is_active` 같은 명시적 필드를 사용한다.

예시:

```python
from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
```

---

## 9. 상태값 규칙

- 주문, Saga, 결제, 환불 상태값은 문자열 하드코딩 대신 Python `str + enum.Enum`을 사용한다.
- 허용 상태값은 반드시 `ERD_structure.md` 기준으로 정의한다.
- DB 저장값, 응답값, 로그 필드에서 동일한 Enum 문자열을 사용한다.
- 상태 전이가 있는 로직은 가능한 전이 경로를 docstring 또는 주석으로 명시한다.

예시:

```python
import enum


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
```

---

## 10. `schemas.py` 규칙

- 요청/응답 스키마는 Pydantic 모델로 분리한다.
- ORM 모델을 그대로 응답으로 노출하지 않는다.
- 금액, 수량, 상태값 등 비즈니스 의미가 있는 필드는 타입과 제약을 명확히 둔다.
- 외부 API 응답과 내부 서비스 응답은 필요 시 별도 스키마로 구분한다.
- 입력 유효성 검사가 복잡한 경우 `@model_validator`를 사용한다. (예: 중복 product_id 차단)

예시:

```python
from pydantic import BaseModel, Field


class PaymentCreateRequest(BaseModel):
    order_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    amount: int = Field(gt=0)


class PaymentResponse(BaseModel):
    payment_id: int
    order_id: int
    status: str
    amount: int
```

---

## 11. 라우터 규칙

- 라우터는 얇게 유지하고, 비즈니스 로직은 `services/` 또는 별도 함수로 분리한다.
- 엔드포인트 함수 내부에서 긴 트랜잭션 로직을 직접 작성하지 않는다.
- `response_model`을 명시한다.
- 상태 코드와 예외 메시지는 일관되게 유지한다.
- 내부 서비스 전용 API는 라우터 설명 또는 주석으로 명확히 표시한다.

예시:

```python
from fastapi import APIRouter, status

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=PaymentResponse)
async def create_payment(payload: PaymentCreateRequest, db: DBSession):
    return await create_payment_service(db=db, payload=payload)
```

---

## 12. 서비스 간 호출 규칙

- 서비스 간 HTTP 호출은 반드시 명시적 timeout을 설정한다.
- 내부 서비스 호출은 공통적으로 `X-Internal-Token` 헤더를 사용한다.
- 사용자 인증 정보는 `api-gateway`가 검증 후 `X-User-ID`, `X-User-Role` 헤더로 전달한다.
- 하위 서비스는 외부 JWT를 직접 검증하지 않는다.
- 서비스 간 호출 실패 시 실패 원인을 로그와 메트릭에 남긴다.
- 재시도 가능한 오류와 비재시도 오류를 구분한다.
  - 재시도 가능: `VERSION_CONFLICT(409)` → 상품 재조회 후 최대 `max_optimistic_retry`회 재시도
  - 재시도 불가: `INSUFFICIENT_STOCK(409)`, `PAYMENT_REJECTED(402)` → 즉시 실패
  - 네트워크 오류(`TimeoutException`): Saga 복잡도를 낮추기 위해 비재시도로 처리
- 내부 API는 외부 클라이언트에 직접 노출하지 않는다.
- HTTP 클라이언트는 서비스별로 `services/http_clients.py`에 분리하고, 커스텀 예외로 래핑한다.

예시:

```python
headers = {
    "X-Internal-Token": settings.internal_service_token,
    "X-User-ID": str(user_id),
}
```

---

## 13. API 경계 규칙

- 외부 클라이언트용 API와 내부 서비스용 API를 구분한다.
- 내부 서비스 전용 API는 인증 헤더 없이는 접근할 수 없어야 한다.
- 관리자 전용 기능은 역할 기반 권한 검사를 거친다.
- 외부 공개 API는 입력 검증과 권한 검사를 우선한다.
- 내부 API는 명세 문서에 요청/응답 형태를 먼저 정의한 뒤 구현한다.
- `user_id`는 바디가 아닌 `X-User-ID` 헤더에서만 추출한다. gateway를 우회한 직접 호출로 user_id를 위조하는 공격을 방어한다.

---

## 14. 비즈니스 로직 규칙

- 결제, 주문, 재고 차감처럼 실패 가능성이 높은 로직은 단계별 상태를 남긴다.
- 보상 트랜잭션이 필요한 로직은 중간 상태를 DB에 저장해 복구 가능하게 만든다.
- 중복 처리 방지가 필요한 기능은 애플리케이션 레벨 검사와 DB 제약을 함께 사용한다.
- "성공 경로"뿐 아니라 "실패 경로"와 "부분 실패"를 먼저 설계하고 구현한다.
- 보상 트랜잭션은 best-effort로 처리하되, 미완료 상태(`STOCK_ROLLBACK_NEEDED`)를 DB에 커밋해 배치 복구 잡이 스캔할 수 있도록 한다.

---

## 15. 로깅 / 관찰성 규칙

- 모든 서비스는 `shared/telemetry` 공통 모듈을 우선 사용한다.
- 로그는 구조화된 JSON 형식을 사용한다.
- trace_id, span_id, service name을 로그에 포함한다.
- 비즈니스 이벤트는 의미 있는 event명을 사용한다. 예: `payment_approved`, `payment_rejected`, `stock_conflict`
- 에러 로그에는 가능한 범위에서 원인 분류값(`failure_reason`)을 남긴다.
- 각 서비스의 핵심 비즈니스 이벤트는 OpenTelemetry Counter/Histogram 메트릭으로 계측한다.

---

## 16. 보안 규칙

- `INTERNAL_SERVICE_TOKEN` 기본값은 개발용으로만 사용하고 운영에서는 반드시 변경한다.
- private key, DB password, secret token은 절대 코드에 하드코딩하지 않는다.
- 민감 정보(비밀번호, Refresh Token 원문)는 로그에 남기지 않는다.
- 내부 서비스 토큰 비교는 `hmac.compare_digest`를 사용하여 타이밍 공격을 방지한다.
- 외부 노출이 필요 없는 서비스(`payment-service`, `notification-service`)는 gateway 뒤 또는 내부 네트워크에만 두는 것을 전제로 설계한다.

---

## 17. 테스트 / 검증 규칙

- 최소한의 정상 흐름과 실패 흐름을 직접 검증한다.
- 모델 변경 시 생성/조회/상태 변경이 의도대로 되는지 확인한다.
- 내부 API는 인증 헤더 누락 케이스를 검증한다.
- 결제/주문/재고 차감 로직은 멱등성, 충돌, 예외 상황을 우선 테스트한다.

---

## 18. 문서 동기화 규칙

다음 변경이 발생하면 관련 문서를 함께 갱신한다.

- 모델 변경 → `ERD_structure.md`
- 엔드포인트/호출 흐름 변경 → `service_function_definition.md`
- 아키텍처/구현 현황 변경 → `README.md`, `micromart_design.md`
- 공통 코드 작성 방식 변경 → `dev_convention.md`

> ⚠️ 새 서비스의 `routes`, `schemas`, 내부/외부 호출 로직을 작성하기 전에 반드시 `service_function_definition.md`를 먼저 확인한다.

---

## 19. 커밋 / 작업 규칙

- 자동 커밋하지 않는다.
- 의미 없는 대규모 리팩터링을 한 번에 진행하지 않는다.
- 리뷰 피드백은 옳고 그름을 먼저 분석한 뒤 반영한다.
- 구현 중 컨벤션과 충돌하는 예외가 있으면 이유를 먼저 설명하고 진행한다.

---

## 20. 체크리스트

새 서비스 또는 새 기능 구현 전 아래 항목을 확인한다.

- [ ] `ERD_structure.md`를 확인했는가?
- [ ] `service_function_definition.md`를 확인했는가?
- [ ] 엔드포인트 요청/응답 스키마를 먼저 정의했는가?
- [ ] 상태값 Enum을 먼저 정의했는가?
- [ ] 내부/외부 API 경계를 구분했는가?
- [ ] 서비스 간 호출 헤더와 timeout을 정의했는가?
- [ ] 실패 경로와 보상 로직을 먼저 고려했는가?
- [ ] 로그/메트릭 포인트를 정했는가?
- [ ] 관련 문서 업데이트가 필요한가?
- [ ] Redis 미사용 서비스에 Redis 설정이 포함되어 있지 않은가?
- [ ] 불변 데이터 테이블에 `updated_at`이 없고 그 이유가 명시되어 있는가?
