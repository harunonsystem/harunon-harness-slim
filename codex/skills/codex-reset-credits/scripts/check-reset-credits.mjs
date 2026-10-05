#!/usr/bin/env node

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const ENDPOINT = "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits";
const AUTH_PATH = path.join(os.homedir(), ".codex", "auth.json");

function readAuth() {
  try {
    return JSON.parse(fs.readFileSync(AUTH_PATH, "utf8"));
  } catch (error) {
    throw new Error(`failed to read ${AUTH_PATH}: unable to read or parse auth`);
  }
}

function firstString(...values) {
  return values.find((value) => typeof value === "string" && value.length > 0);
}

function findNestedString(value, keyNames) {
  if (!value || typeof value !== "object") return undefined;
  for (const [key, nestedValue] of Object.entries(value)) {
    if (keyNames.includes(key) && typeof nestedValue === "string" && nestedValue.length > 0) {
      return nestedValue;
    }
  }
  for (const nestedValue of Object.values(value)) {
    const found = findNestedString(nestedValue, keyNames);
    if (found) return found;
  }
  return undefined;
}

function getAccessToken(auth) {
  return firstString(
    auth?.tokens?.access_token,
    auth?.tokens?.accessToken,
    auth?.access_token,
    auth?.accessToken,
    findNestedString(auth, ["access_token", "accessToken"]),
  );
}

function getAccountId(auth) {
  return firstString(
    auth?.tokens?.account_id,
    auth?.tokens?.accountId,
    auth?.account_id,
    auth?.accountId,
    auth?.current_account_id,
    auth?.currentAccountId,
    findNestedString(auth, ["account_id", "accountId", "current_account_id", "currentAccountId"]),
  );
}

function getCredits(data) {
  if (Array.isArray(data)) return data;
  for (const key of ["credits", "reset_credits", "resetCredits", "items", "data"]) {
    if (Array.isArray(data?.[key])) return data[key];
  }
  return [];
}

function getCount(data, credits) {
  for (const key of ["count", "available_count", "availableCount", "remaining", "remaining_count", "remainingCount"]) {
    if (Number.isSafeInteger(data?.[key]) && data[key] >= 0) return data[key];
  }
  return credits.length;
}

function getExpiresAt(credit) {
  return firstString(
    credit?.expires_at,
    credit?.expiresAt,
    credit?.expiration_time,
    credit?.expirationTime,
    credit?.expires,
  );
}

function formatLocalDate(raw) {
  if (!raw) return "(missing)";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return "(invalid date)";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  });
}

async function main() {
  const auth = readAuth();
  const accessToken = getAccessToken(auth);
  if (!accessToken) {
    throw new Error(`access token not found in ${AUTH_PATH}`);
  }

  const headers = {
    authorization: `Bearer ${accessToken}`,
    "content-type": "application/json",
  };
  const accountId = getAccountId(auth);
  if (accountId) {
    headers["chatgpt-account-id"] = accountId;
  }

  let response;
  try {
    response = await fetch(ENDPOINT, { headers, signal: AbortSignal.timeout(15_000) });
  } catch {
    throw new Error("reset-credit request failed or timed out");
  }
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`endpoint returned HTTP ${response.status}`);
  }

  let data;
  try { data = JSON.parse(text); } catch { throw new Error("reset-credit response is not valid JSON"); }
  const credits = getCredits(data);
  const count = getCount(data, credits);

  console.log("Codex reset credits");
  console.log(`endpoint: ${ENDPOINT}`);
  console.log(`available_reset_credits: ${count}`);

  if (credits.length > 0) {
    for (const [index, credit] of credits.entries()) {
      const expiresAt = getExpiresAt(credit);
      console.log(`${index + 1}. expires_at: ${formatLocalDate(expiresAt)}`);
    }
    return;
  }

  console.log("credits: []");
  console.log("response_details: omitted (unrecognized fields may contain credentials)");
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});

