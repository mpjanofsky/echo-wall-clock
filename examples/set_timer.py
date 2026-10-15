#!/usr/bin/env python3
"""Minimal use of agt.py: build the frames a real Echo sends to start (and later cancel) a timer.

No Bluetooth needed. This prints each frame as hex and decodes it back, so you can compare against
PROTOCOL.md or feed the bytes to your own RFCOMM channel-4 socket (pi_echo.py shows a working one).

    python3 examples/set_timer.py [minutes]
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agt


def main():
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 3
    now = datetime.now().astimezone()  # the clock ignores the UTC offset, so send LOCAL time
    end = now + timedelta(minutes=minutes)
    token = "1870862115"  # any unique string

    framer = agt.Framer()
    steps = [
        ("Discover", agt.discover()),
        ("timeinfo", agt.state_update({"timeinfo": now.isoformat(timespec="seconds")})),
        ("ClearIndicator", agt.clear_indicator()),
        ("SetAlert TIMER", agt.set_alert(token, "TIMER", end.isoformat(timespec="seconds"))),
        ("DeleteAlert", agt.delete_alert(token)),
    ]
    for label, payload in steps:
        frame = framer.frame(payload)
        print(f"{label:16} {frame.hex(' ')}")
    # A real session sends these in order over RFCOMM channel 4, waiting for the clock's
    # Discover.Response after Discover. DeleteAlert is what you send when the timer is cancelled.


if __name__ == "__main__":
    main()
