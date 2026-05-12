# user-service Reference

## 1. 문서 목적

이 문서는 `user-service`를 처음 읽는 팀원이나 미래의 내가 인증 설계의 의도와 구현 경계를 빠르게 복원하도록 돕는 학습용 레퍼런스다.

기준 문서는 다음 역할로 나누어 본다.

- `docs/ERD_structure.md`: `users` 테이블과 `token_version`의 도메인 기준
- `docs/service_function_definition.md`: `/auth/*` 엔드포인트 계약
- `docs/micromart_design.md`: 전체 인증 아키텍처와 gateway 연계
- `docs/dev_convention.md`: FastAPI, 설정, 테스트, 보안 컨벤션

이 문서를 읽고 나면 회원가입, 로그인, Refresh Token Rotation, 로그아웃, JWKS 제공이 어떤 책임 경계로 분리되어 있는지 설명할 수 있어야 한다.

## 2. 서비스 역할과 경계

`user-service`는 사용자 인증과 토큰 수명주기를 담당한다. 회원가입, 로그인, Access Token 발급, Refresh Token 저장/회전/폐기, JWKS 공개키 제공이 핵심 책임이다.

하지 않는 일도 명확하다. 외부 요청 라우팅은 `api-gateway`가 담당하고, 하위 서비스 권한 판단은 gateway가 주입한 헤더를 기준으로 각 서비스가 수행한다. 다른 서비스의 DB에는 접근하지 않으며, 주문/상품/결제 도메인 판단을 하지 않는다.

외부 API는 gateway를 통해 `/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/jwks`로 노출된다. 내부 전용 `X-Internal-Token` API는 없다.

## 3. 빠른 구조 지도

```text
services/user-service/
├── app/
│   ├── main.py                 # FastAPI 앱, telemetry/logging, health
│   ├── config.py               # JWT 키 로딩, DB/Redis/OTel 설정
│   ├── database.py             # SQLAlchemy async DB, Redis client
│   ├── models.py               # User, BigIntegerType
│   ├── schemas.py              # auth 요청/응답 스키마
│   ├── auth.py                 # JWT, 비밀번호, Refresh Token Redis 헬퍼
│   ├── routes/auth.py          # HTTP 경계
│   └── services/auth_service.py # 인증 비즈니스 로직, JWKS 생성
└── tests/
    ├── test_auth_routes.py
    ├── test_auth_service.py
    ├── test_auth_utils.py
    └── test_refresh_rotation.py
```

라우터는 요청 스키마와 상태 코드만 다루고, 회원가입/로그인/토큰 회전 판단은 `auth_service.py`에 둔다. Redis 키 생성, JWT encode/decode, 비밀번호 검증 같은 저수준 동작은 `auth.py`가 담당한다.

## 4. 핵심 흐름

회원가입은 이메일 선조회 후 사용자를 생성하고, DB unique 제약과 `IntegrityError` 처리로 동시 가입 경쟁을 한 번 더 막는다.

로그인은 이메일과 비밀번호를 검증한 뒤 RS256 Access Token과 기기별 Refresh Token을 발급한다. Refresh Token은 Redis 정방향 키(`refresh:user:{id}:{device}`)와 역방향 키(`refresh:token:{token}`)를 함께 사용한다.

Refresh는 역방향 키로 토큰 소유자를 찾고, 저장값 불일치나 tombstone 재사용을 감지하면 해당 사용자의 모든 Refresh Token을 폐기한다. 정상 요청은 기존 토큰을 회전하고 새 Access/Refresh Token을 반환한다.

로그아웃은 Access Token의 `sub`와 Refresh Token 소유자가 같은지 확인한다. 이미 회전되었거나 삭제된 Refresh Token은 로그아웃 목적이 달성된 상태로 보고 `204`를 유지한다.

`/auth/jwks`는 gateway가 JWT를 로컬 검증할 수 있도록 공개키를 JWKS 형식으로 제공한다.

## 5. 핵심 설계 결정

| 결정 | 선택 | 대안 | 선택 이유 | 트레이드오프 |
| --- | --- | --- | --- | --- |
| JWT 서명 | RS256 | HS256 공유 secret | private key를 user-service에만 두고 gateway는 public key로 검증 가능 | 키 파일/환경변수 관리가 필요 |
| Refresh Token | Redis 저장 + Rotation | stateless refresh token | 재사용 감지와 기기별 세션 폐기가 가능 | Redis 장애 시 refresh 흐름이 영향받음 |
| Redis 키 | 정방향 + 역방향 키 | user_id 기준 키만 저장 | 토큰 원문으로 소유자 조회와 재사용 감지가 가능 | 저장 키가 늘고 삭제 대칭성이 중요 |
| 중복 가입 | 앱 선조회 + DB unique | DB unique만 사용 | 사용자에게 명확한 409를 주면서 race condition도 방어 | 동일 검사가 두 번 존재 |
| 키 로딩 | 파일 경로 또는 PEM 문자열 | 한 방식만 지원 | 로컬 Docker secret과 Kubernetes env 주입을 모두 지원 | 설정 검증 로직이 조금 복잡 |

## 6. 데이터와 계약

주요 데이터는 `users` 테이블이다. `email`, `hashed_password`, `role`, `token_version`, `is_active`를 저장하고, PK는 SQLite 테스트 호환을 위해 `BigIntegerType`을 사용한다.

주요 스키마는 `RegisterRequest`, `LoginRequest`, `RefreshRequest`, `LogoutRequest`, `TokenResponse`다. `device`는 기기별 Refresh Token 세션을 구분한다.

엔드포인트 요약:

| Method | Path | 목적 |
| --- | --- | --- |
| POST | `/auth/register` | 사용자 생성 |
| POST | `/auth/login` | Access/Refresh Token 발급 |
| POST | `/auth/refresh` | Refresh Token Rotation |
| POST | `/auth/logout` | 현재 기기 세션 폐기 |
| GET | `/auth/jwks` | gateway 검증용 공개키 제공 |

주요 환경변수는 `DATABASE_URL`, `REDIS_URL`, `JWT_PRIVATE_KEY_FILE`, `JWT_PUBLIC_KEY_FILE`, `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`다.

## 7. 관찰성

`shared.telemetry`의 `RequestLoggingMiddleware`, `init_telemetry`, `init_logging`을 사용한다. 로그에는 `신규 회원가입`, `로그인 성공`, `로그인 실패 - 잘못된 자격증명`, `Refresh Token 재사용 감지`, `토큰 재발급 완료`, `로그아웃 완료` 같은 인증 이벤트가 남는다.

메트릭은 `login_total`, `register_total`, `token_refresh_total`을 사용한다. `login_total`은 `result` 레이블로 성공, 실패, 비활성 계정을 구분한다.

TraceContext는 gateway에서 들어온 요청을 FastAPI/OTel 계측으로 이어받는다. 비밀번호와 Refresh Token 원문은 로그에 남기지 않는다.

## 8. 테스트와 검증

핵심 테스트는 라우트, 서비스 로직, auth 유틸, Refresh Token Rotation으로 나뉜다.

대표 검증 명령:

```powershell
pytest services/user-service/tests -q
```

검증해야 할 시나리오는 중복 이메일 409, 로그인 실패 메시지 모호화, 비활성 계정 차단, Refresh Token 재사용 감지, 로그아웃 소유자 불일치 403, JWKS 응답 구조다.

## 9. 자주 발생한 오류와 트러블슈팅

| 증상 | 원인 | 해결 | 재발 방지 |
| --- | --- | --- | --- |
| 앱 시작 시 JWT 키 오류 | 키 파일/PEM 환경변수 누락 | `.env.example` 기준으로 private/public key 주입 | 로컬 실행 전 키 생성 스크립트와 env 확인 |
| Refresh 후 기존 토큰이 계속 동작 | 정방향/역방향 키 삭제 대칭성 누락 | rotation 시 기존 역방향 키를 tombstone으로 교체 | Redis 키 생명주기 테스트 유지 |
| 테스트에서 설정 변경 미반영 | `get_settings()` 캐시 | 테스트 전후 cache clear 또는 dependency override | 설정 의존 테스트는 fixture에서 초기화 |
| 계정 존재 여부 노출 | 로그인 실패 사유를 분리 응답 | 동일한 401 메시지 사용 | 보안 응답 문구를 테스트로 고정 |

## 10. 왜 이 설계인가

인증은 시스템 전체 신뢰 경계의 시작점이다. MicroMart에서는 하위 서비스가 JWT를 직접 검증하지 않고, `api-gateway`가 검증 후 사용자 헤더를 주입한다. 그래서 `user-service`는 토큰 발급과 공개키 제공에 집중하고, gateway는 검증과 라우팅에 집중한다.

Refresh Token은 단순히 긴 TTL 토큰을 주는 기능이 아니라 세션 회수와 재사용 탐지의 핵심 장치다. Redis를 사용하면 기기별 로그아웃과 강제 폐기를 빠르게 처리할 수 있고, DB의 `token_version`은 Redis가 놓칠 수 있는 전체 무효화 기준을 보완한다.

이 서비스의 설계 기준은 “인증 판단은 엄격하게, 라우터는 얇게, 민감 정보는 남기지 않게”다. 기능 수는 많지 않지만 보안 사고의 폭발 반경이 크기 때문에 중복 방어와 명확한 실패 처리가 의도적으로 들어가 있다.
