# 관찰성 스택 배포

명령어는 repository root 기준 실행

## namespace 생성

```bash
kubectl create namespace monitoring
kubectl create namespace micro-mart
```

또는 `helm install` 실행할 때 `--create-namespace` 추가

애플리케이션 서비스는 local overlay에서 `micro-mart-local` namespace를 사용한다.
OTel Collector, PostgreSQL, Redis, NATS 같은 공용 인프라는 `micro-mart` namespace에 둔다.

## K8s Node Label 설정

현재 Grafana 및 Tempo는 자원을 많이 소모하는 것을 확인해 (메모리 1Gi 이상) 따로 전용 노드에서 실행하기로 결정
따라서 node affinity를 적용하였으며 Node에 다음과 같은 Label 설정이 필요

```bash
kubectl label node <k8s-node-name> purpose=monitoring

# 라벨 확인
kubectl get node --show-labels
```

## Helm을 이용한 각 서비스 배포

### OTel Collector

otel-collector는 `micro-mart` namespace에 배포 -> DB, Redis 등 인프라 namespace

```bash
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
```

설치/업그레이드:

```bash
helm upgrade --install otel-collector open-telemetry/opentelemetry-collector -n micro-mart -f k8s/observability/otel-collector-values.yaml
```

### Prometheus

repo 설정

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
```

Slack 알림 webhook 준비:

```bash
mkdir -p k8s/observability/secrets
cp k8s/observability/secrets/slack-webhook-url.txt.example k8s/observability/secrets/slack-webhook-url.txt
```

`k8s/observability/secrets/slack-webhook-url.txt`에는 Slack Incoming Webhook URL 한 줄만 넣는다.
이 파일은 Git에 커밋하지 않는다.

설치/업그레이드:

```bash
helm upgrade --install prometheus prometheus-community/prometheus -n monitoring -f k8s/observability/prometheus-values.yaml --set-file alertmanager.config.global.slack_api_url=k8s/observability/secrets/slack-webhook-url.txt
```

렌더링 검증:

```bash
helm template prometheus prometheus-community/prometheus -n monitoring -f k8s/observability/prometheus-values.yaml --set-file alertmanager.config.global.slack_api_url=k8s/observability/secrets/slack-webhook-url.txt
```

Prometheus / Alertmanager 상태 확인:

```bash
kubectl get pods -n monitoring
kubectl port-forward -n monitoring svc/prometheus-server 9090:9090
kubectl port-forward -n monitoring svc/prometheus-alertmanager 9093:9093
```

Prometheus UI에서는 `Status > Rules`에서 `micromart.phase13.alerts` 그룹을 확인한다.
Alertmanager UI에서는 firing/resolved 알림이 Slack receiver로 라우팅되는지 확인한다.

수동 트리거 시나리오:

```bash
# 결제 지연 / 결제 실패율
k6 run k6/scenarios/payment_latency_chaos_order_flow.js
k6 run k6/scenarios/payment_failure_chaos_order_flow.js

# Rate Limit
k6 run k6/scenarios/auth_rate_limit_flow.js
```

notification 실패 알림은 `NOTIFICATION_FAILURE_RATE`를 높인 뒤 주문 완료 이벤트를 발생시켜 확인한다.
NATS 연결 끊김은 현재 Prometheus metric이 없으므로 notification-service `/health`의
`nats_connected=false`와 Loki warning 로그로 확인한다.

### Grafana

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
```

대시보드 자동 등록:

먼저 dashboard configmap 생성

```bash
kubectl create configmap micromart-observability-overview -n monitoring --from-file=micromart-observability-overview.json=k8s/observability/dashboard/micromart-observability-overview.json
```

설치/업그레이드:

admin 계정 비밀번호 설정에 대해서 `adminPassword="CHANGE_ME_PASSWORD"` 부분 수정

```bash
helm upgrade --install grafana grafana-community/grafana -n monitoring -f k8s/observability/grafana-values.yaml --set adminPassword="CHANGE_ME_PASSWORD"
```

### Loki

<https://grafana.com/docs/loki/latest/setup/install/helm/> 참조

repo는 Grafana와 같음

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
```

설치/업그레이드:

```bash
helm upgrade --install loki grafana-community/loki -n monitoring -f k8s/observability/loki-values.yaml
```

### Tempo

<https://github.com/grafana/tempo/tree/main/example/helm> 참조

repo는 Grafana와 같음

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
```

설치/업그레이드:

```bash
helm upgrade --install tempo grafana-community/tempo -n monitoring -f k8s/observability/tempo-values.yaml
```
