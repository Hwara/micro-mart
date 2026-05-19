# 서비스 외부 노출 설정

로컬 Kubernetes 환경에서 `port-forward` 없이 `api-gateway`와 Grafana에 접근하기 위해
MetalLB와 Envoy Gateway를 사용한다.

- MetalLB: 로컬 클러스터에서 `LoadBalancer` 타입 Service에 고정 IP를 할당한다.
- Envoy Gateway: Gateway API 기반 HTTP 라우팅을 제공한다.
- Gateway API: 기존 Ingress 대신 사용할 표준 라우팅 API이다.

기존에 사용하던 커뮤니티 `ingress-nginx`는 지원이 종료되었으므로, 새 구성에서는
Gateway API와 Envoy Gateway를 사용한다.

---

## 1. MetalLB 배포

설치 방법은 MetalLB 공식 문서를 기준으로 한다.

참고: <https://metallb.io/installation/>

### kube-proxy strictARP 설정

`kube-proxy`가 IPVS 모드로 동작 중이라면 MetalLB Layer 2 모드를 위해 `strictARP`를
`true`로 설정해야 한다.

```bash
kubectl edit configmap -n kube-system kube-proxy
```

설정 예시:

```yaml
apiVersion: kubeproxy.config.k8s.io/v1alpha1
kind: KubeProxyConfiguration
mode: "ipvs"
ipvs:
  strictARP: true
```

### MetalLB 설치

```bash
helm repo add metallb https://metallb.github.io/metallb
helm repo update

helm install metallb metallb/metallb \
  -n metallb \
  --create-namespace
```

### IPAddressPool 설정

로컬 로드밸런서 용도로 사용할 IP 대역을 설정한다.

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: metallb-ip-pool
  namespace: metallb
spec:
  addresses:
    - 172.25.46.100-172.25.46.200
```

### L2Advertisement 설정

MetalLB가 위 IP 대역을 Layer 2 모드로 광고하도록 설정한다.

```yaml
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: metallb-l2-advertisement
  namespace: metallb
spec:
  ipAddressPools:
    - metallb-ip-pool
```

적용:

```bash
kubectl apply -f k8s/metallb/ip-address-pool.yaml
kubectl apply -f k8s/metallb/l2-advertisement.yaml
```

---

## 2. Envoy Gateway 배포

Envoy Gateway는 Gateway API 기반의 HTTP 라우팅을 제공한다.

참고: <https://gateway.envoyproxy.io/docs/tasks/traffic/http-routing/>

### 설치

```bash
helm install eg oci://docker.io/envoyproxy/gateway-helm \
  --version v1.8.0 \
  -n envoy-gateway-system \
  --create-namespace
```

### 배포 상태 확인

```bash
kubectl wait --timeout=5m \
  -n envoy-gateway-system \
  deployment/envoy-gateway \
  --for=condition=Available
```

### 선택: quickstart로 외부 노출 테스트

필요하다면 Envoy Gateway quickstart 예제로 LoadBalancer IP 할당과 HTTP 라우팅을 먼저
확인할 수 있다.

```bash
kubectl apply \
  -f https://github.com/envoyproxy/gateway/releases/download/v1.8.0/quickstart.yaml \
  -n default
```

```bash
export GATEWAY_HOST=$(kubectl get gateway/eg -o jsonpath='{.status.addresses[0].value}')

curl --verbose \
  --header "Host: www.example.com" \
  http://$GATEWAY_HOST/get
```

테스트가 끝난 뒤 quickstart 리소스가 실제 MicroMart 설정과 충돌하지 않도록 정리한다.
