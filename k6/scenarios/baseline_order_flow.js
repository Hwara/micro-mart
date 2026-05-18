import { check, sleep } from "k6";
import http from "k6/http";

import { BASE_URL, BASELINE_OPTIONS, jsonParams } from "../config.js";
import { getAccessToken } from "../lib/auth.js";
import { pickProductId, resolveProductIds } from "../lib/products.js";

export const options = BASELINE_OPTIONS;

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
 * Prepares shared VU data by resolving authentication and product candidates.
 *
 * @returns {{accessToken: string, productIds: number[]}} Data consumed by the
 * default VU function. BASE_URL must point at a reachable api-gateway.
 */
export function setup() {
  const accessToken = getAccessToken(BASE_URL);
  const productIds = resolveProductIds(BASE_URL);
  return { accessToken, productIds };
}

/**
 * Creates one order for a random baseline product using setup data.
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
    jsonParams({ Authorization: `Bearer ${data.accessToken}` }, { endpoint: "order_create" }),
  );

  check(response, {
    "order create is 201": (res) => res.status === 201,
    "order completed": (res) => res.status === 201 && res.json("status") === "COMPLETED",
    "payment id is present": (res) => res.status === 201 && Number.isInteger(res.json("payment_id")),
  });

  sleep(parseSleepSeconds(__ENV.K6_SLEEP_SECONDS));
}
