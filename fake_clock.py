#!/usr/bin/env python3
"""Impersonate the Echo Wall Clock to a real Echo and record what it sends.

Runs on Linux/BlueZ (the Raspberry Pi). Copies the clock's identity as seen
over the air -- name, class of device, EIR (Lab126 vendor 0x1949, product
0x0842, Amazon gadget marker) and its three SDP records -- then accepts the
Echo's pairing and RFCOMM connections on channels 2 and 4 and logs every byte.
It never replies, so the Echo sees a silent gadget; we only want its opener.

    sudo python3 fake_clock.py [--name EchoWallClk10U]

Take the batteries out of the real clock first so the Echo can't find it.
"""

import argparse
import json
import os
import socket
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

import agt

BLUEZ = "org.bluez"
AGENT_PATH = "/fakeclock/agent"
GADGET_UUID = "6088d2b3-983a-4eed-9f94-5ad1256816b7"
CLASS_OF_DEVICE = "0x001f00"
# Manufacturer data exactly as the real clock sends it (little-endian on air):
# vendor 0x1949 (Lab126), product 0x0842, Amazon SIG id 0x0171, gadget id 0xFE151510.
MFR_DATA = "4919" + "4208" + "7101" + "101515fe"
LOG_DIR = Path(__file__).parent / "logs"
# Optional: a Discover.Response recorded from your own clock (pi_echo.py logs it). It contains your
# clock's serial number and device token, so it is never shipped. If given, we answer the Echo with it,
# so the Echo carries on as if we were the clock and sends time sync / timer directives.
RESPONSE_FILE = None


def log_line(kind, **data):
    LOG.write(json.dumps({"t": time.time(), "kind": kind, **data}, default=str) + "\n")
    LOG.flush()


def eir_hex(name):
    name_b = name.encode()
    eir = bytes([1 + len(name_b), 0x09]) + name_b
    # 128-bit service UUID list (partial), little-endian
    eir += bytes([0x11, 0x06]) + bytes.fromhex(GADGET_UUID.replace("-", ""))[::-1]
    mfr = bytes.fromhex(MFR_DATA)
    eir += bytes([1 + len(mfr), 0xFF]) + mfr
    return eir.hex()


def sdp_record(name, class_uuid, channel):
    return f"""<?xml version="1.0" encoding="UTF-8" ?>
<record>
  <attribute id="0x0001"><sequence><uuid value="{class_uuid}" /></sequence></attribute>
  <attribute id="0x0004"><sequence>
    <sequence><uuid value="0x0100" /></sequence>
    <sequence><uuid value="0x0003" /><uint8 value="0x{channel:02x}" /></sequence>
  </sequence></attribute>
  <attribute id="0x0005"><sequence><uuid value="0x1002" /></sequence></attribute>
  {f'<attribute id="0x0100"><text value="{name}" /></attribute>' if name else ''}
</record>"""


class Agent(dbus.service.Object):
    """NoInputNoOutput agent: accept everything, like a clock with no buttons would."""

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        print(f"[agent] AuthorizeService {device} {uuid}")
        log_line("authorize_service", device=device, uuid=uuid)

    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        print(f"[agent] RequestConfirmation {device} {passkey:06d} -> accept")
        log_line("pair_confirm", device=device, passkey=int(passkey))

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        print(f"[agent] RequestAuthorization {device} -> accept")
        log_line("pair_authorize", device=device)

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Cancel(self):
        print("[agent] Cancel")

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Release(self):
        pass


class Profile(dbus.service.Object):
    """BlueZ hands us each incoming RFCOMM connection as a file descriptor."""

    def __init__(self, bus, path, label):
        super().__init__(bus, path)
        self.label = label

    @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
    def NewConnection(self, device, fd, props):
        fd = fd.take()
        print(f"\n[{self.label}] CONNECTION from {device}")
        log_line("connect", profile=self.label, device=str(device))
        sock = socket.socket(fileno=fd)
        sock.setblocking(True)  # BlueZ hands the fd over non-blocking
        threading.Thread(target=self._reader, args=(sock, str(device)), daemon=True).start()

    def _reader(self, sock, device):
        deframer = agt.Deframer()
        framer = agt.Framer(first_seq=0)
        try:
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                print(f"[{self.label}] << {len(data)} bytes: {data.hex(' ')}")
                log_line("rx_raw", profile=self.label, data=data.hex(" "))
                for cmd, err, seq, payload, ok in deframer.feed(data):
                    msg = agt.decode_message(payload)
                    print(f"[{self.label}] frame cmd=0x{cmd:02x} err=0x{err:02x} seq={seq} checksum={'ok' if ok else 'BAD'}")
                    print("   " + json.dumps(msg, indent=2).replace("\n", "\n   "))
                    log_line("rx_frame", profile=self.label, cmd=cmd, err=err, seq=seq,
                             checksum_ok=ok, payload=payload.hex(" "), decoded=msg)
                    if msg.get("name") == "Discover" and RESPONSE_FILE and RESPONSE_FILE.exists():
                        reply = framer.frame(RESPONSE_FILE.read_bytes())
                        sock.sendall(reply)
                        print(f"[{self.label}] >> replied with the real clock's Discover.Response ({len(reply)} bytes)")
                        log_line("tx", profile=self.label, what="Discover.Response (recorded)", data=reply.hex(" "))
        except OSError as e:
            print(f"[{self.label}] socket error: {e}")
        print(f"[{self.label}] disconnected {device}")
        log_line("disconnect", profile=self.label, device=device)
        sock.close()

    @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
    def RequestDisconnection(self, device):
        print(f"[{self.label}] RequestDisconnection {device}")

    @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
    def Release(self):
        pass


def hciconfig(*args):
    subprocess.run(["hciconfig", "hci0", *args], check=False)


def apply_identity(name):
    """Class and EIR go straight to the controller; bluetoothd may rewrite them, so we reapply."""
    hciconfig("class", CLASS_OF_DEVICE)
    hciconfig("inqmode", "2")
    hciconfig("inqdata", eir_hex(name))
    return True


def main():
    global LOG
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", default="EchoWallClk10U")
    p.add_argument("--response", type=Path, help="raw Discover.Response frame payload recorded from your own clock")
    args = p.parse_args()
    global RESPONSE_FILE
    RESPONSE_FILE = args.response

    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-fake.jsonl"
    LOG = log_path.open("a")

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    adapter_path = "/org/bluez/hci0"
    adapter = dbus.Interface(bus.get_object(BLUEZ, adapter_path), "org.freedesktop.DBus.Properties")

    agent = Agent(bus, AGENT_PATH)
    agent_mgr = dbus.Interface(bus.get_object(BLUEZ, "/org/bluez"), "org.bluez.AgentManager1")
    agent_mgr.RegisterAgent(AGENT_PATH, "NoInputNoOutput")
    agent_mgr.RequestDefaultAgent(AGENT_PATH)

    profile_mgr = dbus.Interface(bus.get_object(BLUEZ, "/org/bluez"), "org.bluez.ProfileManager1")
    profiles = [
        # (label, uuid, channel, record-name, class uuid) -- mirrors the clock's SDP dump
        ("DATA", "00001201-0000-1000-8000-00805f9b34fb", 4, "SPP Port 4 DATA", "0x1201"),
        ("OTA", "00001101-0000-1000-8000-00805f9b34fb", 2, "SPP Port 2 OTA", "0x1101"),
    ]
    keep = []
    for label, uuid, chan, rec_name, class_uuid in profiles:
        path = f"/fakeclock/{label.lower()}"
        keep.append(Profile(bus, path, label))
        profile_mgr.RegisterProfile(path, uuid, {
            "Name": rec_name,
            "Role": "server",
            "Channel": dbus.UInt16(chan),
            "RequireAuthentication": False,
            "RequireAuthorization": False,
            "AutoConnect": False,
            "ServiceRecord": sdp_record(rec_name, class_uuid, chan),
        })
        print(f"Registered {label} on RFCOMM {chan}")
    # Gadget identity record: same channel as OTA on the real clock, so it can't own a listener.
    # Registered as a client-role profile purely to publish the SDP record.
    gadget_path = "/fakeclock/gadget"
    keep.append(Profile(bus, gadget_path, "GADGET"))
    try:
        profile_mgr.RegisterProfile(gadget_path, GADGET_UUID, {
            "Role": "server",
            "Channel": dbus.UInt16(2),
            "RequireAuthentication": False,
            "RequireAuthorization": False,
            "AutoConnect": False,
            "ServiceRecord": sdp_record(None, GADGET_UUID, 2),
        })
        print("Registered gadget record (RFCOMM 2)")
    except dbus.DBusException as e:
        print(f"Gadget record registration failed: {e}")
        log_line("error", where="gadget_record", error=str(e))

    adapter.Set("org.bluez.Adapter1", "Alias", args.name)
    adapter.Set("org.bluez.Adapter1", "Pairable", True)
    adapter.Set("org.bluez.Adapter1", "PairableTimeout", dbus.UInt32(0))
    adapter.Set("org.bluez.Adapter1", "DiscoverableTimeout", dbus.UInt32(0))
    adapter.Set("org.bluez.Adapter1", "Discoverable", True)
    time.sleep(1)
    apply_identity(args.name)
    GLib.timeout_add_seconds(15, apply_identity, args.name)

    print(f"\nPretending to be {args.name}. EIR={eir_hex(args.name)}")
    print(f"Log: {log_path}")
    print("Now: take the real clock's batteries out, then pair a Wall Clock from the Alexa app.\n")
    log_line("start", name=args.name, eir=eir_hex(args.name))
    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        pass
    finally:
        adapter.Set("org.bluez.Adapter1", "Discoverable", False)
        print("\nStopped.")


if __name__ == "__main__":
    main()
