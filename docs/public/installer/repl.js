import { USB_VENDOR_ID } from "./const.js";
import { fromBase64, sha256Hex, toBase64 } from "./net.js";

// Certificate names become a device path (certs/<name>) and a Python string
// literal - keep them to a plain basename charset, no ".", ".." or traversal.
export function isValidCertName(name) {
  return /^[A-Za-z0-9._-]{1,64}$/.test(name) && name !== "." && name !== "..";
}

export function serialSupported() {
  return typeof navigator !== "undefined" && "serial" in navigator;
}

export async function requestSerialPort() {
  return navigator.serial.requestPort({ filters: [{ usbVendorId: USB_VENDOR_ID }] });
}

const encoder = new TextEncoder();
const decoder = new TextDecoder();

export class Repl {
  constructor(port) {
    this.port = port;
    this.buffer = "";
  }

  async open() {
    try {
      await this.port.open({ baudRate: 115200 });
    } catch (error) {
      throw new Error(
        `couldn't open the serial port (${error.message}) - if you just flashed or ` +
          "rebooted the board, wait a few seconds and try again; also check no other " +
          "program (Thonny, Arduino IDE, another browser tab) already has this port open"
      );
    }
    this.reader = this.port.readable.getReader();
    this.writer = this.port.writable.getWriter();
    this._pump();
  }

  // Safe to call even if open() never fully succeeded (e.g. port.open()
  // itself threw, so reader/writer were never assigned) - a failed open()
  // still holds the port until this runs, so skipping it on error blocks
  // every retry with the same "Failed to open serial port" until the page
  // reloads.
  async close() {
    try {
      await this.reader?.cancel();
    } catch {
      /* ignore */
    }
    try {
      this.writer?.releaseLock();
    } catch {
      /* ignore */
    }
    try {
      await this.port.close();
    } catch {
      /* ignore */
    }
  }

  async _pump() {
    try {
      for (;;) {
        const { value, done } = await this.reader.read();
        if (done) break;
        this.buffer += decoder.decode(value, { stream: true });
      }
    } catch {
      /* port closed */
    }
  }

  async _write(text) {
    await this.writer.write(encoder.encode(text));
  }

  async _waitFor(token, timeoutMs = 5000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const index = this.buffer.indexOf(token);
      if (index !== -1) {
        const consumed = this.buffer.slice(0, index);
        this.buffer = this.buffer.slice(index + token.length);
        return consumed;
      }
      await sleep(20);
    }
    throw new Error(`timed out waiting for ${JSON.stringify(token)}`);
  }

  async enterRaw() {
    this.buffer = "";
    await this._write("\r\x03\x03");
    await sleep(120);
    this.buffer = "";
    await this._write("\r\x01");
    await this._waitFor("raw REPL; CTRL-B to exit\r\n>");
  }

  async exitRaw() {
    await this._write("\r\x02");
  }

  async exec(code, timeoutMs = 10000) {
    this.buffer = "";
    await this._write(code);
    await this._write("\x04");
    await this._waitFor("OK", 4000);
    const stdout = await this._waitFor("\x04", timeoutMs);
    const stderr = await this._waitFor("\x04", timeoutMs);
    await this._waitFor(">", 4000);
    if (stderr.trim()) throw new Error(stderr.trim());
    return stdout;
  }
}

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function pushBundle(
  repl,
  bundle,
  form,
  { onProgress = () => {}, verify = true, certFile = null } = {}
) {
  await repl.exec("import os, ubinascii");

  const dirs = certFile ? [...bundle.dirs, "certs"] : bundle.dirs;
  const dirList = dirs.map((d) => JSON.stringify(d)).join(",");
  await repl.exec(
    `for _d in [${dirList}]:\n try:\n  os.mkdir(_d)\n except OSError:\n  pass\n`
  );

  const configBytes = new TextEncoder().encode(configJson(form));

  const files = bundle.files.slice();
  files.push({ path: "config.json", b64: toBase64(configBytes.buffer) });
  if (certFile) {
    if (!isValidCertName(certFile.name)) {
      throw new Error(`invalid certificate filename: ${certFile.name}`);
    }
    files.push({ path: `certs/${certFile.name}`, b64: certFile.b64 });
  }

  await repl.exec("import hashlib");

  let index = 0;
  for (const file of files) {
    onProgress(index, files.length, file.path);
    await repl.exec(`_f=open(${JSON.stringify(file.path)},'wb')`);
    for (const chunk of splitB64(file.b64, 1024)) {
      await repl.exec(`_f.write(ubinascii.a2b_base64(${JSON.stringify(chunk)}))`);
    }
    await repl.exec("_f.close()");

    if (verify) {
      const expected = await sha256Hex(fromBase64(file.b64));
      const actual = (
        await repl.exec(
          `print(ubinascii.hexlify(hashlib.sha256(open(${JSON.stringify(file.path)},'rb').read()).digest()).decode())`
        )
      ).trim();
      if (actual !== expected) {
        throw new Error(`${file.path}: on-device hash ${actual}, expected ${expected}`);
      }
    }
    index += 1;
  }
  onProgress(files.length, files.length, "done");
}

export async function reboot(repl) {
  await repl.exec("import machine");
  await repl._write("machine.reset()\r\x04");
}

export function splitB64(b64, rawChunkBytes) {
  // base64 length must stay a multiple of 4 per write, so each chunk lands on
  // a 3-raw-byte boundary; rawChunkBytes needn't itself be a multiple of 3.
  const step = Math.floor(rawChunkBytes / 3) * 4;
  const parts = [];
  for (let offset = 0; offset < b64.length; offset += step) {
    parts.push(b64.slice(offset, offset + step));
  }
  return parts;
}

export function configJson(form) {
  const config = {
    device: { name: form.deviceName },
    network: {
      wifi: { ssid: form.wifiSsid, password: form.wifiPassword },
      ap: { ssid: form.apSsid, password: form.apPassword },
    },
    leds: {
      count: form.ledCount,
      pin: form.ledPin,
      on_after_boot: form.ledsOnAfterBoot,
      segmenting: { enabled: form.segmentingEnabled, length: form.segmentLength },
    },
    mqtt: {
      enabled: form.mqttEnabled,
      server: form.mqttServer,
      port: form.mqttPort,
      user: form.mqttUser,
      password: form.mqttPassword,
      base_topic: form.mqttBaseTopic,
      use_single_topic_for_state_update: form.mqttSingleTopic,
      ssl: form.mqttSsl,
      ntp_host: form.mqttNtpHost,
      certificate: { validate: form.mqttCertValidate, name: form.mqttCertificateName },
    },
    button: { enabled: form.buttonEnabled },
    ir: { enabled: form.irEnabled },
    webapi: { wifi_access: form.wifiAccess },
    system: { default_mode: form.defaultMode },
    logging: { enabled: form.loggingEnabled, level: form.loggingLevel },
    watchdog: { enabled: form.watchdog },
  };
  return JSON.stringify(config);
}
