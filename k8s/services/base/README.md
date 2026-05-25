# Services Base

`k8s/services/base/`는 환경과 무관한 애플리케이션 서비스 기본 manifest를 담는다.
각 서비스 디렉터리는 `Deployment`, `Service`, `kustomization.yaml`을 가진다.

## 포함 서비스

- `api-gateway`
- `user-service`
- `product-service`
- `order-service`
- `payment-service`
- `notification-service`

## Base 역할

- 컨테이너 포트, probe, security context, resource request/limit 같은 서비스 기본 실행 조건을 정의한다.
- 환경별 이미지 registry, tag, namespace, ConfigMap 값은 overlay에서 덮어쓴다.
- 민감값은 manifest에 직접 쓰지 않고 고정 이름의 Kubernetes Secret을 참조한다.

## Secret 참조

Base Deployment는 아래 Secret이 이미 존재한다고 가정한다.

| Secret | 사용 서비스 | 역할 |
| --- | --- | --- |
| `user-database-secrets` | `user-service` | user DB 연결 문자열 |
| `product-database-secrets` | `product-service` | product DB 연결 문자열 |
| `order-database-secrets` | `order-service` | order DB 연결 문자열 |
| `payment-database-secrets` | `payment-service` | payment DB 연결 문자열 |
| `redis-secrets` | `user-service`, `product-service` | Redis 연결 문자열 |
| `nats-secrets` | `order-service`, `notification-service` | NATS 연결 문자열 |
| `internal-service-token-secrets` | `product-service`, `order-service`, `payment-service` | 내부 서비스 호출 토큰 |
| `jwt-keys` | `user-service` | RS256 JWT public/private key 파일 |

로컬 환경에서는 repository root에서 아래 스크립트를 먼저 실행해 Secret을 생성한다.

```bash
bash scripts/apply_local_k8s_secrets.sh
```

## ConfigMap 참조

각 Deployment는 `<service-name>-config` ConfigMap을 `envFrom.configMapRef`로 참조한다.
로컬 overlay는 `k8s/services/overlays/local/config/*.env` 파일에서 이 ConfigMap을 생성한다.
