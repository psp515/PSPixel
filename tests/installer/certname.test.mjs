import assert from "node:assert/strict";
import test from "node:test";

import { isValidCertName } from "../../docs/public/installer/repl.js";

test("accepts plain basenames", () => {
  assert.equal(isValidCertName("ca.pem"), true);
  assert.equal(isValidCertName("broker-root_2.der"), true);
});

test("rejects traversal, separators, and tricky names", () => {
  for (const name of ["", ".", "..", "../ca.pem", "certs/ca.pem", "ca\\pem", "ca pem", "café.pem", "a".repeat(65)]) {
    assert.equal(isValidCertName(name), false, name);
  }
});
