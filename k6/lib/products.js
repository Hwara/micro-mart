import { fail } from "k6";
import http from "k6/http";

import { jsonParams, parseProductIds, PRODUCT_NAME_PREFIX } from "../config.js";

/**
 * Resolves product IDs for k6 order scenarios.
 *
 * PRODUCT_IDS from parseProductIds takes precedence. If none are provided, this
 * fetches /products and selects active items whose names start with
 * PRODUCT_NAME_PREFIX. Non-200 responses or an empty validated result fail.
 *
 * @param {string} baseUrl Gateway base URL.
 * @returns {number[]} Positive integer product IDs.
 */
export function resolveProductIds(baseUrl) {
  const explicitIds = parseProductIds();
  if (explicitIds.length > 0) {
    return explicitIds;
  }

  const response = http.get(
    `${baseUrl}/products?page=1&page_size=100&active_only=true`,
    jsonParams({}, { endpoint: "product_list" }),
  );

  if (response.status !== 200) {
    fail(`product list failed: status=${response.status} body=${response.body}`);
  }

  const body = response.json();
  const items = Array.isArray(body.items) ? body.items : [];
  const productIds = items
    .filter(
      (product) =>
        product.name &&
        product.name.startsWith(PRODUCT_NAME_PREFIX) &&
        Number.isInteger(product.id) &&
        product.id > 0,
    )
    .map((product) => product.id);

  if (productIds.length === 0) {
    fail(
      `no seeded products found. Seed productdb with names starting with "${PRODUCT_NAME_PREFIX}" or set PRODUCT_IDS=1,2,3`,
    );
  }

  return productIds;
}

/**
 * Picks one product ID uniformly at random from the resolved ID pool.
 *
 * @param {number[]} productIds Positive integer product IDs.
 * @returns {number} A randomly selected product ID.
 */
export function pickProductId(productIds) {
  return productIds[Math.floor(Math.random() * productIds.length)];
}
