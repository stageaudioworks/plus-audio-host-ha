/* Plus Audio meters card: live zone levels from the Plus Audio Host integration.
 * Served and loaded by the integration itself (no dashboard resource needed).
 * It subscribes over Home Assistant's own websocket; it never talks to the processor and never sees its token.
 *
 *   type: custom:plus-audio-meters-card
 *   title: Levels            # optional
 *   entry_id: abc123         # optional: one processor (default: all)
 *   zones: [A, B, 5]         # optional: letters or numbers (default: every zone in use)
 *   rate: 15                 # optional: updates a second, 1 to 20 (default 15)
 *   show_rms: true           # optional: draw the average level inside the peak bar when the processor sends it
 */
const FLOOR = -60, YELLOW = -18, RED = -6;
const RELEASE_DB_S = 24;       // how fast a bar falls back (dB a second)
const HOLD_MS = 1500;          // peak hold, then it falls at the same rate

const pct = (db) => Math.max(0, Math.min(100, ((db - FLOOR) / -FLOOR) * 100));

class PlusAudioMetersCard extends HTMLElement {
  static getStubConfig() { return { title: "Levels" }; }
  static getConfigElement() { return undefined; }

  setConfig(config) {
    const rate = Number(config.rate ?? 15);
    this._config = {
      title: config.title ?? "Levels",
      entry_id: config.entry_id,
      zones: Array.isArray(config.zones) ? config.zones.map((z) => String(z).toUpperCase()) : null,
      rate: Math.max(1, Math.min(20, Number.isFinite(rate) ? rate : 15)),
      show_rms: config.show_rms !== false,
    };
    this._resubscribe();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first || (hass.connection !== this._conn)) this._resubscribe();
  }

  getCardSize() { return 1 + Math.ceil((this._zones?.length || 4) / 2); }
  getGridOptions() { return { columns: 12, min_columns: 6, rows: "auto" }; }

  connectedCallback() {
    this._connected = true;
    if (!this.shadowRoot) this._build();
    this._resubscribe();
    this._raf = requestAnimationFrame((t) => this._tick(t));
  }

  disconnectedCallback() {
    this._connected = false;
    this._unsubscribe();
    cancelAnimationFrame(this._raf);
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

  // ---- frames
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
    if (layout !== this._layout) { this._layout = layout; this._zones = zones; this._renderRows(); }
    const now = performance.now();
    for (const z of zones) {
      const m = this._meters[z.key];
      if (!m) continue;
      m.zone = z;
      const peaks = z.peak_db.length ? z.peak_db : [];
      peaks.forEach((db, i) => {
        const ch = m.ch[i] || m.ch[0];
        if (!ch) return;
        if (db >= ch.peak) ch.peak = db;              // attack is instant, release happens in _tick
        if (db >= ch.hold) { ch.hold = db; ch.holdAt = now; }
        ch.rms = z.rms_db[i] ?? null;
      });
      if (!peaks.length) m.ch.forEach((ch) => { ch.rms = null; });
      m.stale = !peaks.length;
    }
    this._mode = all.map((fr) => fr.mode);
    this._errs = all.filter((fr) => fr.error).map((fr) => `${fr.device}: ${fr.error}`);
    this._renderStatus();
  }

  // ---- drawing
  _build() {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { padding: 12px 16px 14px; }
        .head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
        .title { font-size: 1.1em; font-weight: 500; color: var(--primary-text-color); }
        .status { font-size: .8em; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .status.err { color: var(--error-color, #db4437); white-space: normal; }
        .rows { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px 20px; }
        .row { display: grid; grid-template-columns: minmax(0, 1fr); gap: 3px; }
        .name { display: flex; justify-content: space-between; gap: 8px; font-size: .9em; color: var(--primary-text-color); }
        .name span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .db { font-variant-numeric: tabular-nums; color: var(--secondary-text-color); font-size: .85em; min-width: 4.5em; text-align: right; }
        .row.muted .name span:first-child::after { content: " · muted"; color: var(--secondary-text-color); }
        .bar { position: relative; cursor: default; height: 7px; border-radius: 2px; overflow: hidden;
               background: var(--secondary-background-color, rgba(127,127,127,.15)); }
        .fill { position: absolute; inset: 0 auto 0 0; width: 0;
                background: linear-gradient(90deg, var(--success-color, #43a047) 0 ${pct(YELLOW)}%,
                  var(--warning-color, #f9a825) ${pct(YELLOW)}% ${pct(RED)}%, var(--error-color, #e53935) ${pct(RED)}% 100%);
                background-size: var(--full, 100%) 100%; will-change: width; }
        .rms { position: absolute; top: 2px; bottom: 2px; left: 0; width: 0; background: rgba(0,0,0,.28); will-change: width; }
        .hold { position: absolute; top: 0; bottom: 0; width: 2px; left: 0; background: var(--primary-text-color); opacity: .75; will-change: left; }
        .row.stale .bar { opacity: .4; }
        .row.muted .fill { filter: grayscale(1); opacity: .5; }
        .empty { color: var(--secondary-text-color); font-size: .9em; padding: 8px 0; }
      </style>
      <ha-card>
        <div class="head"><div class="title"></div><div class="status"></div></div>
        <div class="rows"><div class="empty">Connecting…</div></div>
      </ha-card>`;
    this._el = { title: root.querySelector(".title"), status: root.querySelector(".status"), rows: root.querySelector(".rows") };
    this._meters = {};
  }

  _renderRows() {
    if (!this.shadowRoot) this._build();
    this._el.title.textContent = this._config.title || "";
    const rows = this._el.rows;
    rows.textContent = "";
    this._meters = {};
    if (!this._zones.length) {
      rows.innerHTML = `<div class="empty">No zones to show.</div>`;
      return;
    }
    for (const z of this._zones) {
      const row = document.createElement("div");
      row.className = "row";
      const name = document.createElement("div");
      name.className = "name";
      const label = document.createElement("span");
      label.textContent = z.label;
      label.title = `${z.letter}${z.source ? " · " + z.source : ""}`;
      const db = document.createElement("span");
      db.className = "db";
      name.append(label, db);
      row.append(name);
      const ch = [];
      for (let i = 0; i < 2; i++) {
        const bar = document.createElement("div");
        bar.className = "bar";
        bar.title = `${i ? "Right" : "Left"}: green to ${YELLOW} dB, yellow to ${RED} dB, red above`;
        const fill = document.createElement("div"); fill.className = "fill";
        const rms = document.createElement("div"); rms.className = "rms";
        const hold = document.createElement("div"); hold.className = "hold";
        bar.append(fill, rms, hold);
        row.append(bar);
        ch.push({ fill, rmsEl: rms, holdEl: hold, peak: FLOOR - 1, hold: FLOOR - 1, holdAt: 0, rms: null, shown: -1 });
      }
      rows.append(row);
      this._meters[z.key] = { row, db, ch, zone: z, stale: true };
    }
  }

  _renderStatus() {
    if (!this._el) return;
    this._el.title.textContent = this._config?.title || "";
    const s = this._el.status;
    if (this._error || this._errs?.length) {
      s.className = "status err";
      s.textContent = this._error || this._errs.join(" · ");
      return;
    }
    s.className = "status";
    const modes = new Set(this._mode || []);
    s.textContent = modes.has("push") ? "live" : modes.has("meters") ? "live (polled)"
      : modes.has("status") ? "polled, may lag" : "connecting…";
  }

  _tick(t) {
    const dt = this._last ? Math.min(0.25, (t - this._last) / 1000) : 0;
    this._last = t;
    for (const m of Object.values(this._meters || {})) {
      let top = FLOOR - 1;
      for (const ch of m.ch) {
        ch.peak = Math.max(FLOOR - 1, ch.peak - RELEASE_DB_S * dt);
        if (t - ch.holdAt > HOLD_MS) ch.hold = Math.max(ch.peak, ch.hold - RELEASE_DB_S * dt);
        const w = pct(ch.peak);
        if (Math.abs(w - ch.shown) > 0.1) {
          ch.fill.style.width = `${w}%`;
          ch.fill.style.setProperty("--full", w > 0 ? `${(100 / w) * 100}%` : "100%");   // colour bands stay put
          ch.shown = w;
        }
        ch.holdEl.style.left = `calc(${pct(ch.hold)}% - 2px)`;
        ch.holdEl.style.display = ch.hold > FLOOR ? "" : "none";
        ch.rmsEl.style.width = this._config.show_rms && ch.rms != null ? `${pct(ch.rms)}%` : "0";
        top = Math.max(top, ch.hold);
      }
      m.row.classList.toggle("stale", m.stale);
      m.row.classList.toggle("muted", !!m.zone?.mute);
      const txt = m.stale ? "–" : top > FLOOR ? `${top.toFixed(1)} dB` : `< ${FLOOR}`;
      if (m.db.textContent !== txt) m.db.textContent = txt;
    }
    if (this._connected) this._raf = requestAnimationFrame((tt) => this._tick(tt));
  }
}

if (!customElements.get("plus-audio-meters-card")) {
  customElements.define("plus-audio-meters-card", PlusAudioMetersCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "plus-audio-meters-card",
    name: "Plus Audio meters",
    description: "Live zone levels from a Plus Audio Host",
    preview: false,
    documentationURL: "https://github.com/stageaudioworks/plus-audio-host-ha#live-meters",
  });
}
