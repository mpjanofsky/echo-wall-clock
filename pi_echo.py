#!/usr/bin/env python3
"""Act as the Echo toward the real Wall Clock, from Linux/BlueZ (the Pi).

    sudo python3 pi_echo.py --address XX:XX:XX:XX:XX:XX [--listen 30]

Finds the clock (it must be flashing amber unless already paired here),
pairs with Just Works, opens RFCOMM channel 4, sends the exact Discover a
real Echo sends, and logs/decodes everything the clock says back.
"""

import argparse
import json
import os
import socket
import struct
import threading
import random
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

import agt

BLUEZ = "org.bluez"
AGENT_PATH = "/piecho/agent"
DATA_CHANNEL = 4
SOL_BLUETOOTH, BT_SECURITY, BT_SECURITY_MEDIUM = 274, 4, 2
LOG_DIR = Path(__file__).parent / "logs"


class Agent(dbus.service.Object):
    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        print(f"[agent] confirm {passkey:06d} -> accept")

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        pass

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        pass

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Cancel(self):
        print("[agent] cancel")

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Release(self):
        pass


class SppProfile(dbus.service.Object):
    """Just logs it if the clock opens our SPP channel when calling back."""

    def __init__(self, bus, path, log):
        super().__init__(bus, path)
        self.log = log

    @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
    def NewConnection(self, device, fd, props):
        sock = socket.socket(fileno=fd.take())
        sock.setblocking(True)
        print(f"\n[SPP] clock opened our serial port: {device}")
        self.log("spp_inbound", device=str(device))

        def reader():
            while True:
                try:
                    data = sock.recv(4096)
                except OSError:
                    break
                if not data:
                    break
                print(f"[SPP] << {data.hex(' ')}")
                self.log("spp_rx", data=data.hex(" "))
        threading.Thread(target=reader, daemon=True).start()

    @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
    def RequestDisconnection(self, device):
        pass

    @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
    def Release(self):
        pass


def run_until(loop_ctx, predicate, timeout):
    end = time.time() + timeout
    while time.time() < end and not predicate():
        loop_ctx.iteration(False)
        time.sleep(0.05)
    return predicate()


def ensure_paired(bus, address, timeout):
    ctx = GLib.MainContext.default()
    dev_path = f"/org/bluez/hci0/dev_{address.replace(':', '_')}"
    adapter = dbus.Interface(bus.get_object(BLUEZ, "/org/bluez/hci0"), "org.bluez.Adapter1")
    props = lambda path: dbus.Interface(bus.get_object(BLUEZ, path), "org.freedesktop.DBus.Properties")

    def known():
        try:
            props(dev_path).Get("org.bluez.Device1", "Address")
            return True
        except dbus.DBusException:
            return False

    if known() and props(dev_path).Get("org.bluez.Device1", "Paired"):
        print("Already paired.")
        return dev_path

    print(f"Searching for {address} (clock should be flashing amber)...")
    try:
        adapter.SetDiscoveryFilter({"Transport": "bredr"})
    except dbus.DBusException:
        pass
    adapter.StartDiscovery()
    found = run_until(ctx, known, timeout)
    adapter.StopDiscovery()
    if not found:
        raise SystemExit("Clock not found. Is it flashing amber?")

    print("Pairing...")
    result = {}
    dbus.Interface(bus.get_object(BLUEZ, dev_path), "org.bluez.Device1").Pair(
        reply_handler=lambda: result.setdefault("ok", True),
        error_handler=lambda e: result.setdefault("err", str(e)),
        timeout=60,
    )
    run_until(ctx, lambda: result, 65)
    if "err" in result and "AlreadyExists" not in result["err"]:
        raise SystemExit(f"Pairing failed: {result['err']}")
    props(dev_path).Set("org.bluez.Device1", "Trusted", True)
    print("Paired.")
    return dev_path


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--address", required=True, help="the clock's Bluetooth address")
    p.add_argument("--listen", type=float, default=30)
    p.add_argument("--search", type=float, default=60, help="seconds to keep trying to connect")
    p.add_argument("--fresh", action="store_true", help="forget any existing pairing first, like a new Echo")
    p.add_argument("--tz", default="America/New_York", help="time zone for timeinfo / timer end times")
    p.add_argument("--no-sync", action="store_true", help="don't send timeinfo after discovery")
    p.add_argument("--timer", type=float, action="append", default=[], help="start a timer of N minutes (repeatable)")
    p.add_argument("--cancel", action="append", default=[], help="cancel a timer by token (repeatable)")
    p.add_argument("--control", help="FIFO path; each line written to it runs as a step (interactive tests)")
    p.add_argument("--step", action="append", default=[], metavar="SECS:ACTION",
                   help="scripted action SECS after discovery (see run_step); repeatable")
    p.add_argument("--state", action="append", default=[], metavar="SECS:NAME=VALUE",
                   help="send a StateUpdate SECS after discovery, e.g. 65:timers=active (repeatable)")
    args = p.parse_args()

    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-piecho.jsonl"
    log_f = log_path.open("a")

    def log(kind, **data):
        log_f.write(json.dumps({"t": time.time(), "kind": kind, **data}, default=str) + "\n")
        log_f.flush()

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    Agent(bus, AGENT_PATH)
    mgr = dbus.Interface(bus.get_object(BLUEZ, "/org/bluez"), "org.bluez.AgentManager1")
    mgr.RegisterAgent(AGENT_PATH, "NoInputNoOutput")
    mgr.RequestDefaultAgent(AGENT_PATH)

    # Real Echos are always connectable: after pairing the clock calls back (SDP search for SPP 0x1101).
    adapter_props = dbus.Interface(bus.get_object(BLUEZ, "/org/bluez/hci0"), "org.freedesktop.DBus.Properties")
    adapter_props.Set("org.bluez.Adapter1", "Pairable", True)
    adapter_props.Set("org.bluez.Adapter1", "Connectable", True)
    spp = SppProfile(bus, "/piecho/spp", log)
    dbus.Interface(bus.get_object(BLUEZ, "/org/bluez"), "org.bluez.ProfileManager1").RegisterProfile(
        "/piecho/spp", "00001101-0000-1000-8000-00805f9b34fb",
        {"Name": "Serial Port", "Role": "server", "Channel": dbus.UInt16(1),
         "RequireAuthentication": False, "RequireAuthorization": False})
    print("Pi is connectable and offers SPP (0x1101) on RFCOMM 1.")

    if args.fresh:
        try:
            adapter = dbus.Interface(bus.get_object(BLUEZ, "/org/bluez/hci0"), "org.bluez.Adapter1")
            adapter.RemoveDevice(f"/org/bluez/hci0/dev_{args.address.replace(':', '_')}")
            print("Removed old pairing.")
        except dbus.DBusException:
            pass

    # Like the Echo: one connection that pairs (SSP Just Works) and opens RFCOMM straight away.
    # connect() runs in a thread so the GLib loop can service the pairing agent meanwhile.
    print(f"Connecting RFCOMM channel {DATA_CHANNEL} with encryption (clock must be flashing)...")
    result = {}

    def connect():
        end = time.time() + args.search
        while time.time() < end:
            s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            s.setsockopt(SOL_BLUETOOTH, BT_SECURITY, struct.pack("BB", BT_SECURITY_MEDIUM, 0))
            s.settimeout(40)
            try:
                s.connect((args.address, DATA_CHANNEL))
                result["sock"] = s
                return
            except OSError as e:
                result["last_error"] = str(e)
                print(f"  connect failed ({e}); retrying...")
                s.close()
                time.sleep(1)
        result["done"] = True

    threading.Thread(target=connect, daemon=True).start()
    ctx = GLib.MainContext.default()
    while "sock" not in result and "done" not in result:
        ctx.iteration(False)
        time.sleep(0.02)
    if "sock" not in result:
        raise SystemExit(f"Could not connect: {result.get('last_error')}")
    sock = result["sock"]
    print("Connected (paired + encrypted).")
    log("connect", channel=DATA_CHANNEL)

    framer, deframer = agt.Framer(), agt.Deframer()
    frame = framer.frame(agt.discover())
    print(f">> Discover: {frame.hex(' ')}")
    sock.sendall(frame)
    log("tx", what="Alexa.Discovery.Discover", data=frame.hex(" "))

    def now_iso():
        return datetime.now(ZoneInfo(args.tz)).isoformat(timespec="seconds")

    def send(what, payload):
        frame = framer.frame(payload)
        sock.sendall(frame)
        print(f"{datetime.now():%H:%M:%S} >> {what}: {frame.hex(' ')}")
        log("tx", what=what, data=frame.hex(" "))

    # Follow-up directives, in the order a real Echo sends them once Discover.Response arrives.
    followups = []
    if not args.no_sync:
        followups.append(lambda: send(f"timeinfo {now_iso()}", agt.state_update({"timeinfo": now_iso()})))
        followups.append(lambda: send("ClearIndicator", agt.directive("Notifications", "ClearIndicator")))
    for minutes in args.timer:
        def set_timer(minutes=minutes):
            token = str(random.randint(10**9, 4 * 10**9))
            end = (datetime.now(ZoneInfo(args.tz)) + timedelta(minutes=minutes)).isoformat(timespec="seconds")
            send(f"SetAlert TIMER {minutes} min (token {token}, ends {end})", agt.set_alert(token, "TIMER", end))
        followups.append(set_timer)
    for token in args.cancel:
        followups.append(lambda token=token: send(f"DeleteAlert {token}", agt.delete_alert(token)))

    # Scripted steps, relative to discovery. SECS:ACTION where ACTION is one of
    #   state:NAME=VALUE | timer:LABEL:MIN | alarm:LABEL:MIN | reminder:LABEL:MIN | delete:LABEL
    #   indicator:on | indicator:off
    # (--state SECS:NAME=VALUE is shorthand for SECS:state:NAME=VALUE.)
    tokens = {}

    def run_step(action):
        kind, _, rest = action.partition(":")
        if kind == "state":
            name, value = rest.split("=", 1)
            send(f"StateUpdate {name}={value}", agt.state_update({name: value}))
        elif kind in ("timer", "alarm", "reminder"):
            label, minutes = rest.split(":")
            token = tokens.setdefault(label, str(random.randint(10**9, 4 * 10**9)))
            ends = (datetime.now(ZoneInfo(args.tz)) + timedelta(minutes=float(minutes))).isoformat(timespec="seconds")
            send(f"SetAlert {kind.upper()} '{label}' {minutes} min (token {token}, ends {ends})",
                 agt.set_alert(token, kind.upper(), ends))
        elif kind == "delete":
            send(f"DeleteAlert '{rest}' (token {tokens[rest]})", agt.delete_alert(tokens[rest]))
        elif action == "sync":
            send(f"timeinfo {now_iso()}", agt.state_update({"timeinfo": now_iso()}))
        elif action == "indicator:on":
            send("SetIndicator persistVisualIndicator=true", agt.set_indicator())
        elif action == "indicator:off":
            send("ClearIndicator", agt.clear_indicator())
        else:
            raise SystemExit(f"unknown step {action!r}")

    delayed, scheduled = [], []
    for spec in args.state:
        delay, kv = spec.split(":", 1)
        delayed.append((float(delay), "state:" + kv))
    for spec in args.step:
        delay, action = spec.split(":", 1)
        delayed.append((float(delay), action))

    # Interactive control: each line written to the FIFO is run as a step (e.g. "timer:A:3").
    control = None
    if args.control:
        if not os.path.exists(args.control):
            os.mkfifo(args.control)
        control = os.open(args.control, os.O_RDONLY | os.O_NONBLOCK)
        print(f"Control FIFO: {args.control}")
    pending = b""

    sock.settimeout(0.5)
    frames = 0
    t0 = time.time()
    end = time.time() + args.listen
    while time.time() < end:
        if control is not None:
            try:
                chunk = os.read(control, 4096)
            except BlockingIOError:
                chunk = b""
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                line = line.decode().strip()
                if line:
                    print(f"   [command] {line}")
                    try:
                        run_step(line)
                    except (SystemExit, KeyError, ValueError) as e:
                        print(f"   [command failed] {e}")
        while scheduled and scheduled[0][0] <= time.time():
            t, action = scheduled.pop(0)
            print(f"   [step +{t - t0:.0f}s]")
            run_step(action)
        try:
            data = sock.recv(4096)
        except socket.timeout:
            continue
        except OSError as e:
            print(f"socket error: {e}")
            break
        if not data:
            print("!! clock closed the connection")
            log("closed")
            break
        print(f"<< {len(data)} bytes: {data.hex(' ')}")
        log("rx_raw", data=data.hex(" "))
        for cmd, err, seq, payload, ok in deframer.feed(data):
            frames += 1
            msg = agt.decode_message(payload)
            print(f"<< frame seq={seq} checksum={'ok' if ok else 'BAD'}")
            print("   " + json.dumps(msg, indent=2).replace("\n", "\n   "))
            log("rx_frame", seq=seq, checksum_ok=ok, payload=payload.hex(" "), decoded=msg)
            if msg.get("name") == "Discover.Response":
                for f in followups:
                    f()
                    time.sleep(0.3)
                followups = []
                t0 = time.time()
                scheduled = sorted((t0 + d, a) for d, a in delayed)
    sock.close()
    print(f"\n{frames} frame(s). Log: {log_path}")


if __name__ == "__main__":
    main()
