# Kubernetes 구성

이 디렉터리는 micro-mart를 Kubernetes 로컬 환경에 배포하기 위한 manifest를 담고 있습니다.

## 디렉터리 구조

```text
k8s/
├── db/                    # PostgreSQL, Redis 등 로컬 인프라 구성
├── namespaces/            # 공통 namespace 매니페스트
├── registry/              # 로컬 이미지 registry 구성
└── services/
    ├── base/              # 환경과 무관한 서비스 Deployment/Service 기본 정의
    └── overlays/
        └── local/         # 로컬 Kubernetes 환경용 ConfigMap/Secret/namespace 조합
```

## 로컬 서비스 배포

### JWT key Secret 준비

`user-service`는 RS256 JWT 서명을 위해 private/public key 파일이 필요합니다.

로컬 환경에서는 repository root의 `keys/` 파일을 overlay의 ignored secret 경로로 복사합니다.

repository root 기준:

```bash
mkdir -p k8s/services/overlays/local/secrets/keys
cp keys/public.pem k8s/services/overlays/local/secrets/keys/public.pem
cp keys/private.pem k8s/services/overlays/local/secrets/keys/private.pem
```

### Kustomize 실행

repository root 기준:

```bash
kubectl apply -k k8s/services/overlays/local
```

렌더링 결과 확인:

```bash
kubectl kustomize k8s/services/overlays/local
```

## base와 overlay 역할

- `services/base/` : 서비스별 Deployment와 Service 정의
- `services/overlays/local/` : 로컬 실행용 namespace, configmap, secret generator 정의
- `services/overlays/local/config/` : Git에 커밋 가능한 로컬 기본 설정 값
- `services/overlays/local/secrets/` : 실제 secret env 파일과 JWT 파일을 두되 실제 값은 Git에 커밋하지 않고 example 만 남김
