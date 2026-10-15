#!/usr/bin/env python3
"""Extract your clock's Discover.Response from a pi_echo.py log, for fake_clock.py --response.

    python3 tools/extract_response.py logs/<timestamp>-piecho.jsonl clock_discover_response.bin

The output contains your clock's serial number (DSN) and device token. Keep it private.
"""

import json
import sys

for line in open(sys.argv[1]):
    rec = json.loads(line)
    if rec.get("kind") == "rx_frame" and (rec.get("decoded") or {}).get("name") == "Discover.Response":
        open(sys.argv[2], "wb").write(bytes.fromhex(rec["payload"]))
        print(f"wrote {sys.argv[2]} (keep it private)")
        break
else:
    sys.exit("no Discover.Response found in that log")
