## Phase 0 — .gitignore 작성

```gitignore
# Python
__pycache__/
*.pyc
*.pyo
.venv/
venv/
*.egg-info/
dist/
.pytest_cache/
.mypy_cache/
.ruff_cache/

# 환경변수 (절대 커밋 금지)
.env
.env.*
!.env.example
*.pem
*.key

# IDE
.vscode/
.idea/

# Docker
*.log

# k8s secrets (실제 시크릿 파일은 커밋 금지)
k8s/**/secret.yaml

```

> ⚠️ **`.env`와 `*.pem` 파일은 절대 Git에 올리면 안 됩니다.** JWT 개인키, DB 비밀번호 같은 민감한 정보가 포함되기 때문입니다. `.gitignore`에 미리 등록해두는 것이 첫 번째 보안 습관입니다.

***

## Phase 0 — Python 가상환경 & 공통 개발 도구

이 프로젝트는 서비스가 6개지만, **개발 도구(linting, formatting)는 루트에서 통합 관리**합니다.

```bash
# 루트에 개발 도구용 가상환경 생성
python3.12 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 개발 도구 설치
pip install pre-commit ruff black mypy
```

### pyproject.toml 작성

루트에 `pyproject.toml`을 만듭니다. 이 파일이 **ruff, black, mypy의 설정 중앙 허브** 역할을 합니다.

```toml
[tool.ruff]
target-version = "py312"
line-length = 100
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes (미사용 import 등)
    "I",   # isort (import 순서 정렬)
    "B",   # flake8-bugbear (잠재적 버그 패턴)
    "UP",  # pyupgrade (Python 최신 문법 권장)
]

[tool.black]
line-length = 100
target-version = ["py312"]

[tool.mypy]
python_version = "3.12"
strict = false          # 처음부터 strict하면 부담스러우니 점진적으로 적용
ignore_missing_imports = true
```

> 💡 **ruff vs black 역할 분리**
>
> - **ruff**: 코드 품질 검사 (버그 가능성, 불필요한 import 등) + import 순서 정리
> - **black**: 코드 포맷팅 (들여쓰기, 따옴표, 줄 길이 등 스타일 통일)
> - 두 도구가 충돌하지 않도록 `line-length = 100`을 동일하게 맞춰줍니다.

***

## Phase 0 — pre-commit 훅 설정

`pre-commit`은 `git commit` 실행 시 **자동으로 코드 검사**를 실행해줍니다. 나쁜 코드가 레포에 들어오는 것을 사전에 차단합니다.

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.4
    hooks:
      - id: ruff
        args: [--fix]   # 자동 수정 가능한 것은 자동으로 수정

  - repo: https://github.com/psf/black
    rev: 24.4.2
    hooks:
      - id: black

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy
        additional_dependencies: [pydantic, fastapi]

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace    # 줄 끝 공백 제거
      - id: end-of-file-fixer      # 파일 끝 개행 확인
      - id: check-yaml             # YAML 문법 검사
      - id: check-added-large-files  # 대용량 파일 실수 커밋 방지
      - id: detect-private-key     # 개인키 커밋 방지
```

```bash
# 훅 설치 (이후 git commit마다 자동 실행됨)
pre-commit install
```

> 💡 **`detect-private-key` 훅이 중요한 이유**
> JWT RS256 개인키(`.pem` 파일)를 실수로 커밋하는 사고를 막아줍니다. 실제 사고 사례가 매우 많아서 팀 프로젝트에서는 필수로 넣는 항목입니다.

***

## Phase 0 — 서비스별 requirements.txt 초안

각 서비스 디렉토리에 `requirements.txt`를 만듭니다. 지금은 **공통 의존성만** 넣고, 서비스별 특수 의존성은 각 Phase에서 추가합니다.

아래 명령으로 6개 서비스에 동일한 파일을 한번에 만듭니다.

```bash
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
pydantic-settings>=2.2.0
sqlalchemy[asyncio]>=2.0.0
asyncpg>=0.29.0
httpx>=0.27.0
opentelemetry-sdk>=1.24.0
opentelemetry-exporter-otlp-proto-grpc>=1.24.0
opentelemetry-instrumentation-fastapi>=0.45b0
opentelemetry-instrumentation-sqlalchemy>=0.45b0
opentelemetry-instrumentation-httpx>=0.45b0
structlog>=24.1.0
prometheus-client>=0.20.0
```

> 💡 **왜 서비스마다 requirements.txt를 따로 두나요?**
> 예를 들어 `user-service`는 JWT 라이브러리(`python-jose`)가 필요하지만, `product-service`는 Redis 클라이언트(`redis`)가 필요합니다. 공통 + 서비스별 의존성을 분리하면 **Docker 이미지 크기를 최소화**하고, 의존성 충돌 가능성도 줄일 수 있습니다.
