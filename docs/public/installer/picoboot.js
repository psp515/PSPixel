import { parseUf2 } from "./uf2.js";
import { USB_PRODUCT_ID, USB_VENDOR_ID } from "./const.js";

const MAGIC = 0x431fd10b;
const IF_RESET = 0x41;

const PC_EXCLUSIVE_ACCESS = 0x01;
const PC_REBOOT = 0x02;
const PC_FLASH_ERASE = 0x03;
const PC_WRITE = 0x05;
const PC_EXIT_XIP = 0x06;

const SECTOR = 4096;

export function webusbSupported() {
  return typeof navigator !== "undefined" && "usb" in navigator;
}

export async function requestBootDevice() {
  return navigator.usb.requestDevice({
    filters: [{ vendorId: USB_VENDOR_ID, productId: USB_PRODUCT_ID }],
  });
}

export class Picoboot {
  constructor(device) {
    this.device = device;
    this.token = 1;
  }

  async open() {
    await this.device.open();
    if (this.device.configuration === null) await this.device.selectConfiguration(1);

    let iface = null;
    for (const candidate of this.device.configuration.interfaces) {
      const alt = candidate.alternate;
      if (alt.interfaceClass === 0xff && alt.endpoints.length >= 2) {
        iface = candidate;
        break;
      }
    }
    if (!iface) throw new Error("PICOBOOT interface not found");

    this.interfaceNumber = iface.interfaceNumber;
    await this.device.claimInterface(this.interfaceNumber);

    for (const ep of iface.alternate.endpoints) {
      if (ep.direction === "in") this.epIn = ep.endpointNumber;
      if (ep.direction === "out") this.epOut = ep.endpointNumber;
    }

    await this.device.controlTransferOut({
      requestType: "vendor",
      recipient: "interface",
      request: IF_RESET,
      value: 0,
      index: this.interfaceNumber,
    });
  }

  async close() {
    try {
      await this.device.close();
    } catch {
      /* already gone after reboot */
    }
  }

  _packet(cmdId, args, transferLength) {
    const buffer = new ArrayBuffer(32);
    const view = new DataView(buffer);
    view.setUint32(0, MAGIC, true);
    view.setUint32(4, this.token++, true);
    view.setUint8(8, cmdId);
    view.setUint8(9, args.length);
    view.setUint32(12, transferLength, true);
    new Uint8Array(buffer, 16, 16).set(args);
    return buffer;
  }

  async _cmd(cmdId, args = new Uint8Array(0), data = null) {
    const transferLength = data ? data.length : 0;
    await this.device.transferOut(this.epOut, this._packet(cmdId, args, transferLength));
    if (data) await this.device.transferOut(this.epOut, data);
    // status handshake: bootrom replies with a zero-length IN packet
    await this.device.transferIn(this.epIn, 1);
  }

  _addrSize(addr, size) {
    const args = new Uint8Array(8);
    new DataView(args.buffer).setUint32(0, addr, true);
    new DataView(args.buffer).setUint32(4, size, true);
    return args;
  }

  async flashUf2(buffer, onProgress = () => {}) {
    const runs = parseUf2(buffer);
    await this._cmd(PC_EXCLUSIVE_ACCESS, Uint8Array.of(1));
    await this._cmd(PC_EXIT_XIP);

    const total = runs.reduce((sum, run) => sum + run.bytes.length, 0);
    let done = 0;

    for (const run of runs) {
      const start = run.addr & ~(SECTOR - 1);
      const eraseSize = Math.ceil((run.addr - start + run.bytes.length) / SECTOR) * SECTOR;
      await this._cmd(PC_FLASH_ERASE, this._addrSize(start, eraseSize));

      for (let offset = 0; offset < run.bytes.length; offset += SECTOR) {
        const chunk = run.bytes.subarray(offset, offset + SECTOR);
        await this._cmd(PC_WRITE, this._addrSize(run.addr + offset, chunk.length), chunk);
        done += chunk.length;
        onProgress(done, total);
      }
    }

    const reboot = new Uint8Array(12); // pc=0, sp=0 -> normal boot from flash
    new DataView(reboot.buffer).setUint32(8, 500, true);
    await this._cmd(PC_REBOOT, reboot);
  }
}
