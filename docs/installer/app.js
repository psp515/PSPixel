import { fetchTagList, fetchBranchList, fetchFirmwareUrl, fetchSource } from "./source.js";
import { fetchBinary, toBase64 } from "./net.js";
import { CERT_MAX_BYTES, DEFAULT_BRANCH, DEFAULT_FIRMWARE_URL } from "./const.js";
import { Picoboot, requestBootDevice, webusbSupported } from "./picoboot.js";
import { Repl, pushBundle, reboot, requestSerialPort, serialSupported, sleep } from "./repl.js";

const FALLBACK_DEFAULTS = {
  device: { name: "PicoController" },
  network: { ap: { ssid: "PicoController", password: "Pico123456!" } },
  leds: { count: 144, pin: 0, segmenting: { length: 2 } },
  mqtt: { port: 1883, base_topic: "controller/led/1", ntp_host: "pool.ntp.org" },
};

const OPEN_TIMEOUT_MS = 8000;
const ADVANCE_DELAY_MS = 700;

const els = {
  unsupported: document.getElementById("unsupported"),
  release: document.getElementById("release"),
  sourceSelect: document.getElementById("source-select"),
  versionSelect: document.getElementById("version-select"),
  uf2Version: document.getElementById("uf2-version"),
  log: document.getElementById("log"),
  firmwareProgress: document.getElementById("firmware-progress"),
  installProgress: document.getElementById("install-progress"),
  installLoading: document.getElementById("install-loading"),
  form: document.getElementById("config-form"),
};

const buttons = {
  flash: document.querySelector('[data-action="flash"]'),
  connect: document.querySelector('[data-action="connect"]'),
  skipFirmware: document.querySelector('[data-action="skip-firmware"]'),
  continueConfig: document.querySelector('[data-action="continue-config"]'),
  retryInstall: document.querySelector('[data-action="retry-install"]'),
  wifiScan: document.querySelector('[data-action="wifi-scan"]'),
};

const steps = {
  firmware: { step: document.getElementById("step-firmware"), status: document.getElementById("step-firmware-status") },
  connect: { step: document.getElementById("step-connect"), status: document.getElementById("step-connect-status") },
  config: { step: document.getElementById("step-config"), status: document.getElementById("step-config-status") },
  install: { step: document.getElementById("step-install"), status: document.getElementById("step-install-status") },
};

const stepEls = { 1: steps.firmware.step, 2: steps.connect.step, 3: steps.config.step, 4: steps.install.step };
const stepperItems = [...document.querySelectorAll(".stepper-item")];

// Sets the DOM property directly (not just the attribute) so hiding this
// panel can never depend on a stylesheet reload picking up [hidden] rules.
function setInstallLoading(visible) {
  els.installLoading.hidden = !visible;
  els.installLoading.style.display = visible ? "" : "none";
}

const STATUS_ICONS = { success: "✓", warning: "⚠", error: "✗" };

function setStepStatus(name, status, message) {
  const { step, status: statusEl } = steps[name];
  step.classList.remove("success", "warning", "error");
  statusEl.classList.remove("success", "warning", "error");
  if (status === "pending") {
    statusEl.hidden = true;
    return;
  }
  step.classList.add(status);
  statusEl.classList.add(status);
  statusEl.textContent = `${STATUS_ICONS[status]} ${message}`;
  statusEl.hidden = false;
}

// --- step navigation: one card visible at a time, replaced as each finishes ---

let currentStep = 1;
let maxReachedStep = 1;
const completedSteps = new Set();
let installState = "idle"; // idle | running | done | error

function renderStepper() {
  stepperItems.forEach((item) => {
    const n = Number(item.dataset.step);
    item.classList.toggle("active", n === currentStep);
    item.classList.toggle("done", completedSteps.has(n));
    item.disabled = n > maxReachedStep;
  });
}

function goToStep(n) {
  currentStep = n;
  maxReachedStep = Math.max(maxReachedStep, n);
  Object.entries(stepEls).forEach(([num, el]) => {
    el.hidden = Number(num) !== n;
  });
  renderStepper();
  if (n === 4 && installState === "idle") runInstall();
}

stepperItems.forEach((item) => {
  item.addEventListener("click", () => {
    const n = Number(item.dataset.step);
    if (n <= maxReachedStep) goToStep(n);
  });
});

renderStepper();

// state.ref: git ref to install from - a release tag or a branch name.
const state = { ref: null, bundle: null, repl: null, firmwareUrl: null };

function parseVersion(url) {
  const match = url && url.match(/v\d+\.\d+\.\d+/);
  return match ? match[0] : null;
}

function log(line) {
  els.log.textContent += `${line}\n`;
  els.log.scrollTop = els.log.scrollHeight;
}

// Content added while the collapsed <details> is closed can't scroll (it's
// not rendered), so jump to the bottom once it's actually opened.
document.getElementById("console-bar").addEventListener("toggle", (event) => {
  if (event.target.open) els.log.scrollTop = els.log.scrollHeight;
});

function fail(error) {
  log(`ERROR: ${error.message || error}`);
}

function withTimeout(promise, ms, message) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(message)), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

async function init() {
  if (!webusbSupported() || !serialSupported()) {
    els.unsupported.hidden = false;
  }

  els.sourceSelect.addEventListener("change", () => loadRefs(els.sourceSelect.value));
  els.versionSelect.addEventListener("change", () => selectVersion(els.versionSelect.value));
  await loadRefs("release");
}

// Fills the version dropdown with either the release tags or the branches,
// depending on the source picker, and selects the first entry.
async function loadRefs(kind) {
  els.sourceSelect.value = kind;
  els.versionSelect.innerHTML = "";
  els.versionSelect.disabled = true;

  let refs = [];
  try {
    refs = kind === "branch" ? await fetchBranchList() : await fetchTagList();
  } catch (error) {
    fail(error);
  }

  if (!refs.length) {
    if (kind === "release") {
      log("No released versions found - falling back to branches.");
      await loadRefs("branch");
      return;
    }
    els.release.textContent = "Couldn't list anything to install from GitHub.";
    els.release.classList.add("error");
    return;
  }

  refs.forEach((ref, index) => addVersionOption(ref, refLabel(kind, ref, index)));
  els.versionSelect.disabled = false;
  await selectVersion(refs[0]);
}

function refLabel(kind, ref, index) {
  if (kind === "release") return index === 0 ? `${ref} (latest release)` : ref;
  if (ref === DEFAULT_BRANCH) return `${ref} (development build, unreleased)`;
  return ref;
}

function addVersionOption(value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  els.versionSelect.appendChild(option);
}

async function selectVersion(value) {
  els.versionSelect.value = value;
  state.ref = value;
  state.bundle = null;
  els.release.classList.remove("error");
  els.release.textContent =
    els.sourceSelect.value === "release"
      ? `Source: release ${value}`
      : `Source: branch ${value} (development build, unreleased)`;

  try {
    state.firmwareUrl = await resolveFirmwareUrl();
  } catch (error) {
    state.firmwareUrl = null;
    fail(error);
  }
  els.uf2Version.textContent = parseVersion(state.firmwareUrl) || "unknown";

  loadDefaults();
}

// Firmware comes from the selected ref's own MICROPYTHON_VERSION pin. A ref
// cut before that file existed has none - fall back to the installer's
// hardcoded default rather than borrowing another ref's pin.
async function resolveFirmwareUrl() {
  try {
    return await fetchFirmwareUrl(state.ref);
  } catch (error) {
    log(`  note: ${error.message} - using the installer's default firmware (${parseVersion(DEFAULT_FIRMWARE_URL)})`);
    return DEFAULT_FIRMWARE_URL;
  }
}

function loadDefaults() {
  els.form.deviceName.value = FALLBACK_DEFAULTS.device.name;
  els.form.ledCount.value = FALLBACK_DEFAULTS.leds.count;
  els.form.ledPin.value = FALLBACK_DEFAULTS.leds.pin;
  els.form.apSsid.value = FALLBACK_DEFAULTS.network.ap.ssid;
  els.form.apPassword.value = FALLBACK_DEFAULTS.network.ap.password;
  els.form.segmentLength.value = FALLBACK_DEFAULTS.leds.segmenting.length;
  els.form.mqttPort.value = FALLBACK_DEFAULTS.mqtt.port;
  els.form.mqttBaseTopic.value = FALLBACK_DEFAULTS.mqtt.base_topic;
  els.form.mqttNtpHost.value = FALLBACK_DEFAULTS.mqtt.ntp_host;
  updateConfigValidity();
}

// Toggle a section's visibility off its driving checkbox (data-toggles="<id>").
els.form.querySelectorAll("[data-toggles]").forEach((toggle) => {
  const target = document.getElementById(toggle.dataset.toggles);
  const sync = () => {
    target.hidden = !toggle.checked;
  };
  toggle.addEventListener("change", sync);
  sync();
});

function setButtonLoading(button, isLoading) {
  button.classList.toggle("is-loading", isLoading);
  button.setAttribute("aria-busy", String(isLoading));
}

buttons.flash.addEventListener("click", async () => {
  buttons.flash.disabled = true;
  setButtonLoading(buttons.flash, true);
  setStepStatus("firmware", "pending");
  let pico = null;
  try {
    log("Requesting the board in BOOTSEL mode…");
    const device = await requestBootDevice();
    pico = new Picoboot(device);
    const openPromise = pico.open();
    openPromise.catch(() => {}); // avoid an unhandled rejection if we bail out on timeout below
    await withTimeout(
      openPromise,
      OPEN_TIMEOUT_MS,
      "timed out opening the board over USB - on Windows this usually means no WinUSB " +
        "driver is bound to the board's boot interface; use the drag-.uf2 fallback below instead"
    );

    if (!state.firmwareUrl) throw new Error("no firmware URL resolved for this version");

    log("Downloading firmware…");
    els.firmwareProgress.hidden = false;
    const uf2 = await fetchBinary(state.firmwareUrl, (received, total) => {
      els.firmwareProgress.value = total ? (received / total) * 50 : 0;
    });

    log("Writing flash…");
    await pico.flashUf2(uf2, (done, total) => {
      els.firmwareProgress.value = 50 + (done / total) * 50;
    });
    await pico.close();
    log("Done. The board is rebooting into MicroPython — give it ~5 seconds, then Connect.");
    setStepStatus("firmware", "success", "Flashed successfully.");
    completedSteps.add(1);
    setTimeout(() => goToStep(2), ADVANCE_DELAY_MS);
  } catch (error) {
    fail(error);
    setStepStatus("firmware", "error", error.message || String(error));
    if (pico) await pico.close();
    buttons.flash.disabled = false;
  } finally {
    setButtonLoading(buttons.flash, false);
  }
});

buttons.skipFirmware.addEventListener("click", () => {
  buttons.skipFirmware.disabled = true;
  setStepStatus("firmware", "success", "Skipped — MicroPython is already on this board.");
  completedSteps.add(1);
  if (currentStep === 1) setTimeout(() => goToStep(2), ADVANCE_DELAY_MS);
});

buttons.connect.addEventListener("click", async () => {
  buttons.connect.disabled = true;
  setButtonLoading(buttons.connect, true);
  setStepStatus("connect", "pending");
  try {
    log("Opening the serial port…");
    const port = await requestSerialPort();
    state.repl = new Repl(port);
    await state.repl.open();
    await sleep(200);
    log("Entering the MicroPython raw prompt…");
    await state.repl.enterRaw();
    log("Connected.");
    setStepStatus("connect", "success", "Connected.");
    completedSteps.add(2);
    setTimeout(() => goToStep(3), ADVANCE_DELAY_MS);
  } catch (error) {
    fail(error);
    setStepStatus("connect", "error", error.message || String(error));
    if (state.repl) {
      await state.repl.close();
      state.repl = null;
    }
    buttons.connect.disabled = false;
  } finally {
    setButtonLoading(buttons.connect, false);
  }
});

function isConfigValid() {
  if (!els.form.checkValidity()) return false;
  const mqttServer = els.form.mqttServer.value.trim();
  if (mqttServer) {
    const port = Number(els.form.mqttPort.value);
    if (!port || port < 1 || port > 65535) return false;
  }
  if (els.form.mqttSsl.checked && els.form.mqttCertValidate.checked) {
    const file = els.form.mqttCertFile.files[0];
    if (!file || file.size > CERT_MAX_BYTES) return false;
  }
  return true;
}

function updateConfigValidity() {
  buttons.continueConfig.disabled = !isConfigValid();
}

els.form.addEventListener("input", updateConfigValidity);
els.form.addEventListener("change", updateConfigValidity);

// Uses the raw REPL connection from step 2 directly - `network` is built
// into MicroPython itself, so this works even before the controller files
// are installed in step 4.
buttons.wifiScan.addEventListener("click", async () => {
  if (!state.repl) {
    fail(new Error("connect to the device (step 2) before scanning"));
    return;
  }
  buttons.wifiScan.disabled = true;
  setButtonLoading(buttons.wifiScan, true);
  try {
    log("Scanning for Wi-Fi networks…");
    const code =
      "import network\n" +
      "_w=network.WLAN(network.STA_IF)\n" +
      "_w.active(True)\n" +
      "for _n in sorted(set(n[0].decode() for n in _w.scan() if n[0])):\n" +
      " print(_n)\n";
    const output = await state.repl.exec(code, 15000);
    const ssids = output.split("\n").map((line) => line.trim()).filter(Boolean);
    const datalist = document.getElementById("wifi-ssid-options");
    datalist.innerHTML = "";
    ssids.forEach((ssid) => {
      const option = document.createElement("option");
      option.value = ssid;
      datalist.appendChild(option);
    });
    log(`Found ${ssids.length} network${ssids.length === 1 ? "" : "s"}.`);
  } catch (error) {
    fail(error);
  } finally {
    buttons.wifiScan.disabled = false;
    setButtonLoading(buttons.wifiScan, false);
  }
});

buttons.continueConfig.addEventListener("click", () => {
  if (!isConfigValid()) return;
  setStepStatus("config", "success", "Configuration looks good.");
  completedSteps.add(3);
  goToStep(4);
});

buttons.retryInstall.addEventListener("click", () => {
  installState = "idle";
  buttons.retryInstall.hidden = true;
  runInstall();
});

async function runInstall() {
  installState = "running";
  buttons.retryInstall.hidden = true;
  setStepStatus("install", "pending");
  setInstallLoading(true);
  els.installProgress.value = 0;
  const form = readForm();
  try {
    const certFile = await readCertFile();
    form.mqttCertificateName = certFile ? certFile.name : "";

    if (!state.bundle) {
      log(`Assembling the bundle from ${state.ref}…`);
      state.bundle = await fetchSource(state.ref, (done, total, path) => {
        log(`  ${done}/${total}  ${path}`);
      });
    }

    const fileCount = state.bundle.files.length + 1 + (certFile ? 1 : 0);
    log(`Installing ${fileCount} files…`);
    await pushBundle(state.repl, state.bundle, form, {
      certFile,
      onProgress: (done, total, path) => {
        els.installProgress.value = (done / total) * 100;
        if (path) log(`  ${done}/${total}  ${path}`);
      },
    });

    log("Rebooting the device…");
    await reboot(state.repl);
    await state.repl.close();
    log("Installed. The controller is starting up.");
    const guidance = postInstallGuidance(form);
    log(guidance);
    setInstallLoading(false);
    setStepStatus("install", "success", `Installed successfully. ${guidance}`);
    completedSteps.add(4);
    installState = "done";
    renderStepper();
  } catch (error) {
    fail(error);
    setInstallLoading(false);
    setStepStatus("install", "error", error.message || String(error));
    buttons.retryInstall.hidden = false;
    installState = "error";
  }
}

function postInstallGuidance(form) {
  if (form.defaultMode === "mqtt-ssl") {
    return (
      "Boot mode is mqtt-ssl — the Web UI/API don't start at all, so there's no " +
      "dashboard to open. Hold the device button ~5s to enter config mode and " +
      "switch it back if you need the dashboard."
    );
  }
  if (form.wifiSsid) {
    return (
      `Wi-Fi "${form.wifiSsid}" was configured — find the device's IP address ` +
      "on your router (or its connected-devices list) and open it in a browser " +
      "to reach the dashboard. If it can't join that network, it automatically " +
      `opens its own setup network ("${form.apSsid}") instead.`
    );
  }
  const passwordNote = form.apPassword ? ` (password: ${form.apPassword})` : " (open network, no password)";
  return (
    "No Wi-Fi was configured, so on this first boot the device starts up as " +
    "its own Wi-Fi access point instead of joining a network — that's " +
    `expected. Connect your phone or computer to "${form.apSsid}"${passwordNote}, ` +
    "then open http://192.168.4.1/ to finish setup."
  );
}

async function readCertFile() {
  const file = els.form.mqttCertFile.files[0];
  if (!file) return null;
  if (file.size > CERT_MAX_BYTES) {
    throw new Error(`certificate too large (${file.size} bytes, max ${CERT_MAX_BYTES})`);
  }
  const buffer = await file.arrayBuffer();
  return { name: file.name.split(/[\\/]/).pop(), size: buffer.byteLength, b64: toBase64(buffer) };
}

// Certificate dropzone: click-to-browse and drag & drop both funnel into the
// same hidden <input type="file"> that readCertFile()/isConfigValid() read.
const certDropzone = document.getElementById("cert-dropzone");
const certFileInput = document.getElementById("mqtt-cert-file-input");
const certFilename = document.getElementById("cert-filename");

function updateCertFilenameDisplay() {
  const file = certFileInput.files[0];
  certFilename.hidden = !file;
  certFilename.textContent = file ? file.name : "";
}

certDropzone.addEventListener("click", () => certFileInput.click());
certDropzone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    certFileInput.click();
  }
});
["dragenter", "dragover"].forEach((eventName) => {
  certDropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    certDropzone.classList.add("dragover");
  });
});
["dragleave", "dragend", "drop"].forEach((eventName) => {
  certDropzone.addEventListener(eventName, () => certDropzone.classList.remove("dragover"));
});
certDropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  if (!event.dataTransfer.files[0]) return;
  certFileInput.files = event.dataTransfer.files;
  updateCertFilenameDisplay();
  updateConfigValidity();
});
certFileInput.addEventListener("change", updateCertFilenameDisplay);

function readForm() {
  const data = new FormData(els.form);
  const bool = (name) => data.get(name) === "on";
  return {
    deviceName: data.get("deviceName") || "PicoController",
    wifiSsid: data.get("wifiSsid") || "",
    wifiPassword: data.get("wifiPassword") || "",
    ledCount: Number(data.get("ledCount")) || 144,
    ledPin: Number(data.get("ledPin")) || 0,
    watchdog: bool("watchdog"),
    apSsid: data.get("apSsid") || "PicoController",
    apPassword: data.get("apPassword") || "",
    ledsOnAfterBoot: bool("ledsOnAfterBoot"),
    segmentingEnabled: bool("segmentingEnabled"),
    segmentLength: Number(data.get("segmentLength")) || 2,
    mqttEnabled: bool("mqttEnabled"),
    mqttServer: data.get("mqttServer") || "",
    mqttPort: Number(data.get("mqttPort")) || 1883,
    mqttUser: data.get("mqttUser") || "",
    mqttPassword: data.get("mqttPassword") || "",
    mqttBaseTopic: data.get("mqttBaseTopic") || "controller/led/1",
    mqttSingleTopic: bool("mqttSingleTopic"),
    mqttSsl: bool("mqttSsl"),
    mqttNtpHost: data.get("mqttNtpHost") || "pool.ntp.org",
    mqttCertValidate: bool("mqttCertValidate"),
    buttonEnabled: bool("buttonEnabled"),
    irEnabled: bool("irEnabled"),
    wifiAccess: bool("wifiAccess"),
    defaultMode: data.get("defaultMode") || "normal",
    loggingEnabled: bool("loggingEnabled"),
    loggingLevel: data.get("loggingLevel") || "info",
  };
}

init();
