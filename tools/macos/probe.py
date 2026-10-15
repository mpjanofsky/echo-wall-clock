#!/usr/bin/env python3
"""Echo Wall Clock BLE probe.

Read-only reconnaissance for the Echo Wall Clock (FCC ID UUU-8459).
It never writes to a characteristic; the only thing it changes on the clock
is enabling notifications, which is what any central does to listen.

    python probe.py scan [--seconds 20] [--all]
    python probe.py watch [--baseline 15] [--seconds 45]
    python probe.py probe <address> [--listen 30] [--pair]

Everything seen is also appended to logs/<timestamp>-<command>.jsonl so we
can diff runs later.
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

# Alexa Gadgets Toolkit service, per Amazon's published BLE settings.
AGT_SERVICE = "0000fe03-0000-1000-8000-00805f9b34fb"
# Bluetooth SIG company identifier assigned to Amazon.com Services.
AMAZON_COMPANY_ID = 0x0171

LOG_DIR = Path(__file__).parent / "logs"


class Log:
    def __init__(self, command):
        LOG_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = LOG_DIR / f"{stamp}-{command}.jsonl"
        self._f = self.path.open("a")

    def write(self, kind, **data):
        data = {"t": time.time(), "kind": kind, **data}
        self._f.write(json.dumps(data, default=str) + "\n")
        self._f.flush()


def hexs(b):
    return bytes(b).hex(" ") if b is not None else None


def looks_like_clock(adv, name):
    name = (name or adv.local_name or "").lower()
    return (
        AGT_SERVICE in [u.lower() for u in adv.service_uuids]
        or AGT_SERVICE in {u.lower() for u in adv.service_data}
        or AMAZON_COMPANY_ID in adv.manufacturer_data
        or "echo" in name
        or "clock" in name
    )


async def cmd_scan(args):
    log = Log("scan")
    seen = {}

    def on_adv(device, adv):
        hit = looks_like_clock(adv, device.name)
        log.write(
            "adv",
            address=device.address,
            name=device.name,
            local_name=adv.local_name,
            rssi=adv.rssi,
            tx_power=adv.tx_power,
            service_uuids=adv.service_uuids,
            service_data={k: hexs(v) for k, v in adv.service_data.items()},
            manufacturer_data={f"0x{k:04x}": hexs(v) for k, v in adv.manufacturer_data.items()},
            candidate=hit,
        )
        if not (hit or args.all):
            return
        key = (device.address, hit)
        first = key not in seen
        seen[key] = (device, adv)
        if first:
            tag = "** CANDIDATE **" if hit else ""
            print(f"\n{tag} {device.address}  name={device.name or adv.local_name!r}  rssi={adv.rssi}")
            for u in adv.service_uuids:
                print(f"    service uuid: {u}")
            for k, v in adv.service_data.items():
                print(f"    service data {k}: {hexs(v)}")
            for k, v in adv.manufacturer_data.items():
                who = " (Amazon)" if k == AMAZON_COMPANY_ID else ""
                print(f"    mfr data 0x{k:04x}{who}: {hexs(v)}")

    print(f"Scanning for {args.seconds}s... (put the clock in pairing mode now)")
    async with BleakScanner(detection_callback=on_adv):
        await asyncio.sleep(args.seconds)

    candidates = [d for (addr, hit), (d, _) in seen.items() if hit]
    print(f"\nDone. {len(candidates)} candidate(s). Log: {log.path}")
    for d in candidates:
        print(f"  python probe.py probe {d.address}")


async def cmd_watch(args):
    """Learn the background devices first, then report anything that shows up later."""
    log = Log("watch")
    start = time.time()
    seen = {}  # address -> [count, first_t, last_adv]
    baseline_done = False

    def on_adv(device, adv):
        now = time.time() - start
        entry = seen.get(device.address)
        log.write(
            "adv",
            address=device.address,
            name=device.name,
            local_name=adv.local_name,
            rssi=adv.rssi,
            service_uuids=adv.service_uuids,
            service_data={k: hexs(v) for k, v in adv.service_data.items()},
            manufacturer_data={f"0x{k:04x}": hexs(v) for k, v in adv.manufacturer_data.items()},
            baseline=not baseline_done,
        )
        if entry is None:
            seen[device.address] = [1, now, adv, not baseline_done]
            if baseline_done and adv.rssi > args.min_rssi:
                empty = not (adv.local_name or adv.service_uuids or adv.manufacturer_data or adv.service_data)
                print(
                    f"[{now:5.1f}s] NEW {device.address}  rssi={adv.rssi}  name={device.name or adv.local_name!r}"
                    f"{'  (empty advertisement)' if empty else ''}"
                )
                for u in adv.service_uuids:
                    print(f"          service uuid: {u}")
                for k, v in adv.service_data.items():
                    print(f"          service data {k}: {hexs(v)}")
                for k, v in adv.manufacturer_data.items():
                    print(f"          mfr data 0x{k:04x}: {hexs(v)}")
        else:
            entry[0] += 1
            entry[2] = adv

    async with BleakScanner(detection_callback=on_adv):
        print(f"Learning background devices for {args.baseline:.0f}s -- do NOT start pairing yet...")
        await asyncio.sleep(args.baseline)
        baseline_done = True
        print(f"Baseline: {len(seen)} devices. >>> START PAIRING MODE NOW <<<  (watching {args.seconds:.0f}s)")
        await asyncio.sleep(args.seconds)

    new = {a: e for a, e in seen.items() if not e[3] and e[2].rssi > args.min_rssi}
    print(f"\nDevices that appeared after baseline (rssi > {args.min_rssi}):")
    for addr, (count, first, adv, _) in sorted(new.items(), key=lambda kv: -kv[1][0]):
        print(f"  {count:4d} pkts  first at {first:5.1f}s  rssi={adv.rssi}  {addr}  name={adv.local_name!r}")
    print(f"Log: {log.path}")


def describe_agt_packet(data):
    """Best-effort labelling of the first Alexa Gadget packet (Protocol Version)."""
    if len(data) >= 4 and data[0] == 0xFE and data[1] == 0x03:
        return f"Alexa Gadget Protocol Version packet: v{data[2]}.{data[3]}, rest={hexs(data[4:])}"
    return None


async def cmd_probe(args):
    log = Log("probe")
    print(f"Looking for {args.address} for up to {args.wait:.0f}s (start pairing mode now)...")
    device = await BleakScanner.find_device_by_address(args.address, timeout=args.wait)
    if device is None:
        sys.exit("Not found. Is the clock in pairing mode and unpaired from the Echo?")

    def on_disconnect(_client):
        print("!! Disconnected by peer")
        log.write("disconnected")

    async with BleakClient(device, disconnected_callback=on_disconnect, pair=args.pair, timeout=30) as client:
        print(f"Connected. MTU={client.mtu_size}")
        log.write("connected", address=device.address, mtu=client.mtu_size)

        notifiable = []
        for service in client.services:
            print(f"\nService {service.uuid}  {service.description}")
            log.write("service", uuid=service.uuid, description=service.description)
            for ch in service.characteristics:
                props = ",".join(ch.properties)
                print(f"  Char {ch.uuid}  [{props}]  handle={ch.handle}  {ch.description}")
                entry = {"service": service.uuid, "uuid": ch.uuid, "handle": ch.handle, "properties": ch.properties}
                if "read" in ch.properties:
                    try:
                        value = await client.read_gatt_char(ch)
                        entry["value"] = hexs(value)
                        text = bytes(value).decode("utf-8", "replace") if value else ""
                        print(f"      read: {hexs(value)}  {text!r}")
                    except (BleakError, OSError) as e:
                        entry["read_error"] = str(e)
                        print(f"      read failed: {e}")
                for desc in ch.descriptors:
                    print(f"      desc {desc.uuid} handle={desc.handle}")
                log.write("characteristic", **entry)
                if "notify" in ch.properties or "indicate" in ch.properties:
                    notifiable.append(ch)

        def make_handler(ch):
            def handler(_sender, data):
                label = describe_agt_packet(data)
                print(f"<< {ch.uuid} ({len(data)} bytes): {hexs(data)}")
                if label:
                    print(f"   {label}")
                log.write("notify", uuid=ch.uuid, data=hexs(data), label=label)
            return handler

        for ch in notifiable:
            try:
                await client.start_notify(ch, make_handler(ch))
                print(f"\nSubscribed to {ch.uuid}")
            except (BleakError, OSError) as e:
                print(f"\nSubscribe to {ch.uuid} failed: {e}")
                log.write("subscribe_error", uuid=ch.uuid, error=str(e))

        print(f"\nListening for {args.listen}s (Ctrl-C to stop early)...")
        try:
            await asyncio.sleep(args.listen)
        except asyncio.CancelledError:
            pass

    print(f"\nDone. Log: {log.path}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scan", help="find the clock and dump its advertisement")
    s.add_argument("--seconds", type=float, default=20)
    s.add_argument("--all", action="store_true", help="print every device, not just candidates")

    w = sub.add_parser("watch", help="learn background devices, then report anything new (trigger pairing mid-scan)")
    w.add_argument("--baseline", type=float, default=15)
    w.add_argument("--seconds", type=float, default=45)
    w.add_argument("--min-rssi", type=int, default=-85, help="ignore far-away devices")

    pr = sub.add_parser("probe", help="connect, list GATT, read what's readable, listen to notifications")
    pr.add_argument("address", help="address/UUID printed by scan")
    pr.add_argument("--wait", type=float, default=60, help="seconds to wait for the device to advertise")
    pr.add_argument("--listen", type=float, default=30, help="seconds to listen for notifications")
    pr.add_argument("--pair", action="store_true", help="request pairing on connect (ignored on macOS, which pairs on demand)")

    args = p.parse_args()
    try:
        commands = {"scan": cmd_scan, "watch": cmd_watch, "probe": cmd_probe}
        asyncio.run(commands[args.command](args))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
