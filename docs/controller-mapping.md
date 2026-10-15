# Mapping a controller's timer model onto the clock

The clock is a dumb display: your controller (a voice assistant, Home Assistant, ...) decides which
timers exist and when they ring, and mirrors that state to the clock. This is what a real Echo sends
(see [PROTOCOL.md §5b](../PROTOCOL.md)).

| Controller event | Send |
|---|---|
| timer started | `SetAlert(token, "TIMER", end_time)` |
| timer paused | `DeleteAlert(token)` |
| timer resumed / duration changed | `SetAlert(token, "TIMER", new_end_time)` (same token) |
| timer cancelled | `DeleteAlert(token)` |
| timer finished (ringing) | `StateUpdate timers=active`, **once** (what a real Echo does) |
| ringing stopped | `StateUpdate timers=cleared` + `DeleteAlert(token)` |
| on every (re)connect | `timeinfo`, `ClearIndicator`, then re-send all active alerts |
| DST change / hourly | `timeinfo` |

