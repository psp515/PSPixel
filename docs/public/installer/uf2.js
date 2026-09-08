const MAGIC_START0 = 0x0a324655;
const MAGIC_START1 = 0x9e5d5157;
const MAGIC_END = 0x0ab16f30;
const FLAG_FAMILY_ID = 0x00002000;
const RP2040_FAMILY_ID = 0xe48bff56;

export function parseUf2(buffer) {
  const view = new DataView(buffer);
  const blocks = [];
  for (let offset = 0; offset + 512 <= buffer.byteLength; offset += 512) {
    if (
      view.getUint32(offset, true) !== MAGIC_START0 ||
      view.getUint32(offset + 4, true) !== MAGIC_START1 ||
      view.getUint32(offset + 508, true) !== MAGIC_END
    ) {
      continue;
    }
    const flags = view.getUint32(offset + 8, true);
    const addr = view.getUint32(offset + 12, true);
    const payloadSize = view.getUint32(offset + 16, true);
    if (payloadSize > 476) continue; // a UF2 block's data area is 476 bytes; anything larger is a malformed/hostile header
    const familyId = view.getUint32(offset + 28, true);
    if (flags & FLAG_FAMILY_ID && familyId !== RP2040_FAMILY_ID) continue;
    blocks.push({ addr, data: new Uint8Array(buffer, offset + 32, payloadSize) });
  }
  if (!blocks.length) throw new Error("no RP2040 blocks found in .uf2");
  blocks.sort((a, b) => a.addr - b.addr);
  return coalesce(blocks);
}

function coalesce(blocks) {
  const runs = [];
  for (const block of blocks) {
    const last = runs[runs.length - 1];
    if (last && block.addr === last.addr + last.bytes.length) {
      const merged = new Uint8Array(last.bytes.length + block.data.length);
      merged.set(last.bytes, 0);
      merged.set(block.data, last.bytes.length);
      last.bytes = merged;
    } else {
      runs.push({ addr: block.addr, bytes: new Uint8Array(block.data) });
    }
  }
  return runs;
}
