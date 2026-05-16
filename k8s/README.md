# Kubernetes 구성

이 디렉터리는 micro-mart를 Kubernetes 로컬 환경에 배포하기 위한 manifest를 담고 있습니다.

## 디렉터리 구조

```text
k8s/
├── db/                    # PostgreSQL, Redis 등 로컬 인프라 구성
├── namespaces/            # 공통 namespace 매니페스트
├── observability/         # 관찰성 스택 환경 구성
└── services/
    ├── base/              # 환경과 무관한 서비스 Deployment/Service 기본 정의
    └── overlays/
        └── local/         # 로컬 Kubernetes 환경용 ConfigMap/Secret/namespace 조합
```

## 로컬 서비스 배포

### DB, Redis 등 선행 인프라 배포

1. 네임스페이스 생성 - `kubectl apply -f k8s/namespaces/namespace.yaml`
2. `k8s/db/README.md`에 따라 DB 및 Redis 배포
3. NATS 배포 - `kubectl apply -f k8s/nats/nats.yaml`

### JWT key Secret 준비

`user-service`는 RS256 JWT 서명을 위해 private/public key 파일이 필요합니다.

로컬 환경에서는 repository root의 `keys/` 파일을 overlay의 ignored secret 경로로 복사합니다.

repository root 기준:

```bash
mkdir -p k8s/services/overlays/local/secrets/keys
cp keys/public.pem k8s/services/overlays/local/secrets/keys/public.pem
cp keys/private.pem k8s/services/overlays/local/secrets/keys/private.pem
```

### 각 서비스별 필요 Secret 준비

각 서비스에 대해 필요한 Secret에 대한 example이 `secrets/`에 포함되어 있습니다.

`.example`을 제거하여 복사 후 현재 환경에 맞게 설정을 변경하세요.

repository root 기준:

```bash
cp k8s/services/overlays/local/secrets/user-database-secret.env.example k8s/services/overlays/local/secrets/user-database-secret.env
cp k8s/services/overlays/local/secrets/product-database-secret.env.example k8s/services/overlays/local/secrets/product-database-secret.env
cp k8s/services/overlays/local/secrets/order-database-secret.env.example k8s/services/overlays/local/secrets/order-database-secret.env
cp k8s/services/overlays/local/secrets/payment-database-secret.env.example k8s/services/overlays/local/secrets/payment-database-secret.env
cp k8s/services/overlays/local/secrets/redis-secrets.env.example k8s/services/overlays/local/secrets/redis-secrets.env
cp k8s/services/overlays/local/secrets/nats-secrets.env.example k8s/services/overlays/local/secrets/nats-secrets.env
cp k8s/services/overlays/local/secrets/internal-service-token-secret.env.example k8s/services/overlays/local/secrets/internal-service-token-secret.env
```

### micro-mart 서비스 이미지 빌드 및 registry push

Kubernetes가 사용할 micro-mart 서비스 이미지를 로컬에서 빌드한 뒤, 로컬 registry에 push합니다.

현재 local overlay는 아래 registry 주소와 `local` 태그를 사용합니다.

```text
172.25.46.10:32000/<service-name>:local
```

repository root 기준:

```bash
REGISTRY=172.25.46.10:32000
TAG=local

docker build -f services/user-service/Dockerfile -t ${REGISTRY}/user-service:${TAG} .
docker build -f services/product-service/Dockerfile -t ${REGISTRY}/product-service:${TAG} .
docker build -f services/order-service/Dockerfile -t ${REGISTRY}/order-service:${TAG} .
docker build -f services/payment-service/Dockerfile -t ${REGISTRY}/payment-service:${TAG} .
docker build -f services/notification-service/Dockerfile -t ${REGISTRY}/notification-service:${TAG} .
docker build -f services/api-gateway/Dockerfile -t ${REGISTRY}/api-gateway:${TAG} .

docker push ${REGISTRY}/user-service:${TAG}
docker push ${REGISTRY}/product-service:${TAG}
docker push ${REGISTRY}/order-service:${TAG}
docker push ${REGISTRY}/payment-service:${TAG}
docker push ${REGISTRY}/notification-service:${TAG}
docker push ${REGISTRY}/api-gateway:${TAG}
```

이미지 주소 또는 태그를 변경한 경우 k8s/services/overlays/local/kustomization.yaml의 images 설정도 같은 값으로 변경해야 합니다.

### Kustomize 실행

repository root 기준:

```bash
kubectl apply -k k8s/services/overlays/local
```

렌더링 결과 확인:

```bash
kubectl kustomize k8s/services/overlays/local
```

### 이후 필요에 따라 관찰성 스택 환경 구축

Kubernetes 관찰성 스택 환경 구축은 [`k8s/observability/README.md`](observability/)를 참고하세요.

## base와 overlay 역할

- `services/base/` : 서비스별 Deployment와 Service 정의
- `services/overlays/local/` : 로컬 실행용 namespace, configmap, secret generator 정의
- `services/overlays/local/config/` : Git에 커밋 가능한 로컬 기본 설정 값
- `services/overlays/local/secrets/` : 실제 secret env 파일과 JWT 파일을 두되 실제 값은 Git에 커밋하지 않고 example 만 남김
