# Gateway API 설정 및 확인

로컬 Kubernetes 환경에서 `port-forward` 없이 `api-gateway`와 Grafana에 접근하기 위해
Envoy Gateway와 Gateway API를 사용한다.

- Envoy Gateway: Gateway API 기반 HTTP 라우팅을 제공한다.
- Gateway API: 기존 Ingress 대신 사용할 표준 라우팅 API이다.
- MetalLB: Envoy Gateway가 생성하는 `LoadBalancer` Service에 외부 IP를 할당한다.

기존에 사용하던 커뮤니티 `ingress-nginx`는 지원이 종료되었으므로, 새 구성에서는
Gateway API와 Envoy Gateway를 사용한다.

참고: <https://gateway-api.sigs.k8s.io/guides/getting-started/simple-gateway/>

---

## 1. Envoy Gateway 배포

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

---

## 2. Gateway API 설정

Gateway API는 `GatewayClass`, `Gateway`, `HTTPRoute` 조합으로 외부 트래픽을 서비스에
연결한다.

### api-gateway 노출

`Gateway`는 외부에 열 프로토콜, 포트, 라우트 허용 범위를 정의한다.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: micro-mart-gateway
  namespace: micro-mart-local
spec:
  gatewayClassName: eg
  listeners:
    - protocol: HTTP
      port: 80
      name: micro-mart-gateway
      allowedRoutes:
        namespaces:
          from: Same
```

적용:

```bash
kubectl apply -f k8s/gateway/micro-mart-gateway.yaml
```

`HTTPRoute`는 Gateway로 들어온 요청을 실제 Kubernetes Service로 전달한다.

현재 구성에서는 `micro-mart-gateway`로 들어온 모든 HTTP 요청을 `api-gateway` Service의
`8000` 포트로 전달한다.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: micro-mart-http-route
  namespace: micro-mart-local
spec:
  parentRefs:
    - name: micro-mart-gateway
  rules:
    - backendRefs:
        - name: api-gateway
          port: 8000
```

적용:

```bash
kubectl apply -f k8s/gateway/micro-mart-httproute.yaml
```

### Grafana 노출

Grafana는 `monitoring` namespace의 `grafana` Service로 라우팅한다.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: grafana-gateway
  namespace: monitoring
spec:
  gatewayClassName: eg
  listeners:
    - protocol: HTTP
      port: 80
      name: grafana-gateway
      allowedRoutes:
        namespaces:
          from: Same
```

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: grafana-http-route
  namespace: monitoring
spec:
  parentRefs:
    - name: grafana-gateway
  rules:
    - backendRefs:
        - name: grafana
          port: 80
```

적용:

```bash
kubectl apply -f k8s/gateway/grafana-gateway.yaml
kubectl apply -f k8s/gateway/grafana-httproute.yaml
```

---

## 3. 접근 확인

Gateway에 할당된 외부 IP를 확인한다. `micro-mart-gateway`와 `grafana-gateway`는 별도
Gateway이므로 각각 다른 외부 IP를 받을 수 있다.

```bash
kubectl get gateway -A
```

또는 Envoy Gateway가 생성한 LoadBalancer Service를 확인한다.

```bash
kubectl get svc -n envoy-gateway-system
```

할당된 IP가 `172.25.46.100-172.25.46.200` 범위 안에 있으면 MetalLB 설정이 정상적으로
동작한 것이다.

예시:

```bash
curl http://<MICRO_MART_GATEWAY_IP>/health
```

이 구성을 적용하면 기존처럼 매번 `kubectl port-forward`로 `api-gateway`나 Grafana에
접근하지 않아도 된다. `api-gateway`와 Grafana를 각각 Gateway API 라우트로 등록하면
MetalLB가 할당한 고정 IP를 통해 로컬 환경에서 안정적으로 접근할 수 있다.
