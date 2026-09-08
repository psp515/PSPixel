import { DEFAULT_BRANCH, FIRMWARE_URL_PREFIX, apiUrl, rawUrl } from "./const.js";
import { toBase64 } from "./net.js";

// Assembles the device file set ({dirs, files}) straight from a git ref (a
// tag or a branch), so the installer needs nothing beyond what's pushed to
// GitHub - no build or release step.

const STATIC_PREFIX = "src/webui/static";

export function isDeviceFile(path) {
  if (path === "main.py") return true;
  if (!path.startsWith("src/") && !path.startsWith("lib/")) return false;
  return path.endsWith(".py") || path.startsWith(STATIC_PREFIX);
}

export function dirsFor(paths) {
  const seen = new Set();
  for (const path of paths) {
    const parts = path.split("/").slice(0, -1);
    for (let i = 1; i <= parts.length; i += 1) seen.add(parts.slice(0, i).join("/"));
  }
  return [...seen].sort((a, b) => {
    const depthDiff = a.split("/").length - b.split("/").length;
    return depthDiff !== 0 ? depthDiff : a.localeCompare(b);
  });
}

// Default branch first, then the rest alphabetically - GitHub returns
// branches in its own order, which isn't useful in a picker.
export function orderBranches(names) {
  const rest = names.filter((name) => name !== DEFAULT_BRANCH).sort((a, b) => a.localeCompare(b));
  return names.includes(DEFAULT_BRANCH) ? [DEFAULT_BRANCH, ...rest] : rest;
}

async function githubJson(path, notFoundMessage = null) {
  const response = await fetch(apiUrl(path), { headers: { Accept: "application/vnd.github+json" } });
  if (response.status === 404 && notFoundMessage) throw new Error(notFoundMessage);
  if (response.status === 403) {
    throw new Error("GitHub API rate limit hit - try again in a few minutes");
  }
  if (!response.ok) throw new Error(`GitHub API returned ${response.status}`);
  return response.json();
}

// Tag names, as returned by GitHub (newest first in practice, not contractually).
export async function fetchTagList() {
  const tags = await githubJson("tags?per_page=100");
  return tags.map((tag) => tag.name);
}

export async function fetchBranchList() {
  const branches = await githubJson("branches?per_page=100");
  return orderBranches(branches.map((branch) => branch.name));
}

export function assertAllowedFirmwareUrl(url) {
  if (!url.startsWith(FIRMWARE_URL_PREFIX)) {
    throw new Error(`firmware URL not under ${FIRMWARE_URL_PREFIX}: ${url}`);
  }
}

// MICROPYTHON_VERSION is the firmware .uf2 URL, optionally followed by
// whitespace/newline and a SHA-256 hex digest of that file. The URL is
// checked against the official-download allowlist; the digest, when present,
// is verified against the downloaded bytes before anything is flashed.
export function parseFirmwarePin(text) {
  const [url, sha256] = text.trim().split(/\s+/);
  if (!url) throw new Error("MICROPYTHON_VERSION is empty");
  assertAllowedFirmwareUrl(url);
  if (sha256 !== undefined && !/^[0-9a-f]{64}$/i.test(sha256)) {
    throw new Error(`MICROPYTHON_VERSION second field is not a SHA-256 hex digest: ${sha256}`);
  }
  return { url, sha256: sha256 ? sha256.toLowerCase() : null };
}

export async function fetchFirmwarePin(ref) {
  const response = await fetch(rawUrl(ref, "MICROPYTHON_VERSION"));
  if (!response.ok) throw new Error(`no MICROPYTHON_VERSION pin at ${ref}`);
  return parseFirmwarePin(await response.text());
}

export async function fetchSource(ref, onProgress = () => {}) {
  const tree = await githubJson(
    `git/trees/${encodeURIComponent(ref)}?recursive=1`,
    `ref ${ref} not found`
  );
  if (tree.truncated) throw new Error(`${ref} tree listing was truncated - too many files`);

  const paths = tree.tree
    .filter((item) => item.type === "blob")
    .map((item) => item.path)
    .filter(isDeviceFile)
    .sort();

  const files = [];
  for (const [index, path] of paths.entries()) {
    onProgress(index, paths.length, path);
    const raw = await fetch(rawUrl(ref, path));
    if (!raw.ok) throw new Error(`failed to fetch ${path} (${raw.status})`);
    const buffer = await raw.arrayBuffer();
    files.push({ path, size: buffer.byteLength, b64: toBase64(buffer) });
  }
  onProgress(paths.length, paths.length, "done");

  return { dirs: dirsFor(paths), files };
}
