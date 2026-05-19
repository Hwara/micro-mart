
# Gateway API 설정 및 확인

## Gateway API 설정

Gateway API는 `GatewayClass`, `Gateway`, `HTTPRoute` 조합으로 외부 트래픽을 서비스에
연결한다.

참고: <https://gateway-api.sigs.k8s.io/guides/getting-started/simple-gateway/>

### Gateway 설정

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

### HTTPRoute 설정

`HTTPRoute`는 Gateway로 들어온 요청을 실제 Kubernetes Service로 전달한다.

현재 구성에서는 모든 HTTP 요청을 `api-gateway` Service의 `8000` 포트로 전달한다.

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

---

## 접근 확인

Gateway에 할당된 외부 IP를 확인한다.

```bash
kubectl get gateway -n micro-mart-local
```

또는 Envoy Gateway가 생성한 LoadBalancer Service를 확인한다.

```bash
kubectl get svc -n envoy-gateway-system
```

할당된 IP가 `172.25.46.100-172.25.46.200` 범위 안에 있으면 MetalLB 설정이 정상적으로
동작한 것이다.

예시:

```bash
curl http://<GATEWAY_IP>/health
```

이 구성을 적용하면 기존처럼 매번 `kubectl port-forward`로 `api-gateway`나 Grafana에
접근하지 않아도 된다. `api-gateway`와 Grafana를 각각 Gateway API 라우트로 등록하면
MetalLB가 할당한 고정 IP를 통해 로컬 환경에서 안정적으로 접근할 수 있다.
