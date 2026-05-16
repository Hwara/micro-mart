# 관찰성 스택 배포

## OTel Collector

```bash
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts

helm install otel-collector open-telemetry/opentelemetry-collector -n micro-mart -f otel-collector-values.yaml
```

## Prometheus

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
```

```bash
helm install prometheus prometheus-community/prometheus -n monitoring -f prometheus-values.yaml
```

```bash
helm upgrade prometheus prometheus-community/prometheus -n monitoring -f prometheus-values.yaml
```

## Grafana

```bash
helm repo add grafana https://grafana.github.io/helm-charts
```

admin 계정 비밀번호 설정에 대해서 `adminPassword="admin"` 부분 수정

```bash
helm install grafana grafana/grafana -n monitoring -f grafana-values.yaml --set adminPassword="admin"
```
