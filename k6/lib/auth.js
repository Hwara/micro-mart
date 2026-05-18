import { fail } from "k6";
import http from "k6/http";

import { jsonParams, TEST_USER_DEVICE, TEST_USER_EMAIL, TEST_USER_PASSWORD } from "../config.js";

const AUTH_REGISTER_EXPECTED = http.expectedStatuses(201, 409);

/**
 * Ensures the baseline user exists by POSTing registration data.
 *
 * @param {string} baseUrl Gateway base URL.
 * @returns {void}
 * @throws Calls fail when registration returns anything other than 201 or 409.
 */
export function registerBaselineUser(baseUrl) {
  const payload = JSON.stringify({
    email: TEST_USER_EMAIL,
    password: TEST_USER_PASSWORD,
  });

  const response = http.post(
    `${baseUrl}/auth/register`,
    payload,
    {
      ...jsonParams({}, { endpoint: "auth_register" }),
      responseCallback: AUTH_REGISTER_EXPECTED,
    },
  );
  if (![201, 409].includes(response.status)) {
    fail(`baseline user registration failed: status=${response.status}`);
  }
}

/**
 * Logs in the baseline user and returns the access token string.
 *
 * @param {string} baseUrl Gateway base URL.
 * @returns {string} Access token from the login response.
 * @throws Calls fail when login is not HTTP 200 or the response lacks access_token.
 */
export function loginBaselineUser(baseUrl) {
  const payload = JSON.stringify({
    email: TEST_USER_EMAIL,
    password: TEST_USER_PASSWORD,
    device: TEST_USER_DEVICE,
  });

  const response = http.post(`${baseUrl}/auth/login`, payload, jsonParams({}, { endpoint: "auth_login" }));

  if (response.status !== 200) {
    fail(`baseline user login failed: status=${response.status}`);
  }

  const body = response.json();
  if (!body.access_token) {
    fail(`baseline user login response did not include access_token: status=${response.status}`);
  }

  return body.access_token;
}

/**
 * Registers the baseline user if needed, then returns a fresh access token.
 *
 * @param {string} baseUrl Gateway base URL.
 * @returns {string} Access token for order creation requests.
 * @throws Propagates registerBaselineUser or loginBaselineUser fail conditions.
 */
export function getAccessToken(baseUrl) {
  registerBaselineUser(baseUrl);
  return loginBaselineUser(baseUrl);
}
