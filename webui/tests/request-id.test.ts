import assert from "node:assert/strict";
import test from "node:test";

import { createRequestId } from "../src/utils/request-id.ts";

test("uses crypto.randomUUID when the browser provides it", () => {
  assert.equal(createRequestId({ randomUUID: () => "provided-id" }), "provided-id");
});

test("generates a UUID with getRandomValues when randomUUID is unavailable", () => {
  const requestId = createRequestId({
    getRandomValues: (array) => array.fill(0),
  });
  assert.equal(requestId, "00000000-0000-4000-8000-000000000000");
});

test("falls back to a unique request id without Web Crypto", () => {
  const first = createRequestId({});
  const second = createRequestId({});
  assert.notEqual(first, second);
  assert.match(first, /^[a-z0-9]+-[a-z0-9]{4}-[a-z0-9]+$/);
});
