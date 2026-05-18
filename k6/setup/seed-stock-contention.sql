-- Active: 1779007577703@@127.0.0.1@5432@productdb
-- Kubernetes local stock contention load test product.
-- Run against productdb only. Existing k6-contention-single rows are replaced
-- so repeated contention runs start from a predictable high-stock product.

BEGIN;

DELETE FROM products WHERE name = 'k6-contention-single';

INSERT INTO
    products (
        name,
        description,
        price,
        stock,
        version,
        is_active
    )
VALUES (
        'k6-contention-single',
        'k6 stock contention load test product',
        15000,
        100000,
        1,
        true
    );

COMMIT;
