/* Plus Audio meters card: live zone levels from the Plus Audio Host integration, drawn like a console's meter bridge.
 * Served and loaded by the integration itself (no dashboard resource needed).
 * It subscribes over Home Assistant's own websocket; it never talks to the processor and never sees its token.
 *
 *   type: custom:plus-audio-meters-card
 *   title: Levels            # optional
 *   entry_id: abc123         # optional: one processor (default: all)
 *   zones: [A, B, 5]         # optional: letters or numbers (default: every zone in use)
 *   ballistics: rms          # rms (default, about 300 ms like a VU or a Q-SYS RMS meter), ppm (instant rise,
 *                            # slow fall, like a console's peak meter) or fast (the raw levels)
 *   peak_hold: 2             # optional: seconds the peak marker holds (0: no marker)
 *   height: 200              # optional: meter height in pixels
 *   show_values: true        # optional: the level in dB under each zone
 *   rate: 15                 # optional: updates a second from the processor, 1 to 20
 */
const FLOOR = -60;
const YELLOW = -18, RED = -6, CLIP = -1;
const TICKS = [0, -6, -12, -18, -24, -30, -40, -60];
// a console-style scale: more room near the top, where it matters
const SCALE = [[-60, 0], [-40, 0.14], [-30, 0.3], [-20, 0.5], [-10, 0.75], [0, 1]];
const BALLISTICS = {
  rms:  { tau: 0.30 },                       // power average, same rise and fall (VU-like, 300 ms)
  ppm:  { attack: 0.005, release: 12 },      // near-instant rise, 12 dB a second fall (IEC type I-ish)
  fast: { attack: 0, release: 40 },
};
const PEAK_FALL = 20;                         // dB a second, after the hold
const STALE_MS = 1200;                        // no frame for this long: the zone falls to silence

function pos(db) {                            // dB → 0..1 up the meter
  if (db <= SCALE[0][0]) return 0;
  for (let i = 1; i < SCALE.length; i++) {
    const [d1, p1] = SCALE[i], [d0, p0] = SCALE[i - 1];
    if (db <= d1) return p0 + ((db - d0) / (d1 - d0)) * (p1 - p0);
  }
  return 1;
}
const toPow = (db) => Math.pow(10, db / 10);
const toDb = (p) => (p > 1e-12 ? 10 * Math.log10(p) : -120);

class PlusAudioMetersCard extends HTMLElement {
  static getStubConfig() { return { title: "Levels" }; }

  setConfig(config) {
    const num = (v, d, lo, hi) => { const n = Number(v ?? d); return Math.max(lo, Math.min(hi, Number.isFinite(n) ? n : d)); };
    this._config = {
      title: config.title ?? "Levels",
      entry_id: config.entry_id,
      zones: Array.isArray(config.zones) ? config.zones.map((z) => String(z).toUpperCase()) : null,
      rate: num(config.rate, 15, 1, 20),
      ballistics: BALLISTICS[config.ballistics] ? config.ballistics : "rms",
      peak_hold: num(config.peak_hold, 2, 0, 30),
      height: num(config.height, 200, 100, 600),
      show_values: config.show_values !== false,
    };
    if (this.shadowRoot) this._applyHeight();
    this._resubscribe();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first || hass.connection !== this._conn) this._resubscribe();
  }

  getCardSize() { return Math.ceil((this._config?.height || 200) / 50) + 2; }
  getGridOptions() { return { columns: 12, min_columns: 6, rows: "auto" }; }

  connectedCallback() {
    this._connected = true;
    if (!this.shadowRoot) this._build();
    this._resubscribe();
    this._last = 0;
    this._raf = requestAnimationFrame((t) => this._tick(t));
  }

  disconnectedCallback() {
    this._connected = false;
    this._unsubscribe();
    cancelAnimationFrame(this._raf);
    this._ro?.disconnect();
  }

  // ---- websocket
  async _resubscribe() {
    this._unsubscribe();
    if (!this._connected || !this._hass || !this._config) return;
    const conn = (this._conn = this._hass.connection);
    const msg = { type: "plus_audio_host/meters/subscribe", rate: this._config.rate };
    if (this._config.entry_id) msg.entry_id = this._config.entry_id;
    const token = (this._subToken = {});
    try {
      const unsub = await conn.subscribeMessage((f) => this._onFrame(f), msg);
      if (token !== this._subToken || !this._connected) { unsub(); return; }
      this._unsub = unsub;
      this._error = null;
    } catch (e) {
      this._error = e?.message || "Live levels are not available (is the Plus Audio Host integration 0.3 or newer?)";
      this._renderStatus();
    }
  }

  _unsubscribe() {
    this._subToken = null;
    if (this._unsub) { try { this._unsub(); } catch (e) { /* the connection already went */ } }
    this._unsub = null;
  }

  // ---- frames: only set targets; the drawing loop applies the ballistics
  _onFrame(f) {
    this._frames = this._frames || {};
    this._frames[f.entry_id] = f;
    const all = Object.values(this._frames);
    const multi = all.length > 1;
    const zones = [];
    for (const fr of all) {
      for (const z of fr.zones) {
        if (this._config.zones && !this._config.zones.includes(z.letter) && !this._config.zones.includes(String(z.zone))) continue;
        zones.push({ ...z, key: `${fr.entry_id}:${z.zone}`, label: multi ? `${fr.device} · ${z.name}` : z.name });
      }
    }
    const layout = zones.map((z) => z.key).join("|");
    if (layout !== this._layout) { this._layout = layout; this._renderStrips(zones); }
    const now = performance.now();
    for (const z of zones) {
      const s = this._strips[z.key];
      if (!s) continue;
      s.zone = z;
      if (!z.peak_db.length) { s.has = false; continue; }
      s.has = true;
      s.at = now;
      s.ch.forEach((ch, i) => {
        const peak = z.peak_db[i] ?? z.peak_db[0];
        const rms = z.rms_db[i] ?? z.rms_db[0];
        ch.peakIn = peak;
        // with rms ballistics, prefer the processor's own average when it sends one
        ch.target = this._config.ballistics === "rms" && rms != null ? rms : peak;
        if (peak >= ch.hold) { ch.hold = peak; ch.holdAt = now; }
        if (peak >= CLIP) ch.clipAt = now;
      });
    }
    this._mode = all.map((fr) => fr.mode);
    this._errs = all.filter((fr) => fr.error).map((fr) => `${fr.device}: ${fr.error}`);
    this._renderStatus();
  }

  // ---- layout
  _build() {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { padding: 12px 12px 10px; overflow: hidden; }
        .head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin: 0 4px 10px; }
        .title { font-size: 1.1em; font-weight: 500; color: var(--primary-text-color); }
        .status { font-size: .8em; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .status.err { color: var(--error-color, #db4437); white-space: normal; }
        .bridge { display: flex; align-items: flex-start; gap: 0; overflow-x: auto; overflow-y: hidden;
                  background: #0b0d10; border-radius: 8px; padding: 10px 8px 8px 0;
                  box-shadow: inset 0 1px 3px rgba(0,0,0,.6); scrollbar-width: thin; }
        .scale { position: sticky; left: 0; z-index: 1; flex: none; background: #0b0d10; padding-left: 4px; }
        .strip { flex: none; width: 54px; display: flex; flex-direction: column; align-items: center; gap: 5px; }
        .strip + .strip { border-left: 1px solid #1a1e24; }
        canvas { display: block; }
        .val { font: 500 11px/1 ui-monospace, "SF Mono", Menlo, Consolas, monospace; color: #9fb0a4;
               font-variant-numeric: tabular-nums; height: 11px; }
        .name { font-size: 11px; line-height: 1.2; color: #c9cdd2; width: 50px; text-align: center;
                overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .strip.muted .name::before { content: "M "; color: #ff6b5a; font-weight: 700; }
        .strip.muted canvas, .strip.muted .val { opacity: .45; }
        .empty { color: #8a9099; font-size: .9em; padding: 16px; }
      </style>
      <ha-card>
        <div class="head"><div class="title"></div><div class="status"></div></div>
        <div class="bridge"><canvas class="scale"></canvas><div class="empty">Connecting…</div></div>
      </ha-card>`;
    this._el = { title: root.querySelector(".title"), status: root.querySelector(".status"),
                 bridge: root.querySelector(".bridge"), scale: root.querySelector(".scale") };
    this._strips = {};
    this._applyHeight();
  }

  _applyHeight() {
    this._dpr = window.devicePixelRatio || 1;
    this._mh = this._config?.height || 200;        // the meter's own height, clip light included
    this._sizeCanvas(this._el.scale, 30, this._mh);
    for (const s of Object.values(this._strips || {})) { this._sizeCanvas(s.canvas, 30, this._mh); s.drawn = null; }
    this._drawScale();
  }

  _sizeCanvas(c, w, h) {
    c.style.width = `${w}px`; c.style.height = `${h}px`;
    c.width = Math.round(w * this._dpr); c.height = Math.round(h * this._dpr);
  }

  // geometry inside a meter canvas (css px): a clip light, then the segments
  get _geo() {
    const top = 10, bottom = this._mh - 1;
    return { top, bottom, h: bottom - top };
  }

  _drawScale() {
    const c = this._el.scale, g = c.getContext("2d"), d = this._dpr, { top, h } = this._geo;
    g.setTransform(d, 0, 0, d, 0, 0);
    g.clearRect(0, 0, 30, this._mh);
    g.font = "10px ui-monospace, Menlo, Consolas, monospace";
    g.textAlign = "right"; g.textBaseline = "middle";
    for (const t of TICKS) {
      const y = top + h * (1 - pos(t));
      g.fillStyle = t >= RED ? "#ff8a7a" : t >= YELLOW ? "#e8c45a" : "#7d8794";
      g.fillText(t === 0 ? "0" : String(t), 22, Math.max(top + 4, Math.min(top + h - 4, y)));
      g.fillStyle = "#39404a";
      g.fillRect(25, Math.round(y), 4, 1);
    }
  }

  _renderStrips(zones) {
    const bridge = this._el.bridge;
    bridge.querySelectorAll(".strip, .empty").forEach((n) => n.remove());
    this._strips = {};
    if (!zones.length) {
      bridge.insertAdjacentHTML("beforeend", `<div class="empty">No zones to show.</div>`);
      return;
    }
    for (const z of zones) {
      const strip = document.createElement("div");
      strip.className = "strip";
      const canvas = document.createElement("canvas");
      this._sizeCanvas(canvas, 30, this._mh);
      const val = document.createElement("div"); val.className = "val";
      const name = document.createElement("div"); name.className = "name";
      name.textContent = z.label;
      name.title = `${z.letter} · ${z.label}${z.source ? " · " + z.source : ""}`;
      strip.append(canvas, val, name);
      if (!this._config.show_values) val.style.display = "none";
      bridge.append(strip);
      const ch = [0, 1].map(() => ({ target: -120, pow: 0, db: -120, peakIn: -120, hold: -120, holdAt: 0, clipAt: -1e9 }));
      this._strips[z.key] = { canvas, val, name, strip, ch, zone: z, has: false, at: 0, shownAt: 0, drawn: null };
    }
  }

  _renderStatus() {
    if (!this._el) return;
    this._el.title.textContent = this._config?.title || "";
    this._el.title.style.display = this._config?.title ? "" : "none";
    const s = this._el.status;
    if (this._error || this._errs?.length) {
      s.className = "status err";
      s.textContent = this._error || this._errs.join(" · ");
      return;
    }
    s.className = "status";
    const modes = new Set(this._mode || []);
    const src = modes.has("push") ? "live" : modes.has("meters") ? "live (polled)" : modes.has("status") ? "polled, may lag" : "connecting…";
    s.textContent = `${this._config.ballistics.toUpperCase()} · ${src}`;
  }

  // ---- ballistics and drawing
  _tick(t) {
    const dt = this._last ? Math.min(0.1, (t - this._last) / 1000) : 0;
    this._last = t;
    const b = BALLISTICS[this._config.ballistics];
    const holdMs = this._config.peak_hold * 1000;
    for (const s of Object.values(this._strips || {})) {
      const stale = !s.has || t - s.at > STALE_MS;
      for (const ch of s.ch) {
        const target = stale ? -120 : ch.target;
        if (b.tau) {                                   // rms: average the power
          ch.pow += (toPow(target) - ch.pow) * (1 - Math.exp(-dt / b.tau));
          ch.db = toDb(ch.pow);
        } else if (target > ch.db) {                   // ppm / fast: quick rise, steady fall
          ch.db = b.attack ? ch.db + (target - ch.db) * (1 - Math.exp(-dt / b.attack)) : target;
        } else {
          ch.db = Math.max(target, ch.db - b.release * dt);
        }
        if (t - ch.holdAt > holdMs) ch.hold = Math.max(ch.db, ch.hold - PEAK_FALL * dt);
        if (stale) ch.hold = Math.min(ch.hold, Math.max(ch.db, FLOOR - 1));
      }
      this._drawStrip(s, t);
      if (this._config.show_values && t - s.shownAt > 250) {    // a readable number: four times a second
        s.shownAt = t;
        const lv = Math.max(...s.ch.map((c) => c.db));
        const txt = !s.has ? "–" : lv > FLOOR ? lv.toFixed(1) : "-∞";
        if (s.val.textContent !== txt) s.val.textContent = txt;
      }
      s.strip.classList.toggle("muted", !!s.zone?.mute);
    }
    if (this._connected) this._raf = requestAnimationFrame((tt) => this._tick(tt));
  }

  _drawStrip(s, t) {
    const { bottom, h } = this._geo;
    const holdOn = this._config.peak_hold > 0;
    // skip the redraw when nothing visible moved
    const sig = s.ch.map((c) => `${pos(c.db).toFixed(3)}/${holdOn ? pos(c.hold).toFixed(3) : 0}/${t - c.clipAt < 2000 ? 1 : 0}`).join("|");
    if (sig === s.drawn) return;
    s.drawn = sig;
    const g = s.canvas.getContext("2d"), d = this._dpr;
    g.setTransform(d, 0, 0, d, 0, 0);
    g.clearRect(0, 0, 30, this._mh);
    const seg = 3, gap = 1, step = seg + gap;
    const n = Math.floor(h / step);
    const cw = 10, xs = [4, 16];
    s.ch.forEach((ch, i) => {
      const x = xs[i];
      // clip light
      const clip = t - ch.clipAt < 2000;
      g.fillStyle = clip ? "#ff3b2f" : "#2a1716";
      g.fillRect(x, 0, cw, 6);
      const lit = pos(ch.db) * n;
      const holdSeg = holdOn && ch.hold > FLOOR ? Math.min(n - 1, Math.floor(pos(ch.hold) * n)) : -1;
      for (let k = 0; k < n; k++) {
        const y = bottom - (k + 1) * step + gap;
        const p = (k + 0.5) / n;
        const zone = p >= pos(RED) ? 2 : p >= pos(YELLOW) ? 1 : 0;
        const on = k < lit;
        const isHold = k === holdSeg && !on;
        g.fillStyle = on || isHold
          ? ["#2fd15b", "#f2c230", "#ff4b3a"][zone]
          : ["#0f2416", "#2a2410", "#2c1412"][zone];
        if (isHold) g.globalAlpha = 0.95;
        g.fillRect(x, y, cw, seg);
        g.globalAlpha = 1;
      }
    });
  }
}

if (!customElements.get("plus-audio-meters-card")) {
  customElements.define("plus-audio-meters-card", PlusAudioMetersCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "plus-audio-meters-card",
    name: "Plus Audio meters",
    description: "Live zone levels from a Plus Audio Host, as a meter bridge",
    preview: false,
    documentationURL: "https://github.com/stageaudioworks/plus-audio-host-ha#live-meters",
  });
}
