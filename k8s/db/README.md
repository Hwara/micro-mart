# DB 구축

명령어는 repository root 기준으로 실행한다.
PostgreSQL과 Redis는 애플리케이션 namespace인 `micro-mart-local`이 아니라 공용 인프라 namespace
`micro-mart`에 배포한다.

## 1. helm으로 구축

1. `postgresql-config.yaml.example`을 따라 `postgresql-config.yaml` 작성
2. `helm repo add bitnami https://charts.bitnami.com/bitnami`
3. `helm repo update`
4. `helm install postgresql bitnami/postgresql -n micro-mart --version 18.6.6 -f postgresql-config.yaml`

> 주의 : default storageclass를 생성해두어야 자동 생성되는 PVC가 PV를 생성
> storageclass 가 따로 없다면 직접 PV 생성 및 설정 필요

현재 `userdb` 외 DB가 기본으로 생성되지 않기 때문에 psql을 이용해 직접 DB에 접근하여 다음의 명령을 실행해주어야 함

```sql
-- userdb는 이미 있으면 생략
CREATE DATABASE userdb;
CREATE DATABASE productdb;
CREATE DATABASE orderdb;
CREATE DATABASE paymentdb;
```

각 DB의 schema는 서비스별 Alembic migration으로 관리한다.

## 2. Alembic migration 적용

Alembic은 애플리케이션 런타임 이미지에 포함하지 않는다. migration은 repository root에서
`requirements/migration.txt`를 설치한 host/dev/CI 환경에서 명시적으로 실행한다.

### 2.1 migration 의존성 설치

이미 프로젝트 가상환경을 사용 중이라면 해당 환경을 활성화한 뒤 실행한다.

```bash
python -m pip install -c requirements/constraints.txt -r requirements/migration.txt
```

### 2.2 Kubernetes PostgreSQL에 접근

로컬 Kubernetes의 PostgreSQL Service는 클러스터 내부 주소이므로 host에서 Alembic을 실행할 때는
port-forward를 사용한다. 로컬 `5432` 포트가 이미 사용 중일 수 있으므로 예시는 `15432`를 사용한다.

```bash
kubectl -n micro-mart port-forward svc/postgresql 15432:5432
```

위 명령은 foreground로 실행되므로, 별도 터미널을 열어 migration 명령을 실행한다.

### 2.3 서비스별 migration 실행

각 서비스는 자기 DB만 migration한다. `DATABASE_URL`은 대상 DB에 맞게 매번 바꿔서 실행한다.

```bash
# user-service -> userdb
DATABASE_URL=postgresql+asyncpg://micromart:micromart@localhost:15432/userdb \
python -m alembic -c services/user-service/alembic.ini upgrade head

# product-service -> productdb
DATABASE_URL=postgresql+asyncpg://micromart:micromart@localhost:15432/productdb \
python -m alembic -c services/product-service/alembic.ini upgrade head

# order-service -> orderdb
DATABASE_URL=postgresql+asyncpg://micromart:micromart@localhost:15432/orderdb \
python -m alembic -c services/order-service/alembic.ini upgrade head

# payment-service -> paymentdb
DATABASE_URL=postgresql+asyncpg://micromart:micromart@localhost:15432/paymentdb \
python -m alembic -c services/payment-service/alembic.ini upgrade head
```

PowerShell에서는 환경변수를 먼저 설정한 뒤 같은 명령을 실행한다.

```powershell
$env:DATABASE_URL = "postgresql+asyncpg://micromart:micromart@localhost:15432/userdb"
python -m alembic -c services/user-service/alembic.ini upgrade head
```

### 2.4 적용 상태 확인

현재 head revision은 DB 연결 없이도 확인할 수 있다.

```bash
python -m alembic -c services/user-service/alembic.ini heads
```

DB에 실제 적용된 revision은 대상 DB의 `DATABASE_URL`을 설정한 뒤 확인한다.

```bash
DATABASE_URL=postgresql+asyncpg://micromart:micromart@localhost:15432/userdb \
python -m alembic -c services/user-service/alembic.ini current
```

### 2.5 주의사항

- `DATABASE_URL`은 반드시 migration 대상 서비스의 DB를 가리켜야 한다. 예를 들어
  `product-service` migration을 `userdb`에 실행하면 안 된다.
- 이미 `DEBUG=True`의 `create_all()` 또는 이전 수동 작업으로 테이블이 만들어진 DB에
  `upgrade head`를 실행하면 중복 테이블 오류가 날 수 있다. 기존 schema가 migration과 동일한지
  확인한 뒤 `stamp head`를 사용하거나, 빈 DB에서 migration을 실행한다.
- migration은 서비스별로 독립적이다. 전역 Alembic history를 만들지 않고 각 DB가 자기
  `alembic_version` 테이블을 가진다.
- 애플리케이션 Deployment는 시작 시 migration을 자동 실행하지 않는다. DB 생성과 migration 적용을
  먼저 끝낸 뒤 서비스를 배포한다.

# Redis 구축

## 1. helm으로 구축

1. `helm install redis bitnami/redis -n micro-mart`

## 2. 기존 작성해둔 statefulset yaml로 단일 서버 구축

helm은 기본적으로 redis-cluster 구축 및 여러 설정이 사용됨.
단일 서버는 간단하게 작성해놓은 yaml 로 구축

1. `kubectl apply -f redis.yaml`
