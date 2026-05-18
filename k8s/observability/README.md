# 관찰성 스택 배포

명령어는 repository root 기준 실행

## namespace 생성

```bash
kubectl create namespace monitoring
kubectl create namespace micro-mart
```

또는 `helm install` 실행할 때 `--create-namespace` 추가

## OTel Collector

otel-collector는 `micro-mart` namespace에 배포 -> DB, Redis 등 인프라 namespace

```bash
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
```

설치/업그레이드

```bash
helm upgrade otel-collector open-telemetry/opentelemetry-collector -n micro-mart -f k8s/observability/otel-collector-values.yaml
```

## Prometheus

repo 설정

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
```

설치/업그레이드

```bash
helm upgrade --install prometheus prometheus-community/prometheus -n monitoring -f k8s/observability/prometheus-values.yaml
```

## Grafana

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
```

먼저 dashboard configmap 생성

```bash
kubectl create configmap micromart-observability-overview -n monitoring --from-file=micromart-observability-overview.json=k8s/observability/dashboard/micromart-observability-overview.json
```

admin 계정 비밀번호 설정에 대해서 `adminPassword="CHANGE_ME_PASSWORD"` 부분 수정

```bash
helm upgrade --install grafana grafana-community/grafana -n monitoring -f k8s/observability/grafana-values.yaml --set adminPassword="CHANGE_ME_PASSWORD"
```

## Loki

<https://grafana.com/docs/loki/latest/setup/install/helm/> 참조

repo는 Grafana와 같음

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
```

설치/업그레이드

```bash
helm upgrade --install loki grafana-community/loki -n monitoring -f k8s/observability/loki-values.yaml
```

## Tempo

<https://github.com/grafana/tempo/tree/main/example/helm> 참조

repo는 Grafana와 같음

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
```

설치/업그레이드

```bash
helm upgrade --install tempo grafana-community/tempo -n monitoring -f k8s/observability/tempo-values.yaml
```
