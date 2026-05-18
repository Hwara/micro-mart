# k6 Baseline 테스트 데이터

`seed-products.sql`은 `productdb`에 `k6-baseline-001`부터 `k6-baseline-100`까지 100개의 활성 상품을 생성합니다.

이 스크립트는 로컬 학습용 데이터베이스에만 실행하세요.

```bash
cat k6/setup/seed-products.sql | kubectl -n micro-mart exec -i statefulset/postgresql -- psql -U postgres -d productdb
```

PostgreSQL workload의 pod 이름이나 사용자명이 다르다면 `kubectl exec` 대상과 `psql -U` 값을 환경에 맞게 조정하세요. 이 스크립트는 새 high-stock 상품 풀을 넣기 전에 기존 `k6-baseline-*` 행을 삭제합니다.

k6 스크립트는 `GET /products`로 이 상품들을 찾아 사용합니다. 조회를 건너뛰고 명시적인 상품 ID를 쓰고 싶다면 아래처럼 `PRODUCT_IDS`를 전달하면 됩니다.

```bash
k6 run -e PRODUCT_IDS=1,2,3 -e BASE_URL=http://localhost:8080 k6/scenarios/smoke.js
```
