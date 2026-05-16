# 관찰성 스택 배포

## OTel Collector

```bash
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts

# contrib 버전 사용: loki exporter, prometheusremotewrite exporter 포함
helm install otel-collector open-telemetry/opentelemetry-collector \
   -n micro-mart \
   --set image.repository="otel/opentelemetry-collector-contrib" \
   --set image.tag="0.150.1" \
   --set mode=<daemonset|deployment|statefulset> \
   -f values.yaml
```

예제

```bash
helm install otel-collector open-telemetry/opentelemetry-collector -n micro-mart --set image.repository="otel/opentelemetry-collector-contrib" --set image.tag="0.150.1" --set mode=deployment -f values.yaml
```
