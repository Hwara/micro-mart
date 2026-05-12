# product-service Reference

## 1. 문서 목적

이 문서는 `product-service`의 상품 조회, 관리자 CRUD, 재고 차감/복구 설계를 학습하기 위한 서비스별 레퍼런스다.

기준 문서와의 관계는 다음과 같다.

- `docs/ERD_structure.md`: `products` 모델, `price`, `stock`, `version`, `is_active` 기준
- `docs/service_function_definition.md`: 외부 상품 API와 내부 재고 API 계약
- `docs/micromart_design.md`: 상품 서비스가 주문 Saga에서 맡는 위치
- `docs/dev_convention.md`: Redis 사용 서비스, 내부 API 인증, 라우터/서비스 분리 규칙

이 문서를 읽고 나면 Cache-Aside, 낙관적 잠금, 소프트 삭제, 내부 서비스 인증이 왜 함께 쓰이는지 설명할 수 있어야 한다.

## 2. 서비스 역할과 경계

`product-service`는 상품 카탈로그와 재고 정합성을 담당한다. 외부에는 상품 목록/상세 조회와 관리자 CRUD를 제공하고, 내부적으로는 `order-service`가 호출하는 재고 차감/복구 API를 제공한다.

하지 않는 일은 주문 생성, 결제 요청, 사용자 인증 검증이다. 사용자 역할은 gateway가 주입한 `X-User-Role` 헤더를 기준으로 판단하고, 내부 서비스 호출은 `X-Internal-Token`으로만 신뢰한다.

Redis는 상품 상세 캐시 용도로만 사용한다. 원본 데이터와 재고 정합성 기준은 PostgreSQL `products` 테이블이다.

## 3. 빠른 구조 지도

```text
services/product-service/
├── app/
│   ├── main.py                       # FastAPI 앱, telemetry/logging, health
│   ├── config.py                     # DB/Redis/내부토큰/페이지/캐시 설정
│   ├── database.py                   # SQLAlchemy async DB, Redis client
│   ├── dependencies.py               # require_admin, verify_internal_service
│   ├── models.py                     # Product, BigIntegerType
│   ├── schemas.py                    # 상품/재고 요청 응답
│   ├── cache.py                      # Redis Cache-Aside 헬퍼
│   ├── routes/products.py            # HTTP 경계
│   └── services/product_service.py   # CRUD, 캐시, 재고 비즈니스 로직
└── tests/
    ├── test_cache.py
    ├── test_config.py
    ├── test_dependencies.py
    ├── test_product_routes.py
    └── test_product_service.py
```

라우터는 인증 의존성, 쿼리 파라미터, 응답 모델을 담당한다. 상품 조회, 캐시 무효화, 재고 차감 조건 분기는 `product_service.py`에 둔다.

## 4. 핵심 흐름

상품 상세 조회는 Cache-Aside 흐름이다. Redis에 상품 JSON이 있으면 바로 반환하고, 없으면 DB에서 활성 상품을 조회한 뒤 `PRODUCT_CACHE_TTL` 동안 캐시에 저장한다.

상품 생성/수정/삭제는 관리자 전용이다. 수정과 삭제 후에는 기존 상세 캐시를 삭제해 다음 조회에서 DB 최신 상태가 반영되도록 한다.

재고 차감은 `POST /products/{id}/deduct-stock` 내부 API로 처리한다. 단일 `UPDATE ... WHERE id AND is_active AND version AND stock >= quantity` 문으로 재고 충분 여부와 낙관적 잠금을 동시에 검사한다. 실패 시 현재 상품 상태를 조회해 `VERSION_CONFLICT`, `INSUFFICIENT_STOCK`, `404`를 구분한다.

재고 복구는 `POST /products/{id}/restore-stock` 내부 API로 처리한다. 보상 트랜잭션은 `stock += quantity`, `version += 1`만 수행하고 version 조건을 걸지 않는다.

## 5. 핵심 설계 결정

| 결정 | 선택 | 대안 | 선택 이유 | 트레이드오프 |
| --- | --- | --- | --- | --- |
| 금액 저장 | 원단위 Integer | Float/Decimal | 원화 금액 계산의 부동소수점 오차 제거 | 소수 통화 확장 시 별도 설계 필요 |
| 조회 캐시 | Cache-Aside | Write-Through | 읽기 부하를 줄이고 구현을 단순하게 유지 | 캐시 무효화 누락 시 stale 위험 |
| 재고 동시성 | 낙관적 잠금 `version` | `SELECT FOR UPDATE` | 고경합에서 DB 락 대기보다 충돌 재시도가 낫다 | 충돌 시 호출자가 재조회/재시도해야 함 |
| 재고 차감 | 단일 UPDATE | SELECT 후 UPDATE | TOCTOU 경쟁 조건을 DB 조건식으로 차단 | 실패 원인 구분을 위해 추가 조회 필요 |
| 삭제 | `is_active=False` | 물리 삭제 | 주문 이력의 논리적 product_id를 보존 | 목록/상세 조회마다 활성 필터 필요 |
| 복구 | version 조건 없음 | 낙관적 잠금 적용 | 보상 트랜잭션이 충돌로 실패하면 재고 영구 소실 위험 | 복구 요청 중복 방지는 호출자 책임 |

## 6. 데이터와 계약

`products`는 `name`, `description`, `price`, `stock`, `version`, `is_active`, timestamp를 가진다. `stock >= 0`은 DB CHECK 제약으로도 막는다.

엔드포인트 요약:

| Method | Path | 경계 |
| --- | --- | --- |
| GET | `/products` | 공개 조회, `active_only=false`는 admin |
| GET | `/products/{id}` | 공개 상세 조회, 활성 상품만 |
| POST | `/products` | admin 전용 |
| PUT | `/products/{id}` | admin 전용 |
| DELETE | `/products/{id}` | admin 전용, 소프트 삭제 |
| POST | `/products/{id}/deduct-stock` | 내부 전용, `X-Internal-Token` |
| POST | `/products/{id}/restore-stock` | 내부 전용, `X-Internal-Token` |

재고 차감 요청은 `{ "quantity": int, "expected_version": int }`이고, 성공 응답은 `{ "product_id": int, "remaining_stock": int, "new_version": int }`다. 복구 요청은 `{ "quantity": int }`만 받는다.

주요 환경변수는 `DATABASE_URL`, `REDIS_URL`, `INTERNAL_SERVICE_TOKEN`, `PRODUCT_CACHE_TTL`, `DEFAULT_PAGE_SIZE`, `MAX_PAGE_SIZE`다.

## 7. 관찰성

로그 이벤트는 상품 생성/수정/삭제, 캐시 hit/miss, 재고 차감 성공, 재고 부족, version 충돌, 재고 복구 완료를 중심으로 남긴다.

메트릭:

| 이름 | 의미 |
| --- | --- |
| `product_cache_hits_total` | Redis 캐시 히트 |
| `product_cache_misses_total` | Redis 캐시 미스 |
| `product_stock_deduct_total` | 재고 차감 요청 |
| `product_stock_insufficient_total` | 재고 부족 실패 |
| `product_stock_conflict_total` | 낙관적 잠금 충돌 |

메트릭 레이블에는 `product_id`를 넣지 않는다. 상품 ID는 로그 필드로는 유용하지만 Prometheus 레이블에 넣으면 카디널리티가 폭발한다.

## 8. 테스트와 검증

대표 검증 명령:

```powershell
pytest services/product-service/tests -q
```

검증 포인트는 Cache-Aside 동작, 관리자 권한, 내부 토큰 누락 403, 상품 CRUD, 소프트 삭제, `VERSION_CONFLICT`, `INSUFFICIENT_STOCK`, 복구 API의 version 미적용이다.

## 9. 자주 발생한 오류와 트러블슈팅

| 증상 | 원인 | 해결 | 재발 방지 |
| --- | --- | --- | --- |
| `409 VERSION_CONFLICT` | 요청의 `expected_version`이 오래됨 | 상품 재조회 후 최신 version으로 재시도 | order-service 재시도 횟수 제한 유지 |
| `409 INSUFFICIENT_STOCK` | 요청 수량이 현재 재고 초과 | 주문 실패 처리와 기존 차감분 롤백 | 재고 부족은 재시도 불가 오류로 분류 |
| 비활성 상품이 일반 사용자에게 보임 | `active_only=false` 권한 분기 누락 | `x_user_role != admin`이면 403 | 라우트/서비스 테스트에 권한 케이스 포함 |
| 내부 재고 API가 외부 호출됨 | `X-Internal-Token` 검증 누락 | `verify_internal_service` 의존성 적용 | 내부 API 테스트에 헤더 누락 케이스 유지 |
| 캐시가 오래된 상품을 반환 | 수정/삭제 후 무효화 누락 | `invalidate_product_cache` 호출 | 캐시 무효화 테스트 유지 |

## 10. 왜 이 설계인가

상품 서비스는 단순 CRUD처럼 보이지만 주문 Saga의 재고 정합성을 떠받치는 서비스다. 그래서 조회 성능을 위한 Redis 캐시와, 재고 정확성을 위한 DB 조건부 UPDATE가 함께 존재한다.

중요한 판단은 “캐시는 성능 보조 수단이고, 재고의 진실은 DB”라는 점이다. 재고 차감은 Redis나 애플리케이션 메모리에서 판단하지 않고, DB의 `stock`과 `version`을 한 번의 UPDATE 조건으로 검사한다.

복구 API에 낙관적 잠금을 걸지 않는 것도 같은 이유다. 보상 트랜잭션은 실패를 되돌리는 안전장치이므로, 일반 차감보다 성공 가능성을 우선한다. 이 설계는 복잡한 분산 락보다 단순한 DB 원자 연산과 명확한 실패 코드로 학습과 검증을 쉽게 만든다.
