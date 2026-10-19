# Echo Wall Clock — Protocol & Behavior Findings

Reverse-engineered October 2026. Everything here was observed on real hardware: an Echo Wall Clock
(FCC ID UUU-8459, firmware `102`), an Echo Dot (as the reference "real Echo"), and a Raspberry Pi 3B
running BlueZ 5.82 acting as both a fake Echo and a fake clock.

> The clock's serial number (DSN) and device token are redacted (`<DSN>`, `<TOKEN>`). Capture them
> from your own unit with `pi_echo.py`; never publish them.

## TL;DR

- The clock is a standard **Alexa Gadget** that talks over **Bluetooth Classic (BR/EDR) SPP/RFCOMM**,
  not BLE. It uses the (now-deprecated, publicly documented) Alexa Gadgets Toolkit framing and protobufs.
- Anything that can pair over Classic BT, accept the clock's incoming calls, and send ~5 small
  protobuf messages can replace the Echo: set the time, show timers, pulse for timers/alarms/reminders,
  and light the yellow notification LED.
- The clock is **strict and silent**: messages must look exactly like a real Echo's (no optional
  fields), and it never sends errors — wrong messages are just ignored.

## 1. Radio and identity

| Item | Value |
|---|---|
| Transport | Bluetooth Classic (BR/EDR). Nothing on BLE. |
| BD address | `CC:9E:A2:xx:xx:xx` (OUI = Amazon Technologies) |
| Name | `EchoWallClk10U` (suffix likely varies per unit). The Mickey Mouse Edition advertises `EWCMickeyMouse05B` instead (reported by a user; the protocol on that clock is untested here) |
| Class of device | `0x001f00` (uncategorized) |
| Pairing | SSP "Just Works" (IO capability NoInputNoOutput). No PIN, no secret. |
| Link security | Encrypted (E0) after pairing; key size 16 |

### EIR (what it broadcasts while discoverable)

```
0f 09 "EchoWallClk10U"                          complete local name
11 06 b7 16 68 25 d1 5a 94 9f ed 4e 3a 98 b3 d2 88 60   128-bit UUID list (partial) = 6088D2B3-983A-4EED-9F94-5AD1256816B7
0b ff 49 19 42 08 71 01 10 15 15 fe               manufacturer data:
                                                    49 19  vendor  0x1949 (Lab126)
                                                    42 08  product 0x0842 (Echo Wall Clock)
                                                    71 01  Amazon BT SIG company id 0x0171
                                                    10 15 15 fe  Alexa Gadget marker 0xFE151510
```

macOS's BLE APIs (CoreBluetooth/bleak) never see it; System Settings → Bluetooth does, and
IOBluetooth inquiry does. Linux `btmgmt find -b` + `btmon` shows the full EIR.

### SDP records on the clock

| Name | Class UUID | RFCOMM channel |
|---|---|---|
| `SPP Port 4 DATA` | `0x1201` Generic Networking | **4** ← all gadget traffic |
| `SPP Port 2 OTA` | `0x1101` Serial Port | 2 (firmware update — never write to it) |
| *(unnamed)* | `6088D2B3-983A-4EED-9F94-5AD1256816B7` (Alexa Gadget) | 2 |

Amazon's archived AGT docs show the same three records (with the gadget record on channel 4); the
clock points it at 2, but the data channel is 4.

## 2. Pairing / connection behavior (the hard part)

- **Discoverable/connectable only while flashing amber** (hold the button). Outside that window,
  connecting to it fails with "Host is down" / page timeout.
- **A real Echo pairs and opens RFCOMM 4 in one continuous connection.** Pairing first and connecting
  later fails because the window closes.
- **The partner must be connectable.** Right after pairing, the clock drops the link and *calls the
  partner back* (AGT "reconnection flow": gadget initiates SDP, searching for SPP `0x1101`). If the
  partner isn't page-scanning, the radio link dies with a supervision timeout. Making the Pi
  connectable (and offering an SPP record) fixed this; the first RFCOMM attempt then usually gets
  `ECONNRESET` and the immediate retry succeeds.
- **Afterwards the clock periodically calls its partner** (centre LED flashes blue). If nobody opens
  RFCOMM 4 within ~20 s it drops and tries again later.
- **The partner can connect whenever it wants once bonded.** An idle, already-paired clock (no
  pairing mode) accepted a connection from the Pi on the first attempt and completed the handshake
  in ~1 s. (The earlier "Host is down" failures were right after pairing, while the clock was busy
  calling back.)
- **Call-in observed in detail:** ~70 s after the partner disconnected, the clock connected to the
  Pi, ran an SDP *Service Search* for Serial Port `0x1101`, got 0 records (nothing registered at
  that moment), held the link ~58 s waiting for RFCOMM, then disconnected. The blue pulse = this.
- **A held connection is tolerated:** the Pi held RFCOMM 4 open for 23 min (11:23–11:46) with no
  drop. While connected, the centre LED **pulses blue continuously** ("time syncing"); after the
  partner disconnects, the blue stops and a short segment animation plays. A real Echo therefore
  probably connects, syncs, and disconnects rather than holding the link (battery/LED).
- **One partner at a time.** Whoever paired last owns it; switching requires amber pairing mode again.
- Raspberry Pi 3: turn Wi-Fi off (shared radio/antenna) — Classic BT was unreliable with it on.
- Disconnecting clears the displayed timers (observed once; a held connection kept a 2-min timer
  for its full length). A bridge must stay connected while timers are active and re-send them after
  reconnecting.
- Open question: does a real Echo hold the connection permanently or drop it when idle? (Battery
  impact.) An Echo held its connection to the fake clock for at least several minutes.

## 3. Framing (RFCOMM channel 4, both directions)

```
F0 | cmd=02 | err=00 | seq | escaped( payload | checksum_hi | checksum_lo ) | F1
checksum = (cmd + err + sum(payload)) & 0xFFFF        (big-endian)
escape: bytes F0/F1/F2 inside payload/checksum -> F2, (byte ^ F2)
```

- The Echo's first frame uses `seq = 1`, then increments; the clock's first reply used `seq = 0`.
  Seq values F0–F2 are skipped rather than escaped.
- Stream-oriented: frames can be split across reads or coalesced (the clock's 387-byte reply arrived
  as 329 + 58 bytes).

## 4. Payload (protobuf, AGT schema)

```
Message   { 1: bytes payload }                       // wrapper, both directions
Directive { 1: Header{1 namespace, 2 name, 3 messageId, 4 dialogRequestId}, 2: payload }   // Echo -> clock
Event     { 1: Header{1 namespace, 2 name, 3 messageId}, 2: payload }                      // clock -> Echo
```

**Critical:** the real Echo omits `messageId`, `dialogRequestId`, and empty payloads entirely. Our
first attempts included a UUID messageId and a `BearerToken` scope (per Amazon's samples) and the
clock silently ignored them. Byte-identical copies of the Echo's messages work.

### Messages a real Echo sends (captured; `agt.py` reproduces each byte-for-byte)

| Directive | Payload | Example (hex, one frame) |
|---|---|---|
| `Alexa.Discovery` / `Discover` | none | `f0 02 00 01 0a 1d 0a 1b 0a 0f "Alexa.Discovery" 12 08 "Discover" 09 91 f1` |
| `Alexa.Gadget.StateListener` / `StateUpdate` | `states[] {1 name, 2 value}` e.g. `timeinfo = "2026-10-14T10:38:52-04:00"` | sent right after discovery |
| `Notifications` / `ClearIndicator` | none | sent right after `timeinfo` |
| `Alerts` / `SetAlert` | `1 token, 2 type, 3 scheduledTime` | token `"1870862115"`, type `"TIMER"`, time `"2026-10-14T10:44:19-04:00"` |
| `Alerts` / `DeleteAlert` | `1 token` | sent when a timer is cancelled |

- `scheduledTime` is the **end time** (local ISO-8601 with offset, seconds precision), not a duration.
- Tokens are decimal strings (10 digits observed); any unique string works.
- Order on connect: Discover → (Discover.Response) → StateUpdate timeinfo → ClearIndicator → any
  active alerts.

### Also confirmed working (built from the public AGT proto, not captured)

| Directive | Notes |
|---|---|
| `StateUpdate` `timers` / `alarms` / `reminders` = `active` | What the Echo sends when the alert is ringing. Triggers the ring pulse. |
| `StateUpdate` … = `cleared` | Accepted, no visible effect (pulse already self-terminates). |
| `SetAlert` type `ALARM` / `REMINDER` | Accepted; plays a "set" animation (see below). |
| `Notifications` / `SetIndicator` `{1 persistVisualIndicator = true}` | Centre LED pulses yellow. |

### The clock's `Discover.Response` (clock -> Echo)

```
Event Alexa.Discovery / Discover.Response
  endpoints[0]:
    endpointId:  <DSN>                 (16 chars; matches the DSN on the back)
    friendlyName: "EchoWallClk"
    description: "AlexaGadgetsEWC"
    capabilities:
      AlexaInterface  Alexa.Gadget.StateListener 1.0  supportedTypes: timeinfo, timers, alarms, reminders
      AlexaInterface  Alerts                     1.1
      AlexaInterface  Notifications              1.0
    additionalIdentification:
      firmwareVersion: "102"
      deviceToken: <TOKEN>              (64 hex chars; per AGT = sha256(DSN + device-type secret))
      deviceTokenEncryptionType: "1"
      amazonDeviceType: "A28P3XAXJIFE3L"
      modelName: "AlexaGadgetsEWC"
      radioAddress: "default"
```

The clock never sent anything else (no acks, no button/battery events) during any test. A short press
of the clock's button while connected sends nothing over RFCOMM — idle, and also during the ~10 s `active`
pulse burst (tested 2026-10-14 13:07).

## 5. Display behavior (observed)

| Input | What the clock does |
|---|---|
| `timeinfo` | Hands home to 12:00, then drive to the given time (~1–2 min). Already-correct time = no visible movement. **The UTC offset is ignored:** the wall-clock digits are shown as written (`15:40:42Z` set the hands to 3:40), so always send local time. |
| One timer, < 60 min | N segments lit clockwise from 12; the last (current-minute) segment is brightest. |
| Timer in final 60 s | Whole ring lights and counts down per second. |
| One timer, ≥ 60 min | A single segment at 12. |
| Two timers | Soonest = filled run from 12; later one = a single bright segment at its minute position. |
| `DeleteAlert` on the soonest | The next timer becomes the filled run. |
| `DeleteAlert` (any) | Removed silently, no animation. |
| Timer reaches 0 (no message) | Segments go out; **no pulse**. The clock does not ring by itself. |
| `timers`/`alarms`/`reminders` = `active` | ~5 full-ring pulses, ~2 s each (~10 s), then dark on its own. |
| `active` re-sent every 8–12 s | No continuous mode: each send starts a new burst (~5 pulses) with a visible dark gap between bursts. A send while a burst is running appears to be ignored. A ringing timer needs `active` re-sent about every 12 s. |
| `… = cleared` | Nothing visible. |
| Three timers (5, 20, 61 min) | Soonest = filled run from 12; second = single bright segment at its minute position (20 min = 4 o'clock); the 61-min timer is not separately visible (its segment is at 12, under the run). |
| Timer drops below 60 min | The ≥60-min single segment at 12 moves to its minute position (e.g. 59) and the segment at 12 goes dark. |
| Alarm set while timers are running | Set animation plays; no marker for the alarm's time afterwards; timers unchanged. |
| `SetAlert` `ALARM` or `REMINDER` | "Set" animation: a few segments either side of 12 sweep down to 6 and back up to 12. Nothing at the scheduled time unless `alarms`/`reminders = active` is sent. |
| `SetIndicator` | Centre LED pulses yellow ~4 times (a few seconds each), then stops on its own even with persistVisualIndicator=true. |
| `ClearIndicator` | No visible effect when already stopped. |

### Centre status LED (from the printed quick-start guide)

| Color | Meaning |
|---|---|
| Pulsing orange | Pairing mode |
| Solid blue | Paired |
| Pulsing blue | Time syncing or software updating (the periodic blue flashes = the clock calling its partner) |
| Pulsing yellow | Notification received (= `SetIndicator`, confirmed) |
| Single red blink | Battery low (no battery event has been seen on the wire) |
| Three red blinks | Error |

Alarms and reminders appear never to have been enabled for this clock on real Echos (product listing
and reviews only mention timers), yet the firmware accepts them: `SetAlert ALARM/REMINDER` plays the
"set" animation and `alarms/reminders=active` pulses. This is a dormant feature.

Implication: the clock is a dumb display. The controller (Echo/HA) decides when anything "rings",
and must send `active` at the right moment.

## 5b. What a real Echo sends (captured from an Echo Dot against the fake clock, 2026-10-14)

| Voice action | On the wire |
|---|---|
| Pair / connect | `Discover`, `StateUpdate timeinfo`, `ClearIndicator` (as before) |
| Set timer | `SetAlert TIMER` (token = 8–10 digit decimal, `scheduledTime` = end time) |
| Timer reaches 0 | `StateUpdate timers=active` **once**, ~1 s after the end time. Nothing more is sent while it rings (39 s observed). |
| Say "stop" while ringing | `DeleteAlert` + `StateUpdate timers=cleared`, same second |
| Pause | `DeleteAlert` (token) |
| Resume | `SetAlert` with the **same token** and a new end time (original end + paused duration) |
| Cancel | `DeleteAlert` (token); indistinguishable from pause |

(Confirmed by the user on the real clock with a real Echo: a timer ending gives ~5 pulses once, then the clock goes dark.)

So `active` is sent once and the clock's ~10 s pulse burst is the whole alert; the controller must not repeat it (my earlier "repeat every ~12 s" idea is not what Amazon does). The Dot also **held the RFCOMM link** from pairing onward (still connected 5+ min later) rather than connect/sync/disconnect.

### Connection lifecycle of a real Echo (Echo Dot, 53 min capture)

- Connects once (Discover, `timeinfo`, `ClearIndicator`) and **holds the RFCOMM link** for the whole capture:
  no disconnects, no repeat Discover.
- Re-sends `StateUpdate timeinfo` every **30 min** (12:21:06, 12:51:06 — an exact 30:00 apart; the first
  came 16 min after connect, so it looks tied to the half hour rather than the connect time). Two samples only.
- No other idle traffic. It never needed a reply beyond the first Discover.Response.

## 6. Controller mapping

See [docs/controller-mapping.md](docs/controller-mapping.md).

## 7. Open questions

- Battery impact of the held link a real Echo keeps (`timeinfo` every 30 min, see §5b) is unmeasured.
- Call-in cadence over hours/days (one call-in seen ~70 s after a disconnect; the regular interval
  is unknown). Presumably the partner should answer it with RFCOMM 4 + Discover + timeinfo.
- Is there an `active` variant that pulses until `cleared`? Re-sending every 8-12 s does not give
  continuous pulsing.
- `SetIndicator` with an asset / `playAudioIndicator`: any difference?
- Behavior with 4+ timers (1-3 timers, the 60-minute transition and alarms alongside timers are covered in §5).
- Whether a gadget-side `Discover.Response` needs a valid device token for the Echo to accept it
  (the Echo accepted the replayed genuine one; never tested a fake).

Answered: the bond survives a battery change (the Pi reconnected without pairing mode after the
batteries were pulled for ~10 s), and the real Echo's connection lifecycle and ring/stop/pause/resume
behavior are in §5b.

## 8. Gotchas

See [docs/troubleshooting.md](docs/troubleshooting.md).
