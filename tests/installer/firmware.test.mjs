import assert from "node:assert/strict";
import test from "node:test";

import { parseFirmwarePin, assertAllowedFirmwareUrl } from "../../docs/public/installer/source.js";
import { FIRMWARE_URL_PREFIX } from "../../docs/public/installer/const.js";

const OK_URL = `${FIRMWARE_URL_PREFIX}RPI_PICO_W-20260824-v1.29.0.uf2`;
const SHA = "a".repeat(64);

test("parses a bare URL pin", () => {
  assert.deepEqual(parseFirmwarePin(`${OK_URL}\n`), { url: OK_URL, sha256: null });
});

test("parses a URL + SHA-256 pin, lowercasing the digest", () => {
  assert.deepEqual(parseFirmwarePin(`${OK_URL}\n${SHA.toUpperCase()}\n`), {
    url: OK_URL,
    sha256: SHA,
  });
});

test("rejects a firmware URL off the official download path", () => {
  assert.throws(() => parseFirmwarePin("https://evil.example/pico.uf2"), /not under/);
  assert.throws(
    () => assertAllowedFirmwareUrl("https://micropython.org.evil.example/resources/firmware/x.uf2"),
    /not under/
  );
});

test("rejects a malformed second field", () => {
  assert.throws(() => parseFirmwarePin(`${OK_URL} not-a-hash`), /SHA-256/);
});

test("rejects empty content", () => {
  assert.throws(() => parseFirmwarePin("   \n"), /empty/);
});
