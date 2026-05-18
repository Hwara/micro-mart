import { check, fail, sleep } from "k6";
import http from "k6/http";

import { BASE_URL, jsonParams, parseProductIds, STOCK_CONTENTION_OPTIONS } from "../config.js";
import { getAccessToken } from "../lib/auth.js";

export const options = STOCK_CONTENTION_OPTIONS;

const CONTENTION_PRODUCT_NAME = __ENV.K6_CONTENTION_PRODUCT_NAME || "k6-contention-single";

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
 * Resolves the single product ID used by all VUs in this contention scenario.
 *
 * PRODUCT_IDS takes precedence for ad hoc runs. Otherwise this function looks
 * for the seeded k6-contention-single product so unrelated baseline products
 * do not accidentally become the contention target.
 *
 * @param {string} baseUrl Gateway base URL.
 * @returns {number} Positive product ID.
 */
function resolveContentionProductId(baseUrl) {
  const explicitIds = parseProductIds();
  if (explicitIds.length > 0) {
    return explicitIds[0];
  }

  const response = http.get(
    `${baseUrl}/products?page=1&page_size=100&active_only=true`,
    jsonParams({}, { endpoint: "product_list_contention" }),
  );

  if (response.status !== 200) {
    fail(`contention product list failed: status=${response.status} body=${response.body}`);
  }

  const body = response.json();
  const items = Array.isArray(body.items) ? body.items : [];
  const product = items.find(
    (item) => item.name === CONTENTION_PRODUCT_NAME && Number.isInteger(item.id) && item.id > 0,
  );

  if (!product) {
    fail(
      `no contention product found. Seed productdb with k6/setup/seed-stock-contention.sql or set PRODUCT_IDS=123`,
    );
  }

  return product.id;
}

/**
 * Prepares shared VU data by resolving auth and the single contention product.
 *
 * @returns {{accessToken: string, productId: number}} Data consumed by the
 * default VU function.
 */
export function setup() {
  const accessToken = getAccessToken(BASE_URL);
  const productId = resolveContentionProductId(BASE_URL);
  return { accessToken, productId };
}

/**
 * Creates one order against the same product from every VU.
 *
 * @param {{accessToken: string, productId: number}} data Setup output.
 * @returns {void}
 */
export default function (data) {
  const payload = JSON.stringify({
    items: [{ product_id: data.productId, quantity: 1 }],
  });

  const response = http.post(
    `${BASE_URL}/orders`,
    payload,
    jsonParams(
      { Authorization: `Bearer ${data.accessToken}` },
      { endpoint: "order_create_contention" },
    ),
  );

  check(response, {
    "contention order create is 201": (res) => res.status === 201,
    "contention order completed": (res) => res.status === 201 && res.json("status") === "COMPLETED",
    "contention payment id is present": (res) =>
      res.status === 201 && Number.isInteger(res.json("payment_id")),
  });

  sleep(parseSleepSeconds(__ENV.K6_CONTENTION_SLEEP_SECONDS || __ENV.K6_SLEEP_SECONDS));
}
