import { check, sleep } from "k6";
import http from "k6/http";

import { BASE_URL, jsonParams, PAYMENT_FAILURE_OPTIONS } from "../config.js";
import { getAccessToken } from "../lib/auth.js";
import { pickProductId, resolveProductIds } from "../lib/products.js";

http.setResponseCallback(http.expectedStatuses({ min: 200, max: 399 }, 402));

export const options = PAYMENT_FAILURE_OPTIONS;

/**
 * Parses a positive sleep duration in seconds and falls back to 1 second.
 *
 * @param {string | undefined} value Environment value to parse.
 * @returns {number} Positive finite sleep duration.
 */
function parseSleepSeconds(value) {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

/**
 * Prepares auth and product data for the payment failure chaos scenario.
 *
 * @returns {{accessToken: string, productIds: number[]}} Data consumed by VUs.
 */
export function setup() {
  const accessToken = getAccessToken(BASE_URL);
  const productIds = resolveProductIds(BASE_URL);
  return { accessToken, productIds };
}

/**
 * Creates one order while payment-service Chaos failure rate is enabled.
 *
 * @param {{accessToken: string, productIds: number[]}} data Setup output.
 * @returns {void}
 */
export default function (data) {
  const productId = pickProductId(data.productIds);
  const payload = JSON.stringify({
    items: [{ product_id: productId, quantity: 1 }],
  });

  const response = http.post(
    `${BASE_URL}/orders`,
    payload,
    jsonParams(
      { Authorization: `Bearer ${data.accessToken}` },
      { endpoint: "order_create_payment_failure" },
    ),
  );

  check(response, {
    "payment chaos order is completed or rejected": (res) => [201, 402].includes(res.status),
    "completed order has payment id": (res) =>
      res.status !== 201 || Number.isInteger(res.json("payment_id")),
    "rejected order reports payment rejected": (res) =>
      res.status !== 402 || res.json("detail.code") === "PAYMENT_REJECTED",
  });

  sleep(parseSleepSeconds(__ENV.K6_PAYMENT_FAILURE_SLEEP_SECONDS || __ENV.K6_SLEEP_SECONDS));
}
