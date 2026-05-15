# DB Secret 생성 예제

- DB를 필요로 하는 서비스 별로 4개의 Secrets을 생성해야 함.
- userdb, productdb, orderdb, paymentdb 총 4개

```bash
kubectl create secret generic database-secrets -n micro-mart --from-literal=DATABASE_URL=postgresql+asyncpg://micromart:micromart@postgresql:5432/userdb --dry-run=client -o yaml > database-secrets.yaml

kubectl apply -f user-database-secrets.yaml
```

# Redis Secret 생성 예제

```bash
kubectl create secret generic redis-secrets -n micro-mart --from-literal=REDIS_URL=redis://redis:6379/0 --dry-run=client -o yaml > redis-secrets.yaml

kubectl apply -f redis-secrets.yaml
```

# JWT Key Secret 생성 예제

- /keys 디렉터리로 이동

```bash
kubectl create secret generic jwt-keys -n micro-mart --from-file=private.pem --from-file=public.pem --dry-run=client -o yaml > jwt-keys-secrets.yaml
```

# internal token Secret 생성 예제

```bash
kubectl create secret generic internal-service-token-secrets -n micro-mart --from-literal=INTERNAL_SERVICE_TOKEN=change-me-in-production --dry-run=client -o yaml > internal-service-token-secrets.yaml

kubectl apply -f internal-token-secrets.yaml
```

# nats Screts 생성 예제

```bash
kubectl create secret generic nats-secrets -n micro-mart --from-literal=NATS_URL=nats://nats:4222 --dry-run=client -o yaml > nats-secrets.yaml

kubectl apply -f nats-secrets.yaml
```
