import assert from "node:assert/strict";
import test from "node:test";

import { isDeviceFile, dirsFor, orderBranches } from "../../docs/public/installer/source.js";

test("isDeviceFile accepts main.py, src/lib .py files, and static assets", () => {
  assert.equal(isDeviceFile("main.py"), true);
  assert.equal(isDeviceFile("src/application.py"), true);
  assert.equal(isDeviceFile("lib/mqtt_as.py"), true);
  assert.equal(isDeviceFile("src/webui/static/index.html"), true);
  assert.equal(isDeviceFile("src/webui/static/js/app.js"), true);
});

test("isDeviceFile rejects host-only files", () => {
  assert.equal(isDeviceFile("tests/test_storage.py"), false);
  assert.equal(isDeviceFile("helpers/reset.py"), false);
  assert.equal(isDeviceFile("docs/web-installer.md"), false);
  assert.equal(isDeviceFile("README.md"), false);
  assert.equal(isDeviceFile("src/webui/webui.py.bak"), false);
});

test("dirsFor lists every parent directory, shallowest first", () => {
  const dirs = dirsFor(["main.py", "src/application.py", "src/webui/static/index.html"]);
  assert.deepEqual(dirs, ["src", "src/webui", "src/webui/static"]);
});

test("orderBranches puts main first, then the rest alphabetically", () => {
  assert.deepEqual(orderBranches(["psp/test", "main", "feature/a"]), ["main", "feature/a", "psp/test"]);
  assert.deepEqual(orderBranches(["psp/test", "feature/a"]), ["feature/a", "psp/test"]);
  assert.deepEqual(orderBranches([]), []);
});
