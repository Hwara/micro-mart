import { fail } from "k6";
import http from "k6/http";

import { jsonParams, TEST_USER_DEVICE, TEST_USER_EMAIL, TEST_USER_PASSWORD } from "../config.js";

export function registerBaselineUser(baseUrl) {
  const payload = JSON.stringify({
    email: TEST_USER_EMAIL,
    password: TEST_USER_PASSWORD,
  });

  const response = http.post(`${baseUrl}/auth/register`, payload, jsonParams({}, { endpoint: "auth_register" }));

  if (![201, 409].includes(response.status)) {
    fail(`baseline user registration failed: status=${response.status} body=${response.body}`);
  }
}

export function loginBaselineUser(baseUrl) {
  const payload = JSON.stringify({
    email: TEST_USER_EMAIL,
    password: TEST_USER_PASSWORD,
    device: TEST_USER_DEVICE,
  });

  const response = http.post(`${baseUrl}/auth/login`, payload, jsonParams({}, { endpoint: "auth_login" }));

  if (response.status !== 200) {
    fail(`baseline user login failed: status=${response.status} body=${response.body}`);
  }

  const body = response.json();
  if (!body.access_token) {
    fail(`baseline user login response did not include access_token: body=${response.body}`);
  }

  return body.access_token;
}

export function getAccessToken(baseUrl) {
  registerBaselineUser(baseUrl);
  return loginBaselineUser(baseUrl);
}
