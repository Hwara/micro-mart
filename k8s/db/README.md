# DB 구축

## 1. helm으로 구축

1. `postgresql-config.yaml.example`을 따라 `postgresql-config.yaml` 작성
2. `helm repo add bitnami https://charts.bitnami.com/bitnami`
3. `helm repo update`
4. `helm install postgresql bitnami/postgresql -n micro-mart --version 18.6.6 -f postgresql-config.yaml`

> 주의 : default storageclass를 생성해두어야 자동 생성되는 PVC가 PV를 생성
> storageclass 가 따로 없다면 직접 PV 생성 및 설정 필요

# Redis 구축

## 1. helm으로 구축

1. `helm install redis bitnami/redis -n micro-mart`

## 2. 기존 작성해둔 statefulset yaml로 단일 서버 구축

helm은 기본적으로 redis-cluster 구축 및 여러 설정이 사용됨.
단일 서버는 간단하게 작성해놓은 yaml 로 구축

1. `kubectl apply -f redis.yaml`
