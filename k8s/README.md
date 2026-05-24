# Kubernetes 구성

이 디렉터리는 MicroMart를 로컬 Kubernetes 환경에 배포하기 위한 manifest와 설치 절차를 담는다.

## 디렉터리 구조

```text
k8s/
├── README.md                  # 전체 배포 흐름의 진입점
├── argocd/                    # Argo CD Helm values, Gateway, HTTPRoute
├── db/                        # PostgreSQL, Redis 로컬 인프라 구성
├── gateway/                   # api-gateway, Grafana Gateway API 설정
├── metallb/                   # MetalLB IP pool 설정
├── namespaces/                # 공통 namespace 매니페스트
├── nats/                      # NATS 로컬 인프라 구성
├── observability/             # OTel, Prometheus, Grafana, Loki, Tempo 구성
└── services/
    ├── base/                  # 서비스 Deployment/Service 기본 정의
    └── overlays/
        └── local/             # 로컬 Kubernetes overlay
```

## 로컬 서비스 배포 순서

### 1. 공통 인프라 배포

repository root 기준:

```bash
kubectl apply -f k8s/namespaces/namespace.yaml
```

그 다음 아래 문서를 따라 인프라를 준비한다.

1. PostgreSQL, Redis: [`k8s/db/README.md`](db/)
2. NATS: `kubectl apply -f k8s/nats/nats.yaml`
3. 관찰성 스택: [`k8s/observability/README.md`](observability/)

### 2. Local Secret 준비

local overlay는 Git에 Secret 원문을 올리지 않는다.
Argo CD도 Git에 없는 로컬 `.env` 파일을 읽을 수 없으므로, Secret은 클러스터에 고정 이름으로 먼저
생성한다.

`.example` 파일을 복사해 실제 값을 채운다.

```bash
cp k8s/services/overlays/local/secrets/user-database-secret.env.example k8s/services/overlays/local/secrets/user-database-secret.env
cp k8s/services/overlays/local/secrets/product-database-secret.env.example k8s/services/overlays/local/secrets/product-database-secret.env
cp k8s/services/overlays/local/secrets/order-database-secret.env.example k8s/services/overlays/local/secrets/order-database-secret.env
cp k8s/services/overlays/local/secrets/payment-database-secret.env.example k8s/services/overlays/local/secrets/payment-database-secret.env
cp k8s/services/overlays/local/secrets/redis-secrets.env.example k8s/services/overlays/local/secrets/redis-secrets.env
cp k8s/services/overlays/local/secrets/nats-secrets.env.example k8s/services/overlays/local/secrets/nats-secrets.env
cp k8s/services/overlays/local/secrets/internal-service-token-secret.env.example k8s/services/overlays/local/secrets/internal-service-token-secret.env
```

JWT key를 ignored 경로로 복사한다.

```bash
mkdir -p k8s/services/overlays/local/secrets/keys
cp keys/public.pem k8s/services/overlays/local/secrets/keys/public.pem
cp keys/private.pem k8s/services/overlays/local/secrets/keys/private.pem
```

Secret을 클러스터에 적용한다.

```bash
./scripts/apply_local_k8s_secrets.sh
```

자세한 Secret 목록은 [`k8s/services/overlays/local/secrets/README.md`](services/overlays/local/secrets/)를
참고한다.

### 3. 서비스 이미지 빌드 및 registry push

수동 로컬 배포는 `docker/services.yaml`을 사용한다.
기본 registry와 tag는 `172.25.46.10:32000`, `local`이다.

```bash
REGISTRY=172.25.46.10:32000
TAG=local

docker compose -f docker/services.yaml build
docker compose -f docker/services.yaml push
```

이미지 주소 또는 태그를 변경하면 `k8s/services/overlays/local/kustomization.yaml`의 `images` 설정도
같이 변경한다.

### 4. Kustomize 수동 적용

GitOps를 거치지 않고 직접 적용할 때 사용한다.

```bash
kubectl apply -k k8s/services/overlays/local
```

렌더링 결과 확인:

```bash
kubectl kustomize k8s/services/overlays/local
```

## GitOps CD 흐름

Phase 15 이후 `main`에 merge되면 GitHub Actions `CD Local GitOps` workflow가 WSL2 Ubuntu
self-hosted runner에서 `docker/services.yaml`로 6개 서비스 이미지를 빌드하고
`172.25.46.10:32000` registry에 push한다.

이미지 태그는 짧은 commit SHA이며, workflow가
`k8s/services/overlays/local/kustomization.yaml`의 `images` 값을 같은 태그로 갱신해 commit한다.

```text
172.25.46.10:32000/<service-name>:<commit-sha>
```

Argo CD Application은 `gitops/argocd-applications/micro-mart-local.yaml`에 정의되어 있다.
로컬 Chaos 테스트와 환경변수 실험의 배포 타이밍을 통제하기 위해 automated sync는 사용하지 않는다.

```bash
kubectl apply -f gitops/argocd-applications/micro-mart-local.yaml
```

Argo CD에서 diff를 확인한 뒤 manual sync를 실행하면 Git에 기록된 local overlay 상태가
`micro-mart-local` namespace에 반영된다.

`feat/#39` 같은 branch에서 먼저 테스트할 때는 Argo CD Application의 `targetRevision`만 해당 branch로
일시 변경한다. 단, Secret은 GitOps 대상이 아니므로 branch 변경 전에도
`./scripts/apply_local_k8s_secrets.sh`로 클러스터에 먼저 존재해야 한다.

## 외부 노출

로컬 Kubernetes에서 `port-forward` 없이 접근하려면 MetalLB와 Envoy Gateway를 사용한다.

1. MetalLB 설치 및 IP pool 설정: [`k8s/metallb/README.md`](metallb/)
2. Envoy Gateway 설치 및 api-gateway/Grafana 라우팅: [`k8s/gateway/README.md`](gateway/)
3. Argo CD HTTPS 라우팅: [`k8s/argocd/README.md`](argocd/)

## Base와 Overlay 역할

- `services/base/`: 서비스별 Deployment와 Service 정의
- `services/overlays/local/`: 로컬 namespace, ConfigMap, 이미지 tag overlay
- `services/overlays/local/config/`: Git에 커밋 가능한 로컬 기본 설정 값
- `services/overlays/local/secrets/`: Git에 커밋하지 않는 Secret 입력 파일과 example
- `scripts/apply_local_k8s_secrets.sh`: local overlay가 참조하는 고정 이름 Secret 생성
