import { check } from "k6";
import http from "k6/http";

import { BASE_URL, jsonParams, SMOKE_OPTIONS } from "../config.js";
import { getAccessToken } from "../lib/auth.js";
import { pickProductId, resolveProductIds } from "../lib/products.js";

export const options = SMOKE_OPTIONS;

export function setup() {
  const accessToken = getAccessToken(BASE_URL);
  const productIds = resolveProductIds(BASE_URL);
  return { accessToken, productIds };
}

export default function (data) {
  const health = http.get(`${BASE_URL}/health`, jsonParams({}, { endpoint: "gateway_health" }));
  check(health, {
    "gateway health is 200": (response) => response.status === 200,
  });

  const productId = pickProductId(data.productIds);
  const product = http.get(
    `${BASE_URL}/products/${productId}`,
    jsonParams({}, { endpoint: "product_detail" }),
  );
  check(product, {
    "product detail is 200": (response) => response.status === 200,
  });

  const orderPayload = JSON.stringify({
    items: [{ product_id: productId, quantity: 1 }],
  });
  const order = http.post(
    `${BASE_URL}/orders`,
    orderPayload,
    jsonParams({ Authorization: `Bearer ${data.accessToken}` }, { endpoint: "order_create" }),
  );
  check(order, {
    "order create is 201": (response) => response.status === 201,
    "order completed": (response) => response.status === 201 && response.json("status") === "COMPLETED",
  });
}
