#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="micro-mart-local"
SECRET_DIR="k8s/services/overlays/local/secrets"

required_files=(
  "${SECRET_DIR}/user-database-secret.env"
  "${SECRET_DIR}/product-database-secret.env"
  "${SECRET_DIR}/order-database-secret.env"
  "${SECRET_DIR}/payment-database-secret.env"
  "${SECRET_DIR}/redis-secrets.env"
  "${SECRET_DIR}/nats-secrets.env"
  "${SECRET_DIR}/internal-service-token-secret.env"
  "${SECRET_DIR}/keys/public.pem"
  "${SECRET_DIR}/keys/private.pem"
)

for file in "${required_files[@]}"; do
  if [ ! -f "${file}" ]; then
    echo "Missing required secret input file: ${file}" >&2
    exit 1
  fi
done

kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic user-database-secrets \
  -n "${NAMESPACE}" \
  --from-env-file="${SECRET_DIR}/user-database-secret.env" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic product-database-secrets \
  -n "${NAMESPACE}" \
  --from-env-file="${SECRET_DIR}/product-database-secret.env" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic order-database-secrets \
  -n "${NAMESPACE}" \
  --from-env-file="${SECRET_DIR}/order-database-secret.env" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic payment-database-secrets \
  -n "${NAMESPACE}" \
  --from-env-file="${SECRET_DIR}/payment-database-secret.env" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic redis-secrets \
  -n "${NAMESPACE}" \
  --from-env-file="${SECRET_DIR}/redis-secrets.env" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic nats-secrets \
  -n "${NAMESPACE}" \
  --from-env-file="${SECRET_DIR}/nats-secrets.env" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic internal-service-token-secrets \
  -n "${NAMESPACE}" \
  --from-env-file="${SECRET_DIR}/internal-service-token-secret.env" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic jwt-keys \
  -n "${NAMESPACE}" \
  --from-file=public.pem="${SECRET_DIR}/keys/public.pem" \
  --from-file=private.pem="${SECRET_DIR}/keys/private.pem" \
  --dry-run=client -o yaml | kubectl apply -f -
