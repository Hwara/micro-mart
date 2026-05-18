import { check, sleep } from "k6";
import http from "k6/http";

import { BASE_URL, jsonParams, MIXED_TRAFFIC_OPTIONS } from "../config.js";
import { getAccessToken } from "../lib/auth.js";
import { pickProductId, resolveProductIds } from "../lib/products.js";

export const options = MIXED_TRAFFIC_OPTIONS;

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
 * Creates one completed order for order-detail reads in the mixed scenario.
 *
 * @param {string} baseUrl Gateway base URL.
 * @param {string} accessToken Access token for the baseline user.
 * @param {number} productId Product ID to order once.
 * @returns {number | null} Created order ID, or null if the setup order failed.
 */
function createSeedOrder(baseUrl, accessToken, productId) {
  const payload = JSON.stringify({
    items: [{ product_id: productId, quantity: 1 }],
  });

  const response = http.post(
    `${baseUrl}/orders`,
    payload,
    jsonParams({ Authorization: `Bearer ${accessToken}` }, { endpoint: "order_create_setup" }),
  );

  if (response.status !== 201) {
    return null;
  }

  const orderId = response.json("id");
  return Number.isInteger(orderId) && orderId > 0 ? orderId : null;
}

/**
 * Prepares auth, product IDs, and one readable order for mixed traffic.
 *
 * @returns {{accessToken: string, productIds: number[], seedOrderId: number | null}} Setup output.
 */
export function setup() {
  const accessToken = getAccessToken(BASE_URL);
  const productIds = resolveProductIds(BASE_URL);
  const seedOrderId = createSeedOrder(BASE_URL, accessToken, productIds[0]);
  return { accessToken, productIds, seedOrderId };
}

/**
 * Runs a simple production-like read/write mix through the api-gateway.
 *
 * @param {{accessToken: string, productIds: number[], seedOrderId: number | null}} data Setup output.
 * @returns {void}
 */
export default function (data) {
  const roll = Math.random();
  const authHeaders = { Authorization: `Bearer ${data.accessToken}` };

  if (roll < 0.45) {
    const response = http.get(
      `${BASE_URL}/products?page=1&page_size=20&active_only=true`,
      jsonParams({}, { endpoint: "product_list_mixed" }),
    );
    check(response, { "mixed product list is 200": (res) => res.status === 200 });
  } else if (roll < 0.7) {
    const productId = pickProductId(data.productIds);
    const response = http.get(
      `${BASE_URL}/products/${productId}`,
      jsonParams({}, { endpoint: "product_detail_mixed" }),
    );
    check(response, { "mixed product detail is 200": (res) => res.status === 200 });
  } else if (roll < 0.85) {
    const response = http.get(
      `${BASE_URL}/orders?page=1&page_size=20`,
      jsonParams(authHeaders, { endpoint: "order_list_mixed" }),
    );
    check(response, { "mixed order list is 200": (res) => res.status === 200 });
  } else if (roll < 0.95 && data.seedOrderId) {
    const response = http.get(
      `${BASE_URL}/orders/${data.seedOrderId}`,
      jsonParams(authHeaders, { endpoint: "order_detail_mixed" }),
    );
    check(response, { "mixed order detail is 200": (res) => res.status === 200 });
  } else {
    const productId = pickProductId(data.productIds);
    const payload = JSON.stringify({
      items: [{ product_id: productId, quantity: 1 }],
    });
    const response = http.post(
      `${BASE_URL}/orders`,
      payload,
      jsonParams(authHeaders, { endpoint: "order_create_mixed" }),
    );
    check(response, {
      "mixed order create is 201": (res) => res.status === 201,
      "mixed order completed": (res) => res.status === 201 && res.json("status") === "COMPLETED",
    });
  }

  sleep(parseSleepSeconds(__ENV.K6_MIXED_TRAFFIC_SLEEP_SECONDS || __ENV.K6_SLEEP_SECONDS));
}
