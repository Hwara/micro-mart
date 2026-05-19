# MetalLB 설정

MetalLB는 로컬 Kubernetes 클러스터에서 `LoadBalancer` 타입 Service에 외부 IP를
할당하기 위해 사용한다. MicroMart 로컬 환경에서는 Envoy Gateway가 생성하는
LoadBalancer Service에 IP를 제공한다.

참고: <https://metallb.io/installation/>

---

## 배포

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

---

## Layer 2 IP pool 설정

MicroMart 로컬 클러스터는 간단한 로컬 로드밸런서 용도이므로 MetalLB Layer 2 모드를
사용한다.

### IPAddressPool 설정

로드밸런서에 할당할 IP 대역을 설정한다.

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

할당된 IP가 `172.25.46.100-172.25.46.200` 범위 안에 있으면 MetalLB 설정이 정상적으로
동작한 것이다.
