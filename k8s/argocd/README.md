# ArgoCD

## 1. ArgoCD 배포

### 레포 등록

```bash
helm repo add argo https://argoproj.github.io/argo-helm
```

### 설치

```bash
helm upgrade --install my-argo-cd argo/argo-cd --version 9.5.15 -n argocd --create-namespace -f k8s/argocd/argocd-values.yaml
```

## 2. Gateway를 이용한 외부 노출

### TLS 시크릿 생성

cert-manager를 이용해 자동화할 수 있다고 하나 테스트를 위해 기존 생성되는 `argocd-secret`을 참조하여 tls 시크릿 생성

```bash
kubectl get secret argocd-secret -n argocd \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > /tmp/argocd-tls.crt

kubectl get secret argocd-secret -n argocd \
  -o jsonpath='{.data.tls\.key}' | base64 -d > /tmp/argocd-tls.key

kubectl create secret tls argocd-gateway-tls \
  -n argocd \
  --cert=/tmp/argocd-tls.crt \
  --key=/tmp/argocd-tls.key
```

### Gateway, HttpRoute 설정

```bash
kubectl apply -f k8s/argocd/argocd-gateway.yaml
kubectl apply -f k8s/argocd/argocd-http-route.yaml
```

## 3. ArgoCD Application 배포

### Application 생성

```bash
kubectl apply -f gitops/argocd-applications/micro-mart-local.yaml
```
