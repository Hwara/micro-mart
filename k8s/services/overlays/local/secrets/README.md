# Local Secrets

이 디렉터리는 로컬 Kubernetes 실행에 필요한 Secret 입력 파일의 위치다.
실제 Secret 값은 Git에 커밋하지 않고, `.env.example` 파일만 기준으로 남긴다.

## 적용 방식

Phase 15 기준 local overlay는 `secretGenerator`를 사용하지 않는다.
Argo CD가 Git에 없는 로컬 secret 파일을 읽을 수 없기 때문에, Secret은 클러스터에 고정 이름으로
미리 생성한다.

repository root 기준:

```bash
bash scripts/apply_local_k8s_secrets.sh
```

이 스크립트는 `micro-mart-local` namespace를 만든 뒤 아래 Secret을 `kubectl apply` 방식으로
생성 또는 갱신한다.
필수 입력 파일이 하나라도 없으면 어떤 Secret도 변경하지 않고 실패한다.

## Secret 목록

| Secret | 입력 파일 | 역할 |
| --- | --- | --- |
| `user-database-secrets` | `user-database-secret.env` | `user-service` DB 연결 |
| `product-database-secrets` | `product-database-secret.env` | `product-service` DB 연결 |
| `order-database-secrets` | `order-database-secret.env` | `order-service` DB 연결 |
| `payment-database-secrets` | `payment-database-secret.env` | `payment-service` DB 연결 |
| `redis-secrets` | `redis-secrets.env` | Redis 연결 |
| `nats-secrets` | `nats-secrets.env` | NATS 연결 |
| `internal-service-token-secrets` | `internal-service-token-secret.env` | 내부 서비스 호출 토큰 |
| `jwt-keys` | `keys/public.pem`, `keys/private.pem` | RS256 JWT key |

## 준비 절차

`.example` 파일을 복사한 뒤 로컬 환경 값으로 수정한다.

```bash
cp k8s/services/overlays/local/secrets/user-database-secret.env.example k8s/services/overlays/local/secrets/user-database-secret.env
cp k8s/services/overlays/local/secrets/product-database-secret.env.example k8s/services/overlays/local/secrets/product-database-secret.env
cp k8s/services/overlays/local/secrets/order-database-secret.env.example k8s/services/overlays/local/secrets/order-database-secret.env
cp k8s/services/overlays/local/secrets/payment-database-secret.env.example k8s/services/overlays/local/secrets/payment-database-secret.env
cp k8s/services/overlays/local/secrets/redis-secrets.env.example k8s/services/overlays/local/secrets/redis-secrets.env
cp k8s/services/overlays/local/secrets/nats-secrets.env.example k8s/services/overlays/local/secrets/nats-secrets.env
cp k8s/services/overlays/local/secrets/internal-service-token-secret.env.example k8s/services/overlays/local/secrets/internal-service-token-secret.env
```

JWT key는 repository root의 `keys/` 파일을 ignored 경로로 복사한다.

```bash
mkdir -p k8s/services/overlays/local/secrets/keys
cp keys/public.pem k8s/services/overlays/local/secrets/keys/public.pem
cp keys/private.pem k8s/services/overlays/local/secrets/keys/private.pem
```

## 주의사항

- Secret 파일과 JWT key 파일은 Git에 커밋하지 않는다.
- Secret 변경 후 이미 떠 있는 Pod에 환경변수 변경을 반영하려면 Deployment rollout restart가 필요하다.
- Argo CD manual sync는 Secret 원문을 생성하지 않는다. Secret을 먼저 적용한 뒤 Application을 sync한다.
