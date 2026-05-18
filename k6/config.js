export const BASE_URL = (__ENV.BASE_URL || "http://localhost:8080").replace(/\/$/, "");

export const TEST_USER_EMAIL = __ENV.K6_USER_EMAIL || "k6-baseline@example.com";
export const TEST_USER_PASSWORD = __ENV.K6_USER_PASSWORD || "password1234";
export const TEST_USER_DEVICE = __ENV.K6_USER_DEVICE || "k6-baseline";

export const PRODUCT_NAME_PREFIX = __ENV.K6_PRODUCT_PREFIX || "k6-baseline-";

/**
 * Parses a positive integer setting and falls back when the value is invalid.
 *
 * @param {string | undefined} value Environment value to parse.
 * @param {number} fallback Positive integer fallback.
 * @returns {number} Parsed positive integer or fallback.
 */
function parsePositiveInteger(value, fallback) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

const TARGET_VUS = parsePositiveInteger(__ENV.K6_TARGET_VUS, 20);

export const SMOKE_OPTIONS = {
  vus: 1,
  iterations: 1,
  thresholds: {
    checks: ["rate==1"],
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<1000"],
  },
};

export const BASELINE_OPTIONS = {
  stages: [
    { duration: __ENV.K6_RAMP_UP || "1m", target: TARGET_VUS },
    { duration: __ENV.K6_STEADY || "5m", target: TARGET_VUS },
    { duration: __ENV.K6_RAMP_DOWN || "1m", target: 0 },
  ],
  thresholds: {
    checks: ["rate>0.99"],
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<1000"],
    "http_req_duration{endpoint:order_create}": ["p(95)<1000"],
  },
};

/**
 * Reads comma-separated PRODUCT_IDS from __ENV and returns positive integer IDs.
 *
 * Missing or empty PRODUCT_IDS returns an empty array. Each value is trimmed,
 * converted to Number, and kept only when it is an integer greater than zero.
 *
 * @returns {number[]} Product IDs to use directly instead of fetching products.
 */
export function parseProductIds() {
  if (!__ENV.PRODUCT_IDS) {
    return [];
  }

  return __ENV.PRODUCT_IDS.split(",")
    .map((id) => Number(id.trim()))
    .filter((id) => Number.isInteger(id) && id > 0);
}

/**
 * Builds JSON request options for k6 HTTP calls.
 *
 * @param {Record<string, string>} [extraHeaders={}] Headers merged after the
 * default Content-Type, allowing callers to override it.
 * @param {Record<string, string>} [tags={}] k6 tags passed through unchanged.
 * @returns {{headers: Record<string, string>, tags: Record<string, string>}}
 */
export function jsonParams(extraHeaders = {}, tags = {}) {
  return {
    headers: {
      "Content-Type": "application/json",
      ...extraHeaders,
    },
    tags,
  };
}
