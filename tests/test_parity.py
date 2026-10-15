"""Python and JS renderers must agree on LED states and SVG output. Needs `node`."""
import json, random, shutil, subprocess, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from clocksim import Timer, led_states, render_svg

ROOT = pathlib.Path(__file__).resolve().parents[1]


def cases():
    rnd = random.Random(1)
    for _ in range(300):
        ts = [(rnd.choice([1, 17, 59, 60, 61, 119, 120, 1200, 3599, 3600, 5400, rnd.randint(1, 7200)]),
               rnd.random() < 0.2) for _ in range(rnd.randint(0, 5))]
        yield ts, rnd.random() < 0.1


def main():
    if not shutil.which("node"):
        print("node not found; skipping"); return
    data = [{"t": [{"remaining": r, "paused": p} for r, p in ts], "ringing": rg} for ts, rg in cases()]
    js = ("const s=require('./web/clocksim.js');const d=JSON.parse(require('fs').readFileSync(0));"
          "console.log(JSON.stringify(d.map(c=>[s.ledStates(c.t,c.ringing),"
          "s.renderSvg(c.t,{ringing:c.ringing,ghostPaused:true})])))")
    out = json.loads(subprocess.run(["node", "-e", js], input=json.dumps(data), cwd=ROOT,
                                    capture_output=True, text=True, check=True).stdout)
    for c, (states, svg) in zip(data, out):
        ts = [Timer(t["remaining"], t["paused"]) for t in c["t"]]
        assert states == led_states(ts, c["ringing"]), c
        # JS version sets width/height to 400 like the Python default; compare the drawing only
        assert svg.split("\n", 1)[1] == render_svg(ts, ringing=c["ringing"], ghost_paused=True).replace("<!--leds-->", "").replace("<!--/leds-->", "").split("\n", 1)[1], c
    print(f"ok: {len(data)} cases match")


main()
