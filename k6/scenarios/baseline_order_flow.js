import { check, sleep } from "k6";
import http from "k6/http";

import { BASE_URL, BASELINE_OPTIONS, jsonParams } from "../config.js";
import { getAccessToken } from "../lib/auth.js";
import { pickProductId, resolveProductIds } from "../lib/products.js";

export const options = BASELINE_OPTIONS;

export function setup() {
  const accessToken = getAccessToken(BASE_URL);
  const productIds = resolveProductIds(BASE_URL);
  return { accessToken, productIds };
}

export default function (data) {
  const productId = pickProductId(data.productIds);
  const payload = JSON.stringify({
    items: [{ product_id: productId, quantity: 1 }],
  });

  const response = http.post(
    `${BASE_URL}/orders`,
    payload,
    jsonParams({ Authorization: `Bearer ${data.accessToken}` }, { endpoint: "order_create" }),
  );

  check(response, {
    "order create is 201": (res) => res.status === 201,
    "order completed": (res) => res.status === 201 && res.json("status") === "COMPLETED",
    "payment id is present": (res) => res.status === 201 && Number.isInteger(res.json("payment_id")),
  });

  sleep(Number(__ENV.K6_SLEEP_SECONDS || 1));
}
