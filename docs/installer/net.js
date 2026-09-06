export async function fetchBinary(url, onProgress = () => {}) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`download failed (${response.status}): ${url}`);

  const total = Number(response.headers.get("Content-Length")) || 0;
  const reader = response.body.getReader();
  const chunks = [];
  let received = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    chunks.push(value);
    received += value.length;
    onProgress(received, total);
  }

  const out = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out.buffer;
}

export function toBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}
