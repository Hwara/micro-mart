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

# Redis 구축

## 1. helm으로 구축

1. `helm install redis bitnami/redis -n micro-mart`

## 2. 기존 작성해둔 statefulset yaml로 단일 서버 구축

helm은 기본적으로 redis-cluster 구축 및 여러 설정이 사용됨.
단일 서버는 간단하게 작성해놓은 yaml 로 구축

1. `kubectl apply -f redis.yaml`
