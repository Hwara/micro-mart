# 관찰성 스택 배포

## OTel Collector

```bash
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
```

설치

```bash
helm install otel-collector open-telemetry/opentelemetry-collector -n micro-mart -f otel-collector-values.yaml
```

업그레이드

```bash
helm upgrade otel-collector open-telemetry/opentelemetry-collector -n micro-mart -f otel-collector-values.yaml
```

## Prometheus

repo 설정

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
```

설치

```bash
helm install prometheus prometheus-community/prometheus -n monitoring -f prometheus-values.yaml
```

업그레이드

```bash
helm upgrade prometheus prometheus-community/prometheus -n monitoring -f prometheus-values.yaml
```

## Grafana

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
```

admin 계정 비밀번호 설정에 대해서 `adminPassword="admin"` 부분 수정

```bash
helm install grafana grafana-community/grafana -n monitoring -f grafana-values.yaml --set adminPassword="admin"
```

```bash
helm upgrade grafana grafana-community/grafana -n monitoring -f grafana-values.yaml --set adminPassword="admin"
```

## Loki

<https://grafana.com/docs/loki/latest/setup/install/helm/> 참조

repo는 Grafana와 같음

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
```

설치

```bash
helm install loki grafana-community/loki -n monitoring -f loki-values.yaml
```

업그레이드

```bash
helm upgrade loki grafana-community/loki -n monitoring -f loki-values.yaml
```
