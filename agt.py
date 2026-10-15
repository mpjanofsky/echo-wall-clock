"""Alexa Gadgets protocol (Classic Bluetooth / SPP) -- Echo side.

Transport-independent: framing, checksums, a tiny protobuf codec, and
builders for the directives an Echo sends. Written from the behavior of
Amazon's public gadget samples; no Amazon code is included.

SPP frame:  F0 | cmd=02 | err=00 | seq | escaped(payload + checksum16_be) | F1
  checksum = (cmd + err + sum(payload)) & 0xFFFF
  bytes F0/F1/F2 inside seq/payload/checksum are sent as F2, (byte ^ F2)

Payload is protobuf:  Message{1: bytes} wrapping
  Directive{1: Header{1 namespace, 2 name, 3 messageId, 4 dialogRequestId}, 2: payload}
  Event    {1: Header{1 namespace, 2 name, 3 messageId},                    2: payload}
"""


STX, ETX, ESC = 0xF0, 0xF1, 0xF2
RESERVED = (STX, ETX, ESC)
CMD, ERR = 0x02, 0x00

# ---------------------------------------------------------------- framing


def _escape(data):
    out = bytearray()
    for b in data:
        if b in RESERVED:
            out += bytes([ESC, ESC ^ b])
        else:
            out.append(b)
    return out


class Framer:
    """Builds outgoing frames with an incrementing sequence id."""

    def __init__(self, first_seq=1):
        self._seq = first_seq  # a real Echo starts at 1; the clock's first reply used 0

    def frame(self, payload):
        payload = bytes(payload)
        checksum = (CMD + ERR + sum(payload)) & 0xFFFF
        seq = self._seq
        # Like Amazon's sample: never use a reserved byte as seq, so it needs no escaping.
        self._seq = (self._seq + 1) & 0xFF
        while self._seq in RESERVED:
            self._seq = (self._seq + 1) & 0xFF
        return bytes([STX, CMD, ERR, seq]) + _escape(payload + bytes([checksum >> 8, checksum & 0xFF])) + bytes([ETX])


class Deframer:
    """Feed raw stream bytes; yields (cmd, err, seq, payload, checksum_ok)."""

    def __init__(self):
        self._buf = None
        self._escaped = False

    def feed(self, data):
        out = []
        for b in data:
            if b == STX:
                self._buf, self._escaped = bytearray(), False
                continue
            if self._buf is None:
                continue
            if b == ETX:
                out.append(self._finish(self._buf))
                self._buf = None
                continue
            if self._escaped:
                self._buf.append(ESC ^ b)
                self._escaped = False
            elif b == ESC:
                self._escaped = True
            else:
                self._buf.append(b)
        return [f for f in out if f is not None]

    @staticmethod
    def _finish(buf):
        if len(buf) < 5:
            return None
        cmd, err, seq = buf[0], buf[1], buf[2]
        payload, found = bytes(buf[3:-2]), (buf[-2] << 8) | buf[-1]
        ok = found == ((cmd + err + sum(payload)) & 0xFFFF)
        return cmd, err, seq, payload, ok


# ---------------------------------------------------------------- protobuf


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def field_bytes(num, value):
    if isinstance(value, str):
        value = value.encode()
    return _varint((num << 3) | 2) + _varint(len(value)) + bytes(value)


def field_varint(num, value):
    return _varint(num << 3) + _varint(int(value))


def _read_varint(data, i):
    shift = n = 0
    while True:
        b = data[i]
        i += 1
        n |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return n, i


def parse_fields(data):
    """Raw protobuf -> list of (field, wiretype, value). Raises on malformed input."""
    fields, i = [], 0
    while i < len(data):
        key, i = _read_varint(data, i)
        num, wt = key >> 3, key & 7
        if num == 0:
            raise ValueError("field 0")
        if wt == 0:
            v, i = _read_varint(data, i)
        elif wt == 2:
            ln, i = _read_varint(data, i)
            if i + ln > len(data):
                raise ValueError("truncated")
            v, i = bytes(data[i:i + ln]), i + ln
        elif wt == 1:
            v, i = int.from_bytes(data[i:i + 8], "little"), i + 8
        elif wt == 5:
            v, i = int.from_bytes(data[i:i + 4], "little"), i + 4
        else:
            raise ValueError(f"wiretype {wt}")
        fields.append((num, wt, v))
    return fields


def decode_any(data, depth=0):
    """Best-effort schema-less decode, for exploring messages we have no .proto for."""
    try:
        text = data.decode("utf-8")
        if text and all(c.isprintable() for c in text):
            return text
    except UnicodeDecodeError:
        pass
    if depth < 8 and data:
        try:
            out = {}
            for num, wt, v in parse_fields(data):
                val = decode_any(v, depth + 1) if wt == 2 else v
                out.setdefault(str(num), []).append(val)
            return {k: v[0] if len(v) == 1 else v for k, v in out.items()}
        except (ValueError, IndexError):
            pass
    return data.hex(" ")


# ---------------------------------------------------------------- messages


def header(namespace, name, message_id="", dialog_request_id=""):
    """Empty fields are omitted, as the Echo does -- the clock ignores bigger messages."""
    h = field_bytes(1, namespace) + field_bytes(2, name)
    if message_id:
        h += field_bytes(3, message_id)
    if dialog_request_id:
        h += field_bytes(4, dialog_request_id)
    return h


def directive(namespace, name, payload=b"", message_id=""):
    """Echo -> gadget. Returns the bytes that go inside an SPP frame."""
    d = field_bytes(1, header(namespace, name, message_id))
    if payload:
        d += field_bytes(2, payload)
    return field_bytes(1, d)


def discover():
    """Byte-for-byte what a real Echo sends (captured 2026-10-14): header only, no messageId, no payload."""
    return directive("Alexa.Discovery", "Discover")


def state_update(states):
    """Alexa.Gadget.StateListener StateUpdate; states = {name: value}."""
    payload = b"".join(field_bytes(1, field_bytes(1, k) + field_bytes(2, v)) for k, v in states.items())
    return directive("Alexa.Gadget.StateListener", "StateUpdate", payload)


def set_alert(token, alert_type, scheduled_time):
    """Alerts.SetAlert; alert_type e.g. 'TIMER'/'ALARM', scheduled_time ISO-8601."""
    payload = field_bytes(1, token) + field_bytes(2, alert_type) + field_bytes(3, scheduled_time)
    return directive("Alerts", "SetAlert", payload)


def set_indicator(persist_visual=True, play_audio=False):
    """Notifications.SetIndicator. NOT yet captured from a real Echo -- built from the public proto."""
    payload = b""
    if persist_visual:
        payload += field_varint(1, 1)
    if play_audio:
        payload += field_varint(2, 1)
    return directive("Notifications", "SetIndicator", payload)


def clear_indicator():
    return directive("Notifications", "ClearIndicator")


def delete_alert(token):
    return directive("Alerts", "DeleteAlert", field_bytes(1, token))


def decode_message(payload):
    """Gadget -> Echo payload: Message{Event{header, payload}} -> dict."""
    try:
        (num, wt, inner), *_ = parse_fields(payload)
        fields = {n: v for n, _, v in parse_fields(inner)}
        hdr = {n: v.decode(errors="replace") for n, _, v in parse_fields(fields.get(1, b""))}
        return {
            "namespace": hdr.get(1),
            "name": hdr.get(2),
            "messageId": hdr.get(3),
            "payload": decode_any(fields.get(2, b"")),
        }
    except (ValueError, IndexError):
        return {"raw": decode_any(payload)}
