-- Kubernetes local baseline load test products.
-- Run against productdb only. Existing k6-baseline-* rows are replaced so repeated
-- baseline runs start from a predictable high-stock product pool.

BEGIN;

DELETE FROM products
WHERE name LIKE 'k6-baseline-%';

INSERT INTO products (name, description, price, stock, version, is_active)
SELECT
  'k6-baseline-' || LPAD(i::text, 3, '0') AS name,
  'k6 baseline load test product' AS description,
  10000 + (i * 100) AS price,
  100000 AS stock,
  1 AS version,
  true AS is_active
FROM generate_series(1, 100) AS i;

COMMIT;
