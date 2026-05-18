import { check, fail, sleep } from "k6";
import { Counter } from "k6/metrics";
import http from "k6/http";

import { AUTH_RATE_LIMIT_OPTIONS, BASE_URL, jsonParams } from "../config.js";

const rateLimit429Counter = new Counter("rate_limit_429_total");

http.setResponseCallback(http.expectedStatuses({ min: 200, max: 399 }, 401, 429));

export const options = {
  ...AUTH_RATE_LIMIT_OPTIONS,
  thresholds: {
    ...AUTH_RATE_LIMIT_OPTIONS.thresholds,
    rate_limit_429_total: ["count>=1"],
  },
};

function recordRateLimit(response, endpoint) {
  if (response.status === 429) {
    rateLimit429Counter.add(1, { endpoint });
  }
}

/**
 * Parses a positive sleep duration in seconds and falls back to 0.1 seconds.
 *
 * @param {string | undefined} value Environment value to parse.
 * @returns {number} Positive finite sleep duration.
 */
function parseSleepSeconds(value) {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0.1;
}

/**
 * Verifies authentication failures before the high-frequency rate-limit phase.
 *
 * @returns {{orderPayload: string}} Data consumed by VUs.
 */
export function setup() {
  const orderPayload = JSON.stringify({
    items: [{ product_id: 1, quantity: 1 }],
  });

  const noToken = http.post(
    `${BASE_URL}/orders`,
    orderPayload,
    jsonParams({}, { endpoint: "auth_missing_token_setup" }),
  );
  if (noToken.status !== 401) {
    fail(`missing token setup check expected 401, got ${noToken.status}`);
  }


  const invalidToken = http.post(
    `${BASE_URL}/orders`,
    orderPayload,
    jsonParams(
      { Authorization: "Bearer invalid.k6.token" },
      { endpoint: "auth_invalid_token_setup" },
    ),
  );
  if (invalidToken.status !== 401) {
    fail(`invalid token setup check expected 401, got ${invalidToken.status}`);
  }

  return { orderPayload };
}

/**
 * Exercises gateway authentication failures and rate-limit responses.
 *
 * @param {{orderPayload: string}} data Setup output.
 * @returns {void}
 */
export default function (data) {
  const noToken = http.post(
    `${BASE_URL}/orders`,
    data.orderPayload,
    jsonParams({}, { endpoint: "auth_missing_token" }),
  );
  recordRateLimit(noToken, "auth_missing_token");

  check(noToken, {
    "missing token is 401 or rate-limited": (res) => [401, 429].includes(res.status),
  });

  const invalidToken = http.post(
    `${BASE_URL}/orders`,
    data.orderPayload,
    jsonParams(
      { Authorization: "Bearer invalid.k6.token" },
      { endpoint: "auth_invalid_token" },
    ),
  );
  recordRateLimit(invalidToken, "auth_invalid_token");

  check(invalidToken, {
    "invalid token is 401 or rate-limited": (res) => [401, 429].includes(res.status),
  });

  const productList = http.get(
    `${BASE_URL}/products?page=1&page_size=10&active_only=true`,
    jsonParams({}, { endpoint: "rate_limit_probe" }),
  );
  recordRateLimit(productList, "rate_limit_probe");

  check(productList, {
    "rate-limit probe is 200 or 429": (res) => [200, 429].includes(res.status),
  });

  sleep(parseSleepSeconds(__ENV.K6_AUTH_RATE_LIMIT_SLEEP_SECONDS));
}
