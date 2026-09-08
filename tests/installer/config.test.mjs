import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import test from "node:test";

import { configJson } from "../../docs/public/installer/repl.js";

const SAMPLE_FORM = {
  deviceName: "Pico",
  wifiSsid: "MyWifi",
  wifiPassword: "secret",
  ledCount: 60,
  ledPin: 0,
  watchdog: true,
  apSsid: "PSPixel",
  apPassword: "Pico123456!",
  ledsOnAfterBoot: true,
  segmentingEnabled: false,
  segmentLength: 2,
  mqttEnabled: true,
  mqttServer: "broker.local",
  mqttPort: 8883,
  mqttUser: "user",
  mqttPassword: "pass",
  mqttBaseTopic: "controller/led/1",
  mqttSingleTopic: false,
  mqttSsl: true,
  mqttNtpHost: "pool.ntp.org",
  mqttCertValidate: true,
  mqttCertificateName: "broker.der",
  buttonEnabled: true,
  irEnabled: true,
  wifiAccess: true,
  defaultMode: "normal",
  loggingEnabled: false,
  loggingLevel: "info",
};

// Every key path configJson() writes must exist somewhere in the real
// DEFAULTS (src/defaults.py) - otherwise Storage's merge() would be adding
// a key the device never reads, silently doing nothing.
function keyPaths(obj, prefix = "") {
  const paths = [];
  for (const [key, value] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      paths.push(...keyPaths(value, path));
    } else {
      paths.push(path);
    }
  }
  return paths;
}

test("configJson only writes keys that exist in DEFAULTS", () => {
  const config = JSON.parse(configJson(SAMPLE_FORM));
  const configPaths = keyPaths(config);

  const defaultsJson = execFileSync("python", [
    "-c",
    "import json, sys; sys.path.insert(0, 'src'); from defaults import DEFAULTS; print(json.dumps(DEFAULTS))",
  ]).toString();
  const defaults = JSON.parse(defaultsJson);
  const defaultsPaths = new Set(keyPaths(defaults));

  for (const path of configPaths) {
    assert.ok(defaultsPaths.has(path), `configJson writes ${path}, which DEFAULTS doesn't have`);
  }
});

test("configJson round-trips the sample form's values", () => {
  const config = JSON.parse(configJson(SAMPLE_FORM));
  assert.equal(config.device.name, "Pico");
  assert.equal(config.network.wifi.ssid, "MyWifi");
  assert.equal(config.leds.segmenting.length, 2);
  assert.equal(config.mqtt.certificate.validate, true);
  assert.equal(config.mqtt.certificate.name, "broker.der");
  assert.equal(config.system.default_mode, "normal");
});
