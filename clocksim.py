#!/usr/bin/env python3
"""Echo Wall Clock face simulator: draws the clock (bezel, numerals, 60-LED ring, hands) as SVG.

Pure functions, standard library only, no Bluetooth. The same renderer serves live
previews (call `render_svg` on every timer change) and static images for docs.
The display rules come from PROTOCOL.md section 5; the look follows the real clock.

    from clocksim import Timer, render_svg
    svg = render_svg([Timer(remaining=300), Timer(remaining=1200)], now=(10, 10))

    python3 clocksim.py --out docs/sim        # writes the example scenes
"""
from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from typing import Iterable, Sequence

LEDS = 60
MAX_TIMERS = 4  # protocol notes cover up to 3; the Second Hand plugin handles 4

# Looks modelled on the real clock: white bezel, near-black face, white numerals,
# 60 radial tick-LEDs (dim grey when off, white with a glow when lit).
COLORS = {
    "backdrop": "#12151c",
    "bezel_hi": "#f4f5f7",
    "bezel_lo": "#cfd2d8",
    "face": "#14161a",
    "off": "#3b3e45",
    "lit": "#e9ebf0",
    "lead": "#ffffff",
    "glow": "#ffffff",
    "numerals": "#f2f3f6",
    "hands": "#f4f5f7",
    "button": "#5b5e66",
    "ghost": "#8a90a0",
}


@dataclass(frozen=True)
class Timer:
    """One timer as the clock would see it.

    remaining: seconds until it ends. paused: the controller has sent DeleteAlert
    (PROTOCOL 5b), so the real clock shows nothing for it.
    """
    remaining: float
    paused: bool = False


def led_states(timers: Sequence[Timer], ringing: bool = False) -> list[str]:
    """Return 60 states, index 0 at 12 o'clock then clockwise: 'off' | 'lit' | 'lead'.

    Rules (PROTOCOL 5): the soonest timer is a filled run from 12 with a brighter last
    segment (one segment per minute; in the final 60 s the whole ring counts down per
    second; at 60 min or more just the segment at 12). Every later timer is a single
    bright segment at its minute position (60 min or more sits under the run at 12).
    Paused timers are invisible. `ringing` is the ~10 s full-ring pulse burst.
    """
    if ringing:
        return ["lit"] * LEDS
    states = ["off"] * LEDS
    live = sorted((t for t in timers if not t.paused and t.remaining > 0),
                  key=lambda t: t.remaining)[:MAX_TIMERS]
    for i, t in enumerate(live):
        r = t.remaining
        if i == 0:
            if r >= 3600:
                n = 1
            elif r <= 60:
                n = max(1, math.ceil(r))        # seconds countdown on the full ring
            else:
                n = math.ceil(r / 60)           # minutes, current-minute segment last
            for k in range(n - 1):
                states[k] = "lit"
            states[n - 1] = "lead"
        else:
            states[int(r // 60) % 60 if r < 3600 else 0] = "lead"
    return states


def _pt(deg: float, radius: float) -> tuple[float, float]:
    """Point at `deg` clockwise from 12 o'clock on a circle around (500, 500)."""
    a = math.radians(deg - 90)
    return 500 + radius * math.cos(a), 500 + radius * math.sin(a)


def _tick(i: int, r1: float, r2: float) -> tuple[float, float, float, float]:
    (x1, y1), (x2, y2) = _pt(i * 6, r1), _pt(i * 6, r2)
    return x1, y1, x2, y2


def _hand(deg: float, length: float, tip_w: float, base_w: float) -> str:
    """Tapered hand with a round tip, as a polygon plus a circle for the tip."""
    ux, uy = math.sin(math.radians(deg)), -math.cos(math.radians(deg))
    px, py = -uy, ux
    tx, ty = 500 + ux * length, 500 + uy * length
    pts = [(500 + px * base_w / 2, 500 + py * base_w / 2),
           (tx + px * tip_w / 2, ty + py * tip_w / 2),
           (tx - px * tip_w / 2, ty - py * tip_w / 2),
           (500 - px * base_w / 2, 500 - py * base_w / 2)]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    return (f'<polygon points="{poly}" fill="{COLORS["hands"]}"/>'
            f'<circle cx="{tx:.1f}" cy="{ty:.1f}" r="{tip_w / 2:g}" fill="{COLORS["hands"]}"/>')


def render_svg(timers: Iterable[Timer] = (), now: tuple[int, int] = (10, 10),
               ringing: bool = False, ghost_paused: bool = False,
               animate: bool = False, background: bool = False,
               title: str = "Echo Wall Clock") -> str:
    """Render the clock as an SVG string (1000x1000 viewBox).

    now: (hour, minute) for the hands. ghost_paused: draw paused timers as hollow
    markers (the real clock shows nothing; useful for explanatory images). animate:
    SMIL pulse for `ringing` (5 pulses, 2 s each, like the real burst). background:
    add a dark rounded backdrop behind the clock.
    """
    timers = list(timers)
    st = led_states(timers, ringing)
    C = COLORS
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000" width="400" '
           f'height="400" role="img" aria-label="{title}">',
           f'<title>{title}</title>',
           '<defs>'
           f'<linearGradient id="bz" x1="0" y1="0" x2="1" y2="1"><stop offset="0" '
           f'stop-color="{C["bezel_hi"]}"/><stop offset="1" stop-color="{C["bezel_lo"]}"/>'
           '</linearGradient>'
           '<filter id="g" x="-30%" y="-30%" width="160%" height="160%">'
           '<feGaussianBlur stdDeviation="7"/></filter></defs>']
    if background:
        out.append(f'<rect width="1000" height="1000" rx="48" fill="{C["backdrop"]}"/>')
    out.append('<circle cx="500" cy="500" r="395" fill="url(#bz)"/>')
    out.append(f'<circle cx="500" cy="500" r="346" fill="#9da1aa"/>')
    out.append(f'<circle cx="500" cy="500" r="338" fill="{C["face"]}"/>')

    for n in range(1, 13):
        x, y = _pt(n * 30, 272)
        out.append(f'<text x="{x:.1f}" y="{y:.1f}" font-family="-apple-system,Helvetica,Arial,'
                   f'sans-serif" font-size="64" text-anchor="middle" dominant-baseline="central" '
                   f'fill="{C["numerals"]}">{n}</text>')

    glow, leds = [], []
    for i, s in enumerate(st):
        x1, y1, x2, y2 = _tick(i, 312, 340)
        if s == "off":
            leds.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                        f'stroke="{C["off"]}" stroke-width="5" stroke-linecap="round"/>')
        else:
            lead = s == "lead"
            w = 12 if lead else 8
            glow.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                        f'stroke="{C["glow"]}" stroke-width="{w + 6}" stroke-linecap="round"/>')
            leds.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                        f'stroke="{C["lead"] if lead else C["lit"]}" stroke-width="{w}" '
                        'stroke-linecap="round"/>')
    if ghost_paused:
        for t in timers:
            if t.paused and t.remaining > 0:
                i = int(t.remaining // 60) % 60 if t.remaining < 3600 else 0
                x1, y1, x2, y2 = _tick(i, 312, 340)
                leds.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                            f'stroke="{C["ghost"]}" stroke-width="14" stroke-linecap="round"/>'
                            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                            f'stroke="{C["face"]}" stroke-width="7" stroke-linecap="round"/>'
                            f'<rect x="478" y="345" width="14" height="40" rx="3" fill="{C["ghost"]}"/>'
                            f'<rect x="508" y="345" width="14" height="40" rx="3" fill="{C["ghost"]}"/>')

    pulse = ('<animate attributeName="opacity" values="0;1;0" dur="2s" repeatCount="5" fill="freeze"/>'
             if animate and ringing else "")
    out.append(f'<!--leds--><g>{pulse}<g filter="url(#g)" opacity=".5">{"".join(glow)}</g>{"".join(leds)}</g><!--/leds-->')

    out.append(f'<circle cx="506" cy="645" r="22" fill="{C["button"]}" stroke="#767a83" stroke-width="3"/>')
    h, m = now
    out.append(_hand(((h % 12) + m / 60) * 30, 195, 16, 28))
    out.append(_hand(m * 6, 272, 13, 24))
    out.append(f'<circle cx="500" cy="500" r="14" fill="{C["hands"]}"/>')
    out.append('</svg>')
    return "\n".join(out) + "\n"


SCENES = {
    "idle": dict(timers=[], title="Idle: hands only"),
    "one-timer": dict(timers=[Timer(23 * 60 + 30)], title="One timer, 24 minutes left"),
    "final-minute": dict(timers=[Timer(17)], title="One timer, final minute (17 s left)"),
    "long-timer": dict(timers=[Timer(90 * 60)], title="One timer of an hour or more"),
    "several-timers": dict(timers=[Timer(8 * 60), Timer(20 * 60), Timer(41 * 60), Timer(95 * 60)],
                           title="Four timers"),
    "paused": dict(timers=[Timer(12 * 60, paused=True)], ghost_paused=True,
                   title="Paused timer (hollow marker and pause icon are annotation; the clock shows nothing)"),
    "done": dict(timers=[], ringing=True, animate=True, title="Timer finished: full-ring pulse"),
}


# One frame per step; the loop plays them at FRAME_S seconds each (time is sped up).
LOOP = (
    [([], False)] * 2
    + [([Timer(m * 60)], False) for m in (5, 4, 3, 2)]
    + [([Timer(60), Timer(17 * 60)], False), ([Timer(45), Timer(17 * 60)], False),
       ([Timer(30), Timer(17 * 60)], False), ([Timer(15), Timer(17 * 60)], False),
       ([Timer(5), Timer(17 * 60)], False)]
    + [([], True)] * 3
    + [([Timer(17 * 60)], False), ([Timer(16 * 60), Timer(40 * 60)], False)]
    + [([Timer(15 * 60, paused=True), Timer(40 * 60)], False)]
)
FRAME_S = 1.2


def render_loop_svg(background: bool = True) -> str:
    """One self-playing SVG that loops through LOOP (for the README; SMIL, no scripts)."""
    frames = [render_svg(t, ringing=r, background=background, title="Echo Wall Clock demo")
              for t, r in LOOP]
    head, _, rest = frames[0].partition("<!--leds-->")
    _, _, tail = rest.partition("<!--/leds-->")
    n, total = len(frames), FRAME_S * len(frames)
    groups = []
    for i, f in enumerate(frames):
        leds = f.partition("<!--leds-->")[2].partition("<!--/leds-->")[0]
        times = sorted({0.0, i / n, (i + 1) / n, 1.0})
        vals = ";".join("1" if i / n <= t < (i + 1) / n else "0" for t in times)
        keys = ";".join(f"{t:.5f}" for t in times)
        groups.append(f'<g opacity="0"><animate attributeName="opacity" calcMode="discrete" '
                      f'dur="{total:.1f}s" repeatCount="indefinite" keyTimes="{keys}" '
                      f'values="{vals}"/>{leds}</g>')
    return head + "".join(groups) + tail


def write_scenes(out_dir: str, background: bool = True) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for name, kw in SCENES.items():
        p = os.path.join(out_dir, f"{name}.svg")
        with open(p, "w") as f:
            f.write(render_svg(background=background, **kw))
        paths.append(p)
    p = os.path.join(out_dir, "demo-loop.svg")
    with open(p, "w") as f:
        f.write(render_loop_svg(background=background))
    paths.append(p)
    return paths


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="docs/sim", help="directory for the example scenes")
    ap.add_argument("--no-background", action="store_true", help="transparent, no backdrop")
    args = ap.parse_args()
    for p in write_scenes(args.out, background=not args.no_background):
        print(p)


if __name__ == "__main__":
    main()
