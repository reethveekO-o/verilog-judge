"""Reads a VCD file (the standard waveform dump format) into plain data.

A VCD file has two parts:
  header:  $timescale ... $end, then one `$var <type> <width> <id> <name> $end`
           per signal. The <id> is a short code used in the second part.
  changes: `#<time>` lines, each followed by the values that changed then:
           `1!` (single bit, id "!")  or  `b1010 "` (multi-bit, id '"').
"""
import re

MAX_SIGNALS = 32
MAX_CHANGES = 4000          # per signal
TO_NS = {"s": 1e9, "ms": 1e6, "us": 1e3, "ns": 1.0, "ps": 1e-3, "fs": 1e-6}


def _display(bits: str, width: int) -> str:
    """Turn raw VCD bits into what the page shows: 0/1 for one bit, decimal for buses."""
    if "x" in bits:
        return "x"
    if "z" in bits:
        return "z"
    return bits if width == 1 else str(int(bits, 2))


def parse_vcd(text: str):
    toks = text.split()
    n = len(toks)
    i = 0
    scale = 1.0                 # one VCD time unit, in nanoseconds
    signals = []
    by_id = {}

    # ---- header ----
    while i < n:
        t = toks[i]
        if t == "$timescale":
            j = i + 1
            while j < n and toks[j] != "$end":
                j += 1
            m = re.fullmatch(r"(\d+)(s|ms|us|ns|ps|fs)", "".join(toks[i + 1:j]))
            if m:
                scale = int(m[1]) * TO_NS[m[2]]
            i = j + 1
        elif t == "$var" and i + 4 < n:
            kind, width, ident, name = toks[i + 1], int(toks[i + 2]), toks[i + 3], toks[i + 4]
            if kind not in ("real", "event", "parameter") and len(signals) < MAX_SIGNALS:
                sig = {"name": name, "width": width, "changes": []}
                signals.append(sig)
                by_id.setdefault(ident, []).append(sig)
            while i < n and toks[i] != "$end":
                i += 1
            i += 1
        elif t == "$enddefinitions":
            i += 2
            break
        else:
            i += 1

    # ---- value changes ----
    now = 0.0
    while i < n:
        t = toks[i]
        c = t[0]
        if c == "#" and t[1:].isdigit():
            now = round(int(t[1:]) * scale, 6)
            i += 1
            continue
        if c in "01xzXZ":
            bits, ident = c.lower(), t[1:]
            i += 1
        elif c in "bB" and i + 1 < n:
            bits, ident = t[1:].lower(), toks[i + 1]
            i += 2
        elif c in "rR":
            i += 2
            continue
        else:                   # $dumpvars, $end and similar markers
            i += 1
            continue
        for sig in by_id.get(ident, ()):
            ch = sig["changes"]
            value = _display(bits, sig["width"])
            if ch and ch[-1][0] == now:
                ch[-1][1] = value               # changed twice at the same instant
            elif len(ch) < MAX_CHANGES and (not ch or ch[-1][1] != value):
                ch.append([now, value])

    if not signals:
        return None
    return {"end_ns": now, "signals": signals}
