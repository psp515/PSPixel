import assert from "node:assert/strict";
import test from "node:test";

import { parseUf2 } from "../../docs/installer/uf2.js";

const MAGIC_START0 = 0x0a324655;
const MAGIC_START1 = 0x9e5d5157;
const MAGIC_END = 0x0ab16f30;
const FLAG_FAMILY_ID = 0x00002000;
const RP2040_FAMILY_ID = 0xe48bff56;

function block(addr, payload, familyId = RP2040_FAMILY_ID) {
  const buffer = new ArrayBuffer(512);
  const view = new DataView(buffer);
  view.setUint32(0, MAGIC_START0, true);
  view.setUint32(4, MAGIC_START1, true);
  view.setUint32(8, FLAG_FAMILY_ID, true);
  view.setUint32(12, addr, true);
  view.setUint32(16, payload.length, true);
  view.setUint32(28, familyId, true);
  view.setUint32(508, MAGIC_END, true);
  new Uint8Array(buffer, 32, payload.length).set(payload);
  return new Uint8Array(buffer);
}

function concat(blocks) {
  const out = new Uint8Array(blocks.length * 512);
  blocks.forEach((b, i) => out.set(b, i * 512));
  return out.buffer;
}

test("coalesces contiguous blocks into one run", () => {
  const uf2 = concat([
    block(0x10000000, new Uint8Array(256).fill(1)),
    block(0x10000100, new Uint8Array(256).fill(2)),
  ]);
  const runs = parseUf2(uf2);
  assert.equal(runs.length, 1);
  assert.equal(runs[0].addr, 0x10000000);
  assert.equal(runs[0].bytes.length, 512);
  assert.equal(runs[0].bytes[0], 1);
  assert.equal(runs[0].bytes[256], 2);
});

test("splits a gap into separate runs and sorts them", () => {
  const uf2 = concat([
    block(0x10002000, new Uint8Array(256).fill(9)),
    block(0x10000000, new Uint8Array(256).fill(1)),
  ]);
  const runs = parseUf2(uf2);
  assert.equal(runs.length, 2);
  assert.equal(runs[0].addr, 0x10000000);
  assert.equal(runs[1].addr, 0x10002000);
});

test("ignores blocks from other chip families", () => {
  const uf2 = concat([
    block(0x10000000, new Uint8Array(256).fill(1)),
    block(0x10000100, new Uint8Array(256).fill(2), 0x1c5f21b0),
  ]);
  const runs = parseUf2(uf2);
  assert.equal(runs[0].bytes.length, 256);
});

test("rejects a buffer with no valid blocks", () => {
  assert.throws(() => parseUf2(new ArrayBuffer(512)));
});
