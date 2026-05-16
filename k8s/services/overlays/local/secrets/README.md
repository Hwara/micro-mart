# Secrets

## 현재 사용중인 secrets

- `user-database-secrets` : user-service가 사용하는 DATABASE_URL (Host, ID, Password, DB 포함)
- `product-database-secrets` : product-service가 사용하는 DATABASE_URL (Host, ID, Password, DB 포함)
- `order-database-secrets` : order-service가 사용하는 DATABASE_URL (Host, ID, Password, DB 포함)
- `payment-database-secrets` : payment-service가 사용하는 DATABASE_URL (Host, ID, Password, DB 포함)
- `redis-secrets` : REDIS_URL (Host 포함, 비밀번호 없는 상태)
- `nats-secrets` : NATS_URL (Host 포함)
- `internal-service-token-secrets` : INTERNAL_SERVICE_TOKEN (내부 통신용 토큰)
- `jwt-keys` : JWT public key, private key

## 서비스 별 secrets 사용

user-service

- `user-database-secrets`
- `redis-secrets`
- `jwt-keys`

product-service

- `product-database-secrets`
- `redis-secrets`
- `internal-service-token-secrets`

order-service

- `order-database-secrets`
- `nats-secrets`
- `internal-service-token-secrets`

payment-service

- `payment-database-secrets`
- `internal-service-token-secrets`

notification-service

- `nats-secrets`
