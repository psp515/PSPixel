import assert from "node:assert/strict";
import test from "node:test";

import { splitB64 } from "../../docs/installer/repl.js";

function randomBytes(n) {
  const out = new Uint8Array(n);
  for (let i = 0; i < n; i += 1) out[i] = (i * 7 + 3) % 256;
  return out;
}

function toB64(bytes) {
  let binary = "";
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  return Buffer.from(binary, "binary").toString("base64");
}

test("every chunk is independently valid base64 (length is a multiple of 4)", () => {
  for (const size of [1, 2, 3, 100, 1023, 1024, 1025, 3000]) {
    const b64 = toB64(randomBytes(size));
    for (const chunk of splitB64(b64, 1024)) {
      assert.equal(chunk.length % 4, 0, `chunk length ${chunk.length} for input size ${size}`);
    }
  }
});

test("concatenated chunks decode back to the original bytes", () => {
  for (const size of [1, 2, 3, 100, 1023, 1024, 1025, 3000]) {
    const original = randomBytes(size);
    const b64 = toB64(original);
    const rebuilt = splitB64(b64, 1024).join("");
    const decoded = Buffer.from(rebuilt, "base64");
    assert.deepEqual(new Uint8Array(decoded), original);
  }
});
