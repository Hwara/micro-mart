# MicroMart — AI 개발 컨벤션 가이드

> 최종 갱신일: 2026-05-24
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
├── alembic.ini     # DB를 보유한 서비스의 Alembic 설정
├── alembic/        # DB를 보유한 서비스의 migration history
│   ├── env.py
│   └── versions/
├── Dockerfile
├── .env.example
├── pytest.ini    # 테스트가 있는 서비스
├── tests/        # 테스트가 있는 서비스
└── requirements.txt
```

> DB가 없는 서비스(`api-gateway`, `notification-service`)는 `alembic.ini`와 `alembic/`을 두지 않는다.

### 서비스별 추가 모듈 예시

비즈니스 로직이 복잡하거나 외부 서비스 호출이 많은 서비스는 아래와 같이 모듈을 분리한다.

| 서비스 | 추가 파일 | 역할 |
| -------- | ----------- | ------ |
| `order-service` | `nats_client.py` | NATS 싱글턴 커넥션 관리 (`main.py` 순환 import 방지) |
| `order-service` | `services/http_clients.py` | product/payment 서비스 HTTP 클라이언트 (timeout, 에러 래핑) |
| `order-service` | `services/order_service.py` | Saga 오케스트레이션 비즈니스 로직 |
| `product-service` | `cache.py` | Redis Cache-Aside 헬퍼 |
| `product-service` | `services/product_service.py` | 상품 CRUD, Cache-Aside, 재고 차감/복구 비즈니스 로직 |
| `payment-service` | `services/payment_service.py` | 결제/환불 상태 전이, Chaos Mode, 메트릭 계측 |
| `user-service` | `services/auth_service.py` | 회원가입, 로그인, 토큰 재발급/로그아웃, JWKS 생성 |
| `api-gateway` | `services/proxy_service.py` | 라우팅 대상 결정, 프록시 요청, TraceContext 전파 |

### 파일 역할

| 파일 | 역할 |
| ------ | ------ |
| `main.py` | FastAPI 앱 생성, startup/shutdown, 라우터 등록 |
| `config.py` | 환경변수 설정, `BaseSettings` 기반 설정 로딩 |
| `database.py` | SQLAlchemy async engine, sessionmaker, DB 의존성 |
| `models.py` | SQLAlchemy ORM 모델 |
| `schemas.py` | Pydantic request/response 모델 |
| `alembic.ini` | 서비스별 Alembic 설정, migration script 위치 지정 |
| `alembic/env.py` | `DATABASE_URL`과 `Base.metadata`를 연결하는 migration 실행 환경 |
| `alembic/versions/` | 서비스 DB schema 변경 이력을 담는 revision 파일 |
| `dependencies.py` | 공통 Depends, 인증/헤더 검증 의존성 |
| `services/` | 비즈니스 로직 분리 |
| `routes/` | HTTP 라우터 정의 |
| `middleware/` | 서비스 전용 미들웨어 |

> 작은 서비스에서는 `dependencies.py`, `services/`, `middleware/` 일부가 없을 수 있다. 다만 생략 시에도 책임 분리는 유지한다.

---

## 6. 의존성 관리 규칙

- Python 패키지 버전 고정은 루트 `requirements/constraints.txt`를 기준으로 한다.
- 서비스별 `requirements.txt`는 직접 버전을 고정하지 않고, 가능하면 아래 공통 파일을 참조한다.
  - `requirements/web-common.txt`: FastAPI, httpx, DB-free OpenTelemetry, structlog 등 DB가 없어도 필요한 런타임 의존성
  - `requirements/db-common.txt`: `web-common` + SQLAlchemy, asyncpg, SQLAlchemy 계측 등 DB 보유 서비스 런타임 의존성
  - `requirements/migration.txt`: Alembic migration 명령/테스트 전용 의존성
  - `requirements/service-common.txt`: 과거 호환용 파일. 새 Dockerfile과 새 서비스에서는 사용하지 않는다.
  - `requirements/test-common.txt`: pytest, pytest-asyncio, httpx, aiosqlite 등 테스트 공통 의존성
- 서비스 고유 의존성만 각 서비스의 `requirements.txt`에 추가한다.
  - 예: user-service의 `redis`, `passlib`, `python-jose`
  - 예: product-service의 `redis`
  - 예: order-service의 `nats-py`
- Alembic은 앱 runtime 이미지에 포함하지 않는다. migration 명령과 Alembic 설정 테스트는 host/dev/CI 환경에서
  `requirements/migration.txt`를 추가 설치해 실행한다.
- 새 의존성을 추가할 때는 먼저 `constraints.txt`에 버전을 고정한 뒤, 필요한 common 또는 서비스별 requirements에 이름만 추가한다.
- Dockerfile에서는 레포 루트의 `requirements/` 디렉터리를 먼저 복사한 뒤 서비스별 requirements를 설치한다.
- DB가 없는 서비스는 `web-common`, DB 보유 서비스는 `db-common` 기반 이미지를 사용한다.
- 버전 업그레이드가 발생하면 `docs/micromart_design.md`의 기술 스택 표와 관련 References 문서를 함께 갱신한다.

---

## 7. `config.py` 규칙

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
| `user-service` | `SERVICE_NAME`, `SERVICE_VERSION`, `DEBUG`, `LOG_FORMAT`, `DATABASE_URL`, `REDIS_URL`, `JWT_PRIVATE_KEY_FILE`, `JWT_PUBLIC_KEY_FILE`, `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`, `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` |
| `product-service` | `SERVICE_NAME`, `SERVICE_VERSION`, `DEBUG`, `LOG_FORMAT`, `DATABASE_URL`, `REDIS_URL`, `REDIS_SOCKET_CONNECT_TIMEOUT`, `REDIS_SOCKET_TIMEOUT`, `INTERNAL_SERVICE_TOKEN`, `PRODUCT_CACHE_TTL`, `DEFAULT_PAGE_SIZE`, `MAX_PAGE_SIZE`, `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` |
| `order-service` | `SERVICE_NAME`, `SERVICE_VERSION`, `DEBUG`, `LOG_FORMAT`, `DATABASE_URL`, `INTERNAL_SERVICE_TOKEN`, `PRODUCT_SERVICE_URL`, `PAYMENT_SERVICE_URL`, `MAX_OPTIMISTIC_RETRY`, `HTTP_TIMEOUT_SECONDS`, `NATS_URL`, `NATS_CONNECT_TIMEOUT_SECONDS`, `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` |
| `payment-service` | `SERVICE_NAME`, `SERVICE_VERSION`, `DEBUG`, `LOG_FORMAT`, `DATABASE_URL`, `INTERNAL_SERVICE_TOKEN`, `CHAOS_FAILURE_RATE`, `CHAOS_LATENCY_MS`, `CHAOS_DB_SLOWQUERY`, `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` |
| `notification-service` | `SERVICE_NAME`, `SERVICE_VERSION`, `DEBUG`, `LOG_FORMAT`, `NATS_URL`, `NATS_SUBJECT_ORDER_COMPLETED`, `NATS_CONNECT_TIMEOUT_SECONDS`, `NOTIFICATION_SEND_DELAY_MS`, `NOTIFICATION_FAILURE_RATE`, `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE` |
| `shared/telemetry` | `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE`, `LOG_FORMAT`, `SERVICE_VERSION` |

`shared/telemetry`는 `config.py`의 `TelemetrySettings`에서 위 환경변수를 읽는다. 각 서비스의 `init_telemetry()` 호출은 서비스명과 DB engine만 넘기고, OTLP endpoint나 로그 포맷은 공통 설정이 프로세스 환경변수에서 로딩한다.

---

## 8. `database.py` 규칙

- SQLAlchemy 2.0 async 스타일을 사용한다.
- 세션 의존성은 `AsyncSession` 기반 generator로 제공한다.
- PostgreSQL 계열 엔진은 settings.db_pool_size, settings.db_max_overflow를 사용하고, SQLite 테스트 엔진에는 pool 옵션을 넘기지 않는다.
- `expire_on_commit=False`를 기본값으로 사용한다.
- 공통 타입 별칭 `DBSession`을 사용해 라우터 시그니처를 단순화한다.
- Redis는 **사용하는 서비스만** 정의한다. Redis가 필요 없는 서비스는 `config.py`와
  `database.py`에 Redis 설정을 추가하지 않는다.

  > 현재 Redis 사용 서비스: `user-service`, `product-service`
  > Redis 미사용 서비스: `order-service`, `payment-service`, `notification-service`

### Alembic migration 규칙

- PostgreSQL DB를 보유한 서비스(`user-service`, `product-service`, `order-service`, `payment-service`)는 서비스별 `alembic.ini`와 `alembic/` 디렉터리를 둔다.
- Alembic history는 전역으로 합치지 않는다. 각 서비스 DB는 독립적인 `alembic_version` 테이블을 가진다.
- Alembic `env.py`는 migration에 필요한 `DATABASE_URL`과 `app.models.Base.metadata`만 사용한다. JWT key, Redis, `INTERNAL_SERVICE_TOKEN` 같은 런타임 설정 검증에 migration 실행이 묶이지 않게 한다.
- 서비스 코드가 `postgresql+asyncpg://` URL을 사용하므로 Alembic도 SQLAlchemy async migration 패턴을 사용한다.
- `Base.metadata.create_all()`은 debug/test 편의용으로만 사용하고, 실제 schema 이력 관리는 Alembic revision으로 남긴다.
- 이미 `create_all()`로 테이블이 생성된 DB에 첫 migration을 적용할 때는 `upgrade head`가 중복 테이블 오류를 낼 수 있다. 기존 schema가 revision과 동일한지 확인한 뒤 `stamp head`를 쓰거나, 빈 DB에서 migration을 적용한다.

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
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
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

## 9. `models.py` 규칙

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

## 10. 상태값 규칙

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

## 11. `schemas.py` 규칙

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

## 12. 라우터 규칙

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

## 13. 서비스 간 호출 규칙

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

## 14. API 경계 규칙

- 외부 클라이언트용 API와 내부 서비스용 API를 구분한다.
- 내부 서비스 전용 API는 인증 헤더 없이는 접근할 수 없어야 한다.
- 관리자 전용 기능은 역할 기반 권한 검사를 거친다.
- 외부 공개 API는 입력 검증과 권한 검사를 우선한다.
- 내부 API는 명세 문서에 요청/응답 형태를 먼저 정의한 뒤 구현한다.
- `user_id`는 바디가 아닌 `X-User-ID` 헤더에서만 추출한다. gateway를 우회한 직접 호출로 user_id를 위조하는 공격을 방어한다.

---

## 15. 비즈니스 로직 규칙

- 결제, 주문, 재고 차감처럼 실패 가능성이 높은 로직은 단계별 상태를 남긴다.
- 보상 트랜잭션이 필요한 로직은 중간 상태를 DB에 저장해 복구 가능하게 만든다.
- 중복 처리 방지가 필요한 기능은 애플리케이션 레벨 검사와 DB 제약을 함께 사용한다.
- "성공 경로"뿐 아니라 "실패 경로"와 "부분 실패"를 먼저 설계하고 구현한다.
- 보상 트랜잭션은 best-effort로 처리하되, 미완료 상태(`STOCK_ROLLBACK_NEEDED`)를 DB에 커밋해 배치 복구 잡이 스캔할 수 있도록 한다.

---

## 16. 로깅 / 관찰성 규칙

- 모든 서비스는 `shared/telemetry` 공통 모듈을 우선 사용한다.
- 로그는 구조화된 JSON 형식을 사용한다.
- trace_id, span_id, service name을 로그에 포함한다.
- 비즈니스 이벤트는 의미 있는 event명을 사용한다. 예: `payment_approved`, `payment_rejected`, `stock_conflict`
- 에러 로그에는 가능한 범위에서 원인 분류값(`failure_reason`)을 남긴다.
- 각 서비스의 핵심 비즈니스 이벤트는 OpenTelemetry Counter/Histogram 메트릭으로 계측한다.

### NATS consumer 서비스 규칙

- NATS 연결은 lifespan에서 시도하고, 연결 실패가 서비스 기동 실패가 되어야 하는지 먼저 기능 정의 문서에 명시한다.
- best-effort consumer는 연결 실패를 `/health`와 warning 로그로 드러내되 앱 기동은 유지할 수 있다.
- NATS callback에는 복잡한 비즈니스 로직을 직접 두지 않고, raw message payload를 `services/` 계층 함수로 넘긴다.
- 메시지 처리 실패는 reason 값을 낮은 카디널리티로 분류해 로그와 메트릭에 남긴다.
- `order_id`, `user_id`, `payment_id` 같은 ID 값은 로그 필드로는 사용할 수 있지만 Prometheus/OTel metric label에는 넣지 않는다.

---

## 17. 보안 규칙

- `INTERNAL_SERVICE_TOKEN` 기본값은 개발용으로만 사용하고 운영에서는 반드시 변경한다.
- private key, DB password, secret token은 절대 코드에 하드코딩하지 않는다.
- 민감 정보(비밀번호, Refresh Token 원문)는 로그에 남기지 않는다.
- 내부 서비스 토큰 비교는 `hmac.compare_digest`를 사용하여 타이밍 공격을 방지한다.
- 외부 노출이 필요 없는 서비스(`payment-service`, `notification-service`)는 gateway 뒤 또는 내부 네트워크에만 두는 것을 전제로 설계한다.

---

## 18. 테스트 / 검증 규칙

- 최소한의 정상 흐름과 실패 흐름을 직접 검증한다.
- 테스트 디렉터리 이름은 `tests/`를 표준으로 사용한다.
- 모델 변경 시 생성/조회/상태 변경이 의도대로 되는지 확인한다.
- 내부 API는 인증 헤더 누락 케이스를 검증한다.
- 결제/주문/재고 차감 로직은 멱등성, 충돌, 예외 상황을 우선 테스트한다.
- 테스트 공통 의존성은 `requirements/test-common.txt`를 기준으로 하고, 서비스별 테스트 전용 requirements가 필요하면 해당 서비스 `tests/` 아래에 둔다.

---

## 19. 린트 / 포맷 규칙

- 루트 `pyproject.toml`을 기준으로 Ruff, Black, mypy 설정을 공유한다.
- Ruff는 `E`, `W`, `F`, `I`, `B`, `UP` 규칙을 기본 적용한다.
- `UP042`는 예외로 둔다. 상태값 Enum은 프로젝트 도메인 문서 기준에 따라 `str + enum.Enum` 형태를 유지한다.
- FastAPI의 `Depends`, `Query`, `Header` 등은 기본 인자로 사용하는 공식 패턴이므로 Ruff B008 예외 목록에 포함한다.
- 라인 길이는 100자를 기준으로 한다.

---

## 20. Docker Compose / Kubernetes 로컬 실행 규칙

- 서비스 Dockerfile은 레포 루트를 build context로 전제한다.
- 공통 런타임 의존성은 `docker/base/web-common.Dockerfile`과 `docker/base/db-common.Dockerfile`에서 먼저 설치한다.
  서비스 Dockerfile은 Compose `additional_contexts`로 전달되는 `web_common_base` 또는 `db_common_base`를 `FROM`으로 사용한다.
- Dockerfile의 `pip install`과 `apt-get install`은 BuildKit cache mount를 사용한다. pip 설치에는 `--no-cache-dir`를 쓰지 않는다.
  cache mount 내용은 최종 이미지 레이어에 포함되지 않는다.
- `apt-get` cache mount는 Compose 병렬 빌드를 고려해 `sharing=locked`를 사용한다.
- Dockerfile은 `requirements/`를 먼저 복사한 뒤 서비스별 `requirements.txt`를 설치한다.
- Docker build context에는 `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, `.pip-audit-cache`,
  `__pycache__` 같은 로컬 캐시 디렉터리를 포함하지 않는다.
- 런타임 이미지는 `/app`을 작업 디렉터리로 사용하고 `PYTHONPATH=/app`을 설정한다.
- 애플리케이션 컨테이너는 non-root UID/GID `10001`로 실행한다. 이미지 크기 증가를 막기 위해
  `/app/venv` 전체를 `chown -R`하지 말고, 서비스 소스와 shared 소스만 `COPY --chown=10001:10001`로 복사한다.
- 로컬 통합 실행은 Compose 파일을 역할별로 나누어 사용한다.
  - `docker/infra.yaml`: PostgreSQL, Redis, NATS
  - `docker/observability.yaml`: OTel Collector, Prometheus, Loki, Tempo, Grafana
  - `docker/services.yaml`: 애플리케이션 서비스
- 헬스체크는 런타임 이미지에 curl/wget을 추가하지 않기 위해 Python stdlib `urllib.request` 사용을 기본으로 한다.

### Kubernetes manifest 규칙

- Kubernetes 애플리케이션 서비스는 `k8s/services/base/<service-name>/` 아래에
  `deployment.yaml`, `service.yaml`, `kustomization.yaml`을 둔다.
- 로컬 Kubernetes 실행은 `k8s/services/overlays/local/` overlay를 사용한다.
  이 overlay는 서비스별 ConfigMap, local namespace, image tag를 생성 또는 조합한다.
  local overlay의 기본 이미지 주소는 `172.25.46.10:32000/<service-name>:local`이다.
- 각 애플리케이션 Deployment는 `/health`를 `livenessProbe`와 `readinessProbe`로 사용한다.
  `/health`는 인증 없이 호출 가능해야 하며, probe 때문에 비즈니스 상태가 변경되면 안 된다.
- 환경변수는 `envFrom.configMapRef`와 `envFrom.secretRef`로 주입한다. 민감값을
  ConfigMap에 넣지 않는다.
- 실제 Secret env 파일과 JWT key 파일은 Git에 커밋하지 않는다. Git에는
  `k8s/services/overlays/local/secrets/*.env.example`과 안내 문서만 남기고,
  로컬 실행자는 `.example`을 복사해 실제 값을 채운다.
- local overlay가 참조하는 Secret은 `scripts/apply_local_k8s_secrets.sh`로
  `micro-mart-local` namespace에 고정 이름으로 생성한다. Argo CD는 Git에 없는 Secret 원문을
  생성하지 않는다.
  문서에서는 실행 권한 차이를 피하기 위해 `bash scripts/apply_local_k8s_secrets.sh`로 안내한다.
- `user-service`의 RS256 key는 `k8s/services/overlays/local/secrets/keys/` 아래에
  `public.pem`, `private.pem`으로 복사한 뒤 `jwt-keys` Secret으로 적용한다.
- 앱 local overlay namespace는 `micro-mart-local`이다. PostgreSQL, Redis, NATS,
  OTel Collector 같은 공용 인프라는 `micro-mart` namespace를 사용한다.
  Prometheus, Grafana, Loki, Tempo는 `monitoring` namespace를 사용한다.
- 애플리케이션 컨테이너는 기본적으로 non-root UID/GID `10001`로 실행한다.
  `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`,
  `capabilities.drop: [ALL]`, `seccompProfile: RuntimeDefault`를 적용한다.
- read-only root filesystem을 사용할 때 애플리케이션이 써야 하는 경로는 `/tmp`처럼
  명시적 volume(`emptyDir` 등)으로 제공한다. 이미지 내부 경로에 암묵적으로 쓰지 않는다.

### Kubernetes 리소스 정책

- 애플리케이션 서비스의 초기 resource 기본값은 아래와 같이 둔다.

```yaml
resources:
  requests:
    cpu: "50m"
    memory: "128Mi"
  limits:
    memory: "256Mi"
```

- CPU limit은 초기에는 설정하지 않는다. 낮은 CPU limit은 FastAPI 서비스의 정상 요청도
  throttling하여 관찰성 실습 결과를 왜곡할 수 있으므로, k6 부하 테스트와 Grafana 지표를
  확인한 뒤 결정한다.
- Memory limit은 OOM kill 경계를 명확히 하기 위해 초기값을 둔다. 서비스별 실제 사용량이
  확인되면 `requests`와 `limits`를 서비스별로 조정한다.

### Kubernetes 인프라 / 관찰성 배포 규칙

- PostgreSQL은 Bitnami Helm chart와 `k8s/db/postgresql-config.yaml.example`을 기준으로
  배포한다. chart 기본 설정은 하나의 DB만 자동 생성하므로, 서비스별 DB는 psql 또는 향후
  migration 절차로 생성한다.
- Redis와 NATS는 로컬 학습 환경에서 단일 인스턴스 manifest를 사용할 수 있다.
  Redis manifest는 `redis:8.6.3`, non-root UID/GID `999`, PVC `128Mi`를 기준으로 한다.
  NATS manifest는 `nats:2.14.0`, JetStream enabled, `/tmp/nats` PVC `1Gi`,
  read-only root filesystem을 기준으로 한다.
- OTel Collector는 `micro-mart` namespace에 배포하고, 애플리케이션 서비스는
  `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.micro-mart.svc.cluster.local:4317`로
  데이터를 전송한다.
- Prometheus, Grafana, Loki, Tempo는 `monitoring` namespace에 Helm values 파일로 배포한다.
  OTel Collector는 trace를 Tempo, metric을 Prometheus Remote Write, log를 Loki로 전달한다.

### Kubernetes 외부 노출 규칙

- 로컬 Kubernetes에서 `port-forward` 없이 외부 접근이 필요한 경우 MetalLB와 Envoy Gateway
  기반 Gateway API를 사용한다.
- MetalLB manifest는 `k8s/metallb/` 아래에 둔다. 로컬 기본 IP pool은
  `172.25.46.100-172.25.46.200`이며, 간단한 로컬 로드밸런서 용도로 Layer 2 모드를 사용한다.
- Gateway API manifest는 `k8s/gateway/` 아래에 둔다. Envoy Gateway 설치와 Gateway/HTTPRoute
  적용 절차는 `k8s/gateway/README.md`에 기록한다.
- Argo CD 외부 노출 manifest는 `k8s/argocd/` 아래에 둔다. Gateway TLS Secret은
  `kubernetes.io/tls` 타입이어야 하며, Helm chart가 만드는 Opaque `argocd-secret`을
  Gateway certificateRef로 직접 사용하지 않는다.
- 외부 애플리케이션 트래픽은 `api-gateway`를 통해서만 들어오게 한다. 하위 서비스의 내부 API,
  특히 `payment-service`, `product-service`의 내부 재고 API, `notification-service`는 직접
  외부 노출하지 않는다.
- Grafana처럼 운영/관찰용 UI를 노출할 때는 애플리케이션 라우트와 namespace를 분리한다.
  현재 Grafana Gateway/HTTPRoute는 `monitoring` namespace에 둔다.

---

## 21. 운영 / 배포 확장 규칙

Phase 13~16은 로컬 Kubernetes 구현을 운영 학습 환경으로 확장하는 단계다. 로컬 실행 규칙은
`## 20. Docker Compose / Kubernetes 로컬 실행 규칙`을 기준으로 유지하고, CI/GitOps/AWS 규칙은
아래 기준을 따른다.

### Alerting 규칙

- Alertmanager는 Prometheus 알림 규칙의 receiver 역할을 담당한다.
- 알림 규칙은 기존 서비스 메트릭을 우선 사용한다. 새 메트릭이 필요하면 해당 서비스 구현 문서와
  References 문서에 먼저 이름, 타입, 레이블을 정의한다.
- 알림 레이블에는 `order_id`, `user_id`, `payment_id`, raw token 같은 고카디널리티 또는 민감값을
  넣지 않는다.
- 알림 기준은 장애 학습 시나리오와 연결한다. 예: 결제 p99 지연, 결제 실패율, gateway 5xx,
  gateway 인증 실패, rate limit 급증, 주문 실패율/완료율, Saga 보상 증가, 상품 재고 경합,
  캐시 미스율 증가, notification 실패, NATS 연결 끊김, OTel 수집 중단.
- Alertmanager receiver는 Phase 13 기준 Slack Incoming Webhook을 사용한다. 실제 webhook URL은
  Git에 커밋하지 않고 Helm 배포 시 `--set-file`로 주입한다.
- 현재 `k8s/observability/prometheus-values.yaml`은 로컬 학습 환경 기준이므로 대부분의 alert `for`는
  `1m`, Alertmanager `group_wait`은 `10s`, `repeat_interval`은 `10m`처럼 짧게 둔다. staging/prod
  환경 values를 만들 때는 일시적 배포와 scrape 지연을 흡수하도록 더 긴 값을 사용한다.

### CI workflow 규칙

- GitHub Actions workflow는 `.github/workflows/` 아래에 둔다.
- 기존 `validate-pinned-versions.yml`은 `requirements/constraints.txt`의 PyPI pin 존재 여부를
  계속 검증한다.
- PR 기준 종합 CI는 `.github/workflows/ci.yml`에 두고, `main`과 `feat/**` 대상 pull request에서
  실행한다.
- PR 기준 CI는 최소한 서비스별 pytest, Ruff, Black, mypy smoke check, Docker build 검증,
  `kustomize build` 검증, Gitleaks, pip-audit, Bandit, kube-linter를 포함한다.
- CI는 클러스터에 직접 배포하지 않는다. `kubectl apply`, Helm upgrade, Argo CD sync 실행은
  GitOps phase의 명시적 배포 흐름에서만 다룬다.
- 서비스별 테스트는 실제 `services/<service-name>/tests/`가 있는 서비스만 실행한다. 테스트가 없는
  서비스는 CI에서 실패시키지 말고, References 문서에 테스트 공백으로 기록한다.
- Python 버전은 프로젝트 기준인 3.12를 사용한다.
- mypy는 여러 서비스의 `app` 패키지를 한 번에 검사하지 않는다. 서비스들이 동일한 top-level package
  이름을 사용하므로 `shared`를 먼저 검사하고, 각 서비스 디렉터리에서 `app`을 개별 검사한다.
- 현재 mypy는 엄격한 타입 보장보다 명백한 타입 오류를 막는 smoke check 용도로 사용한다.
  서비스별 타입 품질이 올라가면 `ignore_missing_imports`와 `strict` 옵션을 단계적으로 강화한다.
- Docker build는 레포 루트를 build context로 사용한다.
- local Kustomize overlay 검증 시 실제 secret 파일을 Git에 커밋하지 않는다. local overlay는
  고정 이름 Secret을 참조하므로 CI runner는 Secret 원문 없이 `kustomize build`를 실행할 수 있다.
- kube-linter는 source YAML이 아니라 Kustomize 렌더링 결과를 대상으로 실행한다. 렌더링은
  `security-gates` job에서 한 번만 수행해 중복 검증을 피한다.
- Bandit은 `services`, `shared`, `scripts`를 검사하되 `tests`와 `alembic`은 제외한다. 초기 실패
  기준은 medium 이상 severity다.
- pip-audit는 취약한 dependency가 발견되면 기본적으로 고정 버전을 업그레이드한다. 예외가 필요하면
  vulnerability ID, 사유, 만료 기준을 Phase References 문서에 기록한다.
- pip-audit는 constraints 파일만이 아니라 서비스별 requirements 설치 결과도 검사한다. extras 기반
  transitive dependency가 누락되지 않도록 installed environment audit을 유지한다.
- workflow가 민감값을 필요로 하면 GitHub Actions secrets를 사용하고, secret 값을 로그에 출력하지
  않는다.
- workflow 권한은 필요한 최소 권한으로 제한한다. Phase 14 PR CI 기준 권한은 `contents: read`와
  Gitleaks PR commit 조회를 위한 `pull-requests: read`다.
- 외부 GitHub Action은 mutable tag 대신 full commit SHA로 고정한다. checkout step은 기본 동작에
  의존하지 않고 `persist-credentials: false`를 명시한다.

### GitOps / CD 규칙

- CD의 기준 상태는 클러스터가 아니라 Git repository다.
- Argo CD Application은 환경별 overlay를 바라본다. local, staging, prod가 생기면 각각 별도 overlay와
  Application으로 분리한다.
- CI는 이미지 빌드/푸시와 manifest image tag 갱신까지만 담당한다. 실제 동기화는 Argo CD가 수행한다.
- 로컬 CD는 `.github/workflows/cd-local-gitops.yml`에서 WSL2 Ubuntu self-hosted runner를 사용한다.
  runner는 `self-hosted`, `Linux`, `X64` label을 가져야 하고, Docker build/push와
  `172.25.46.10:32000` registry 접근이 가능해야 한다.
- 로컬 CD의 이미지 build/push는 기존 수동 배포와 동일하게 `docker/services.yaml`을 사용한다.
  workflow는 `REGISTRY`와 `TAG` 환경변수로 Compose image 이름을 제어한다.
- 로컬 CD image tag는 `${GITHUB_SHA::12}`를 사용한다. 고정 `local` 태그는 수동 로컬 배포용으로만
  사용할 수 있고, GitOps CD에서는 commit SHA tag로 배포 이력을 남긴다.
- CD workflow가 overlay tag 갱신 commit을 push해야 하므로 해당 workflow만 `contents: write` 권한과
  checkout credentials를 사용할 수 있다. PR CI workflow는 계속 read-only 권한을 유지한다.
- CD workflow는 main 배포 작업을 concurrency group으로 직렬화하고, overlay tag commit 직전
  `origin/main`을 rebase한 뒤 image tag를 다시 설정한다.
- 로컬 Argo CD Application은 `gitops/argocd-applications/micro-mart-local.yaml`에 두고,
  `k8s/services/overlays/local`을 바라본다.
- local Secret은 GitOps 대상이 아니므로 Application sync 전에
  `bash scripts/apply_local_k8s_secrets.sh`로 고정 이름 Secret을 먼저 적용한다.
- 로컬 Chaos Mode와 부하 테스트의 배포 타이밍을 사람이 통제할 수 있도록 Phase 15 local Application은
  automated sync, prune, self-heal을 켜지 않는다. 수동 sync로 diff 확인 후 반영한다.
- feature branch에서 GitOps를 테스트할 때는 Application의 `targetRevision`을 임시 branch로 바꾸고,
  테스트 후 `main`으로 되돌린다. Secret 존재 여부는 branch가 아니라 클러스터 선적용 상태에 의해 결정된다.
- main merge 직후에는 CD workflow가 commit SHA image tag 갱신 commit을 성공시킨 뒤 Argo CD manual
  sync를 실행한다.
- 수동으로 클러스터 리소스를 수정해 drift가 생기면 Argo CD diff를 확인하고 Git 기준으로 복구한다.
- 내부 전용 서비스와 내부 API는 GitOps 배포 후에도 Gateway API나 LoadBalancer로 직접 노출하지 않는다.
- secret manifest 원본은 Git에 커밋하지 않는다. Git에는 `.example`, sealed secret, external secret
  정의처럼 원문 secret이 없는 자료만 남긴다.

### AWS / Terraform 규칙

- Terraform 코드는 향후 `infra/terraform/` 아래에 환경별 root module과 재사용 module을 분리해 둔다.
- Terraform state는 로컬 파일이 아니라 S3 backend와 DynamoDB lock을 기본으로 설계한다.
- AWS 배포 기본값은 학습용 최소형 EKS다. 운영형 HA, 멀티 리전, 고급 백업 정책은 별도 phase에서
  다룬다.
- Terraform은 VPC, EKS, RDS PostgreSQL, ElastiCache Redis, IAM/IRSA, Secrets Manager, remote backend
  같은 클라우드 인프라를 관리한다.
- 애플리케이션 manifest 배포는 Terraform이 아니라 GitOps가 담당한다.
- AWS secret, DB password, JWT private key, internal token은 Terraform 코드나 tfvars에 평문으로
  커밋하지 않는다.
- RDS에서도 서비스별 DB 분리 원칙을 유지하고, 서비스 코드가 다른 서비스 DB에 직접 접근하지 않게 한다.
- EKS 외부 노출은 AWS Load Balancer Controller 또는 Gateway API 연계를 사용하되, 외부 애플리케이션
  트래픽은 계속 `api-gateway` 단일 진입점으로 제한한다.

---

## 22. 문서 동기화 규칙

다음 변경이 발생하면 관련 문서를 함께 갱신한다.

- 모델 변경 → `ERD_structure.md`
- 엔드포인트/호출 흐름 변경 → `service_function_definition.md`
- 아키텍처/구현 현황 변경 → `README.md`, `micromart_design.md`
- 공통 코드 작성 방식 변경 → `dev_convention.md`
- Alerting/CI/GitOps/AWS phase 변경 → `micromart_design.md`, `service_function_definition.md`,
  `dev_convention.md`

> ⚠️ 새 서비스의 `routes`, `schemas`, 내부/외부 호출 로직을 작성하기 전에 반드시 `service_function_definition.md`를 먼저 확인한다.

---

## 23. 커밋 / 작업 규칙

- 자동 커밋하지 않는다.
- 의미 없는 대규모 리팩터링을 한 번에 진행하지 않는다.
- 리뷰 피드백은 옳고 그름을 먼저 분석한 뒤 반영한다.
- 구현 중 컨벤션과 충돌하는 예외가 있으면 이유를 먼저 설명하고 진행한다.

---

## 24. 체크리스트

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
