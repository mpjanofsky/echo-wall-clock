// Echo Wall Clock face simulator (JS port of ../clocksim.py). Same rules, same SVG.
// Rules: PROTOCOL.md section 5. Keep in sync with clocksim.py (see tests/test_parity.py).
(function (root) {
  const LEDS = 60, MAX_TIMERS = 4;
  const C = {
    backdrop: "#12151c", bezel_hi: "#f4f5f7", bezel_lo: "#cfd2d8", face: "#14161a",
    off: "#3b3e45", lit: "#e9ebf0", lead: "#ffffff", glow: "#ffffff", numerals: "#f2f3f6",
    hands: "#f4f5f7", button: "#5b5e66", ghost: "#8a90a0",
  };

  // timers: [{remaining: seconds, paused: bool}] -> 60 x 'off'|'lit'|'lead'
  function ledStates(timers, ringing) {
    if (ringing) return Array(LEDS).fill("lit");
    const st = Array(LEDS).fill("off");
    const live = timers.filter(t => !t.paused && t.remaining > 0)
      .sort((a, b) => a.remaining - b.remaining).slice(0, MAX_TIMERS);
    live.forEach((t, i) => {
      const r = t.remaining;
      if (i === 0) {
        const n = r >= 3600 ? 1 : r <= 60 ? Math.max(1, Math.ceil(r)) : Math.ceil(r / 60);
        for (let k = 0; k < n - 1; k++) st[k] = "lit";
        st[n - 1] = "lead";
      } else {
        st[r < 3600 ? Math.floor(r / 60) % 60 : 0] = "lead";
      }
    });
    return st;
  }

  const pt = (deg, r) => { const a = (deg - 90) * Math.PI / 180; return [500 + r * Math.cos(a), 500 + r * Math.sin(a)]; };
  const f1 = x => x.toFixed(1);
  const tick = (i, r1, r2) => [...pt(i * 6, r1), ...pt(i * 6, r2)];
  const line = (t, stroke, w, extra = "") =>
    `<line x1="${f1(t[0])}" y1="${f1(t[1])}" x2="${f1(t[2])}" y2="${f1(t[3])}" stroke="${stroke}" stroke-width="${w}" stroke-linecap="round"${extra}/>`;

  function hand(deg, length, tipW, baseW) {
    const ux = Math.sin(deg * Math.PI / 180), uy = -Math.cos(deg * Math.PI / 180), px = -uy, py = ux;
    const tx = 500 + ux * length, ty = 500 + uy * length;
    const pts = [[500 + px * baseW / 2, 500 + py * baseW / 2], [tx + px * tipW / 2, ty + py * tipW / 2],
                 [tx - px * tipW / 2, ty - py * tipW / 2], [500 - px * baseW / 2, 500 - py * baseW / 2]];
    return `<polygon points="${pts.map(p => f1(p[0]) + "," + f1(p[1])).join(" ")}" fill="${C.hands}"/>` +
           `<circle cx="${f1(tx)}" cy="${f1(ty)}" r="${tipW / 2}" fill="${C.hands}"/>`;
  }

  // opts: {now:[h,m], ringing, ghostPaused, animate, background, title, size}
  function renderSvg(timers, opts = {}) {
    const { now = [10, 10], ringing = false, ghostPaused = false, animate = false,
            background = false, title = "Echo Wall Clock", size = 400 } = opts;
    const st = ledStates(timers, ringing);
    const o = [`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000" width="${size}" height="${size}" role="img" aria-label="${title}">`,
      `<title>${title}</title>`,
      `<defs><linearGradient id="bz" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${C.bezel_hi}"/><stop offset="1" stop-color="${C.bezel_lo}"/></linearGradient>` +
      `<filter id="g" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="7"/></filter></defs>`];
    if (background) o.push(`<rect width="1000" height="1000" rx="48" fill="${C.backdrop}"/>`);
    o.push(`<circle cx="500" cy="500" r="395" fill="url(#bz)"/>`, `<circle cx="500" cy="500" r="346" fill="#9da1aa"/>`,
           `<circle cx="500" cy="500" r="338" fill="${C.face}"/>`);
    for (let n = 1; n <= 12; n++) {
      const [x, y] = pt(n * 30, 272);
      o.push(`<text x="${f1(x)}" y="${f1(y)}" font-family="-apple-system,Helvetica,Arial,sans-serif" font-size="64" text-anchor="middle" dominant-baseline="central" fill="${C.numerals}">${n}</text>`);
    }
    const glow = [], leds = [];
    st.forEach((s, i) => {
      const t = tick(i, 312, 340);
      if (s === "off") leds.push(line(t, C.off, 5));
      else { const lead = s === "lead", w = lead ? 12 : 8;
        glow.push(line(t, C.glow, w + 6)); leds.push(line(t, lead ? C.lead : C.lit, w)); }
    });
    if (ghostPaused) timers.forEach(t => {
      if (t.paused && t.remaining > 0) {
        const tk = tick(t.remaining < 3600 ? Math.floor(t.remaining / 60) % 60 : 0, 312, 340);
        leds.push(line(tk, C.ghost, 14), line(tk, C.face, 7),
          `<rect x="478" y="345" width="14" height="40" rx="3" fill="${C.ghost}"/><rect x="508" y="345" width="14" height="40" rx="3" fill="${C.ghost}"/>`);
      }
    });
    const pulse = animate && ringing ? `<animate attributeName="opacity" values="0;1;0" dur="2s" repeatCount="5" fill="freeze"/>` : "";
    o.push(`<g>${pulse}<g filter="url(#g)" opacity=".5">${glow.join("")}</g>${leds.join("")}</g>`);
    o.push(`<circle cx="506" cy="645" r="22" fill="${C.button}" stroke="#767a83" stroke-width="3"/>`);
    const [h, m] = now;
    o.push(hand(((h % 12) + m / 60) * 30, 195, 16, 28), hand(m * 6, 272, 13, 24),
           `<circle cx="500" cy="500" r="14" fill="${C.hands}"/>`, `</svg>`);
    return o.join("\n") + "\n";
  }

  const api = { ledStates, renderSvg };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.ClockSim = api;
})(typeof window !== "undefined" ? window : globalThis);
