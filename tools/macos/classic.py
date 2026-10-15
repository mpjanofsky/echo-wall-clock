#!/usr/bin/env python3
"""Bluetooth Classic recon for the Echo Wall Clock (macOS, IOBluetooth).

The clock shows up in System Settings as "EchoWallClk..." but never in the
BLE scans, so it is discoverable over Bluetooth Classic (BR/EDR). This:

  1. runs a Classic inquiry and lists what it finds,
  2. for the clock (name contains --match), runs an SDP query and dumps every
     service record: names, service-class UUIDs, RFCOMM channels, L2CAP PSMs.

Read-only: an SDP query needs no pairing and sends nothing to the app layer.

    python classic.py [--seconds 15] [--match wallclk]
"""

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import objc
from Foundation import NSDate, NSObject, NSRunLoop
import IOBluetooth

LOG_DIR = Path(__file__).parent / "logs"


def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))


class InquiryDelegate(NSObject):
    def init(self):
        self = objc.super(InquiryDelegate, self).init()
        self.done = False
        return self

    def deviceInquiryDeviceFound_device_(self, sender, device):
        print(f"  found {device.addressString()}  {device.name()!r}  rssi={device.rawRSSI()}")

    def deviceInquiryComplete_error_aborted_(self, sender, error, aborted):
        self.done = True


class SDPDelegate(NSObject):
    def init(self):
        self = objc.super(SDPDelegate, self).init()
        self.status = None
        return self

    def sdpQueryComplete_status_(self, device, status):
        self.status = status


def element_value(el):
    """Turn an IOBluetoothSDPDataElement into plain Python, recursively."""
    if el is None:
        return None
    t = el.getTypeDescriptor()
    # 0 nil, 1 uint, 2 int, 3 UUID, 4 string, 5 bool, 6 seq, 7 alt, 8 URL
    if t == 3:
        return {"uuid": str(el.getUUIDValue())}
    if t in (4, 8):
        return el.getStringValue()
    if t in (6, 7):
        return [element_value(e) for e in el.getArrayValue()]
    if t in (1, 2, 5):
        n = el.getNumberValue()
        return int(n) if n is not None else None
    return None


def dump_record(rec):
    out = {"name": rec.getServiceName()}
    status, ch = rec.getRFCOMMChannelID_(None)
    if status == 0:
        out["rfcomm_channel"] = int(ch)
    status, psm = rec.getL2CAPPSM_(None)
    if status == 0:
        out["l2cap_psm"] = int(psm)
    attrs = {}
    for key, el in (rec.attributes() or {}).items():
        attrs[f"0x{int(key):04x}"] = element_value(el)
    out["attributes"] = attrs
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seconds", type=int, default=15, help="inquiry length")
    p.add_argument("--match", default="wallclk", help="case-insensitive name fragment for the clock")
    args = p.parse_args()

    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-classic.json"

    print(f"Classic inquiry for {args.seconds}s (clock should be flashing amber)...")
    delegate = InquiryDelegate.alloc().init()
    inquiry = IOBluetooth.IOBluetoothDeviceInquiry.inquiryWithDelegate_(delegate)
    inquiry.setInquiryLength_(args.seconds)
    inquiry.setUpdateNewDeviceNames_(True)
    inquiry.start()
    deadline = time.time() + args.seconds + 10
    while not delegate.done and time.time() < deadline:
        pump(0.5)
    inquiry.stop()

    found = list(inquiry.foundDevices() or [])
    result = {"devices": [], "clock": None}
    clock = None
    for d in found:
        info = {
            "address": d.addressString(),
            "name": d.name(),
            "class_of_device": f"0x{d.classOfDevice():06x}",
            "rssi": d.rawRSSI(),
            "paired": bool(d.isPaired()),
        }
        result["devices"].append(info)
        if d.name() and args.match.lower() in d.name().lower():
            clock = d

    if clock is None:
        print(f"\nNo device with {args.match!r} in its name. Saw {len(found)} device(s).")
        log_path.write_text(json.dumps(result, indent=2, default=str))
        print(f"Log: {log_path}")
        return

    print(f"\nClock: {clock.name()}  address={clock.addressString()}  class=0x{clock.classOfDevice():06x}")
    print("Running SDP query (lists the services it offers)...")
    sdp = SDPDelegate.alloc().init()
    clock.performSDPQuery_(sdp)
    deadline = time.time() + 30
    while sdp.status is None and time.time() < deadline:
        pump(0.5)
    print(f"SDP status: {sdp.status}")

    records = [dump_record(r) for r in (clock.services() or [])]
    result["clock"] = {"address": clock.addressString(), "name": clock.name(), "sdp_status": sdp.status, "services": records}
    for r in records:
        uuids = r["attributes"].get("0x0001")
        print(f"\n  Service: {r['name']!r}")
        if "rfcomm_channel" in r:
            print(f"    RFCOMM channel: {r['rfcomm_channel']}")
        if "l2cap_psm" in r:
            print(f"    L2CAP PSM: {r['l2cap_psm']}")
        print(f"    class UUIDs: {uuids}")

    log_path.write_text(json.dumps(result, indent=2, default=str))
    print(f"\nLog: {log_path}")


if __name__ == "__main__":
    main()
