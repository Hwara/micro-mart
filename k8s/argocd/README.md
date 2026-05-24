# Argo CD

이 디렉터리는 로컬 Kubernetes 클러스터에 Argo CD를 Helm으로 설치하고 Gateway API로 외부 노출하기
위한 manifest를 담는다.

## 구성 파일

| 파일 | 역할 |
| --- | --- |
| `argocd-values.yaml` | Argo CD 서버를 HTTP backend로 노출하기 위한 Helm values |
| `argocd-gateway.yaml` | Envoy Gateway HTTPS listener와 TLS 종료 설정 |
| `argocd-http-route.yaml` | Argo CD server Service로 라우팅하는 HTTPRoute |

## 1. Argo CD 설치

repository root 기준:

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

helm upgrade --install my-argo-cd argo/argo-cd \
  --version 9.5.15 \
  -n argocd \
  --create-namespace \
  -f k8s/argocd/argocd-values.yaml
```

`argocd-values.yaml`은 `server.insecure: true`를 설정한다.
Gateway가 HTTPS를 종료하고 Argo CD server에는 HTTP port `80`으로 전달하기 위해서다.

## 2. Gateway TLS Secret 준비

Gateway API의 `certificateRefs`는 `kubernetes.io/tls` 타입 Secret을 요구한다.
Helm chart가 생성하는 `argocd-secret`은 `tls.crt`, `tls.key` 데이터를 포함하더라도 타입이
`Opaque`이므로 Gateway 인증서 Secret으로 직접 사용할 수 없다.

로컬 테스트에서는 `argocd-secret`의 인증서 데이터를 별도 TLS Secret으로 복사한다.

```bash
kubectl get secret argocd-secret -n argocd \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > /tmp/argocd-tls.crt

kubectl get secret argocd-secret -n argocd \
  -o jsonpath='{.data.tls\.key}' | base64 -d > /tmp/argocd-tls.key

kubectl create secret tls argocd-gateway-tls \
  -n argocd \
  --cert=/tmp/argocd-tls.crt \
  --key=/tmp/argocd-tls.key \
  --dry-run=client -o yaml | kubectl apply -f -
```

운영 환경에서는 cert-manager나 외부 인증서 관리 방식을 사용하는 것이 일반적이다.

## 3. Gateway / HTTPRoute 적용

```bash
kubectl apply -f k8s/argocd/argocd-gateway.yaml
kubectl apply -f k8s/argocd/argocd-http-route.yaml
```

상태 확인:

```bash
kubectl describe gateway argocd-gateway -n argocd
kubectl describe httproute argocd-http-route -n argocd
kubectl get svc -n envoy-gateway-system
```

MetalLB가 할당한 IP로 접속한다.

```text
https://<ARGOCD_GATEWAY_IP>
```

브라우저에서 자체 서명 인증서 경고가 뜰 수 있다.

## 4. 초기 로그인

초기 admin password 확인:

```bash
kubectl get secret argocd-initial-admin-secret -n argocd \
  -o jsonpath='{.data.password}' | base64 -d
```

## 5. MicroMart Application 적용

Application을 sync하기 전에 local Secret을 먼저 생성한다.

```bash
./scripts/apply_local_k8s_secrets.sh
kubectl apply -f gitops/argocd-applications/micro-mart-local.yaml
```

`micro-mart-local` Application은 `k8s/services/overlays/local`을 바라보며 automated sync를 사용하지
않는다. Argo CD UI 또는 CLI에서 diff를 확인한 뒤 manual sync한다.

## Feature Branch 테스트

`feat/#39` 같은 feature branch에서 먼저 GitOps 동작을 확인하려면 Application의 `targetRevision`을
일시적으로 해당 branch로 바꾼다.

```yaml
spec:
  source:
    targetRevision: feat/#39
```

주의할 점:

- branch에 local Secret 원문이 없어도 정상이다. Secret은 Git이 아니라
  `./scripts/apply_local_k8s_secrets.sh`로 클러스터에 미리 만든다.
- Secret이 없다는 sync 에러가 나면 Application 문제가 아니라 선행 Secret 적용이 빠진 것이다.
- 테스트가 끝나면 `targetRevision: main`으로 되돌린 뒤 main 기준 sync 흐름을 확인한다.
