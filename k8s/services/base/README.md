# 각 서비스별 yaml 생성 예제

## configmaps

각 서비스 환경변수 파일이 있는 곳으로 이동

```bash
kubectl create configmap xxxx-service-config -n micro-mart --from-env-file=.env --dry-run=client -o yaml > xxxx-service-config.yaml
```
