import assert from "node:assert/strict";
import test from "node:test";

import { OWNER, REPO, DEFAULT_FIRMWARE_URL, apiUrl, rawUrl } from "../../docs/installer/const.js";

test("apiUrl builds repo-scoped GitHub API URLs", () => {
  assert.equal(apiUrl("tags?per_page=100"), `https://api.github.com/repos/${OWNER}/${REPO}/tags?per_page=100`);
});

test("rawUrl builds raw.githubusercontent URLs with the ref encoded", () => {
  assert.equal(rawUrl("v1.2.3", "main.py"), `https://raw.githubusercontent.com/${OWNER}/${REPO}/v1.2.3/main.py`);
  assert.equal(
    rawUrl("feature/web installer", "src/application.py"),
    `https://raw.githubusercontent.com/${OWNER}/${REPO}/feature%2Fweb%20installer/src/application.py`
  );
});

test("DEFAULT_FIRMWARE_URL points at a micropython.org RPI_PICO_W uf2", () => {
  assert.match(DEFAULT_FIRMWARE_URL, /^https:\/\/micropython\.org\/.*RPI_PICO_W-.*\.uf2$/);
});
