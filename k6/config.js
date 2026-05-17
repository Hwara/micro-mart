export const BASE_URL = (__ENV.BASE_URL || "http://localhost:8080").replace(/\/$/, "");

export const TEST_USER_EMAIL = __ENV.K6_USER_EMAIL || "k6-baseline@example.com";
export const TEST_USER_PASSWORD = __ENV.K6_USER_PASSWORD || "password1234";
export const TEST_USER_DEVICE = __ENV.K6_USER_DEVICE || "k6-baseline";

export const PRODUCT_NAME_PREFIX = __ENV.K6_PRODUCT_PREFIX || "k6-baseline-";

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
    { duration: __ENV.K6_RAMP_UP || "1m", target: Number(__ENV.K6_TARGET_VUS || 20) },
    { duration: __ENV.K6_STEADY || "5m", target: Number(__ENV.K6_TARGET_VUS || 20) },
    { duration: __ENV.K6_RAMP_DOWN || "1m", target: 0 },
  ],
  thresholds: {
    checks: ["rate>0.99"],
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<1000"],
    "http_req_duration{endpoint:order_create}": ["p(95)<1000"],
  },
};

export function parseProductIds() {
  if (!__ENV.PRODUCT_IDS) {
    return [];
  }

  return __ENV.PRODUCT_IDS.split(",")
    .map((id) => Number(id.trim()))
    .filter((id) => Number.isInteger(id) && id > 0);
}

export function jsonParams(extraHeaders = {}, tags = {}) {
  return {
    headers: {
      "Content-Type": "application/json",
      ...extraHeaders,
    },
    tags,
  };
}
