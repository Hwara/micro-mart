# 현재 구조

- `namespaces/` : 사용하는 namespace 정의
- `services/` : 각 서비스별 `deployment.yaml`, `service.yaml`, `config.yaml` 포함된 디렉토리 존재
- `secrets/` : 사용하는 secrets 정의
- `db/` : `postgrsql`, `redis` 구축

# Secrets

## 현재 사용중인 secrets

- `database-secrets` : DATABASE_URL (Host, ID, Password, DB 포함)
- `redis-secrets` : REDIS_URL (Host 포함, 비밀번호 없는 상태)
- `nats-secrets` : NATS_URL (Host 포함)
- `internal-service-token-secrets` : INTERNAL_SERVICE_TOKEN (내부 통신용 토큰)

## 서비스 별 secrets 사용

### user-service

- `database-secrets`
- `redis-secrets`

### product-service

- `database-secrets`
- `redis-secrets`
- `database-secrets`

### order-service

- `database-secrets`
- `nats-secrets`
- `internal-service-token-secrets`

### payment-service

- `database-secrets`
- `internal-service-token-secrets`

### notification-service

- `nats-secrets`
