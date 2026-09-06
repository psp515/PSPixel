// Every hardcoded endpoint, id and limit the installer depends on.

export const OWNER = "psp515";
export const REPO = "PicoController";

export const GITHUB_API = "https://api.github.com";
export const GITHUB_RAW = "https://raw.githubusercontent.com";

// Last-resort firmware when neither the picked ref nor `main` has a
// MICROPYTHON_VERSION pin (a tag cut before that file existed) - bump this in
// step with the repo-root MICROPYTHON_VERSION file so it doesn't drift.
export const DEFAULT_FIRMWARE_URL =
  "https://micropython.org/resources/firmware/RPI_PICO_W-20260824-v1.29.0.uf2";

export const USB_VENDOR_ID = 0x2e8a;
export const USB_PRODUCT_ID = 0x0003;

export const CERT_MAX_BYTES = 16 * 1024; // matches CERT_MAX_BYTES in src/channels/webapi.py

export const DEFAULT_BRANCH = "main";

export function apiUrl(path) {
  return `${GITHUB_API}/repos/${OWNER}/${REPO}/${path}`;
}

export function rawUrl(ref, path) {
  return `${GITHUB_RAW}/${OWNER}/${REPO}/${encodeURIComponent(ref)}/${path}`;
}
