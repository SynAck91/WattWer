class PVEnergyAllocationPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._initialized = false;
    this._rangeMode = "today";
    this._selectedDisplay = "";
    this._resolution = "auto";
    this._displayMode = localStorage.getItem("wattwer.defaultDisplayMode") || "groups";
    this._liveTimer = null;
    this._historyTimer = null;
    this._refreshing = false;
    this._liveRefreshing = false;
    this._lastView = null;
    this._management = null;
    this._backfillStatus = null;
  }

  set hass(value) {
    this._hass = value;
    if (!this._initialized) {
      this._initialized = true;
      this._renderShell();
      this._setPreset("today", false);
      this._refresh();
      // The lightweight summary comes directly from the controller and does not
      // query Recorder. Full history is reloaded only when a quarter closes,
      // the user changes the range/configuration, or presses refresh.
      this._liveTimer = setInterval(() => this._refreshLive(), Math.max(5, Number(localStorage.getItem("wattwer.liveRefreshSeconds") || 5)) * 1000);
    }
  }

  get hass() { return this._hass; }
  set panel(value) { this._panel = value; }
  set narrow(value) { this._narrow = value; }

  disconnectedCallback() {
    if (this._liveTimer) clearInterval(this._liveTimer);
    if (this._historyTimer) clearInterval(this._historyTimer);
    this._liveTimer = null;
    this._historyTimer = null;
  }

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; min-height:100%; background:var(--primary-background-color); color:var(--primary-text-color); }
        * { box-sizing:border-box; }
        .page { max-width:1500px; margin:0 auto; padding:20px; }
        .hero { display:flex; align-items:center; justify-content:space-between; gap:18px; margin-bottom:18px; }
        .hero h1 { margin:0; font-size:28px; font-weight:650; letter-spacing:-.02em; }
        .hero p { margin:5px 0 0; color:var(--secondary-text-color); }
        .status { padding:7px 11px; border-radius:999px; background:var(--card-background-color); border:1px solid var(--divider-color); font-size:13px; white-space:nowrap; }
        .toolbar, .card { background:var(--card-background-color); border-radius:16px; box-shadow:var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,.10)); }
        .toolbar { padding:14px; display:flex; flex-wrap:wrap; gap:10px; align-items:end; margin-bottom:16px; }
        button, select, input { font:inherit; color:var(--primary-text-color); background:var(--secondary-background-color); border:1px solid var(--divider-color); border-radius:10px; padding:9px 11px; }
        input[type=checkbox] { width:18px; height:18px; padding:0; }
        button { cursor:pointer; }
        button.primary, button.active { background:var(--primary-color); color:var(--text-primary-color, white); border-color:var(--primary-color); }
        button.danger { color:var(--error-color); }
        button:disabled { opacity:.5; cursor:default; }
        label { display:flex; flex-direction:column; gap:5px; font-size:12px; color:var(--secondary-text-color); }
        .spacer { flex:1; }
        .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:14px; margin-bottom:16px; }
        .summary { padding:16px; }
        .summary h3 { margin:0 0 12px; font-size:16px; }
        .total { font-size:25px; font-weight:650; margin-bottom:12px; }
        .sources { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; }
        .metric { border-radius:11px; padding:9px; background:var(--secondary-background-color); min-width:0; }
        .metric .label { font-size:11px; color:var(--secondary-text-color); }
        .metric .value { font-weight:650; margin-top:3px; }
        .bar { height:7px; border-radius:7px; overflow:hidden; display:flex; background:var(--divider-color); margin-top:12px; }
        .pv { background:#f4b400; } .gridc { background:#4285f4; } .battery { background:#8e5bd9; }
        .main { display:grid; grid-template-columns:minmax(0,1fr) 300px; gap:16px; }
        .chartcard { padding:16px; min-width:0; }
        .charthead { display:flex; flex-wrap:wrap; gap:10px; justify-content:space-between; align-items:center; margin-bottom:12px; }
        .chartwrap { overflow-x:auto; min-height:330px; }
        svg { width:100%; min-width:760px; height:330px; display:block; }
        .side { padding:16px; }
        .side h3, .chartcard h3 { margin:0; font-size:16px; }
        .diag { margin-top:14px; display:grid; gap:9px; }
        .diagrow { display:flex; justify-content:space-between; gap:10px; padding-bottom:8px; border-bottom:1px solid var(--divider-color); font-size:13px; }
        .muted { color:var(--secondary-text-color); }
        .legend { display:flex; flex-wrap:wrap; gap:13px; font-size:12px; color:var(--secondary-text-color); }
        .dot { width:9px; height:9px; border-radius:50%; display:inline-block; margin-right:5px; }
        .error { padding:18px; background:var(--error-color); color:white; border-radius:12px; }
        .loading { padding:40px; text-align:center; color:var(--secondary-text-color); }
        .modalback { position:fixed; z-index:1000; inset:0; background:rgba(0,0,0,.55); display:flex; align-items:flex-start; justify-content:center; padding:4vh 16px; overflow:auto; }
        .modal { width:min(1120px,100%); max-height:92vh; overflow:auto; background:var(--card-background-color); color:var(--primary-text-color); border-radius:18px; box-shadow:0 10px 40px rgba(0,0,0,.35); }
        .modalhead { position:sticky; top:0; z-index:2; background:var(--card-background-color); padding:18px 20px; border-bottom:1px solid var(--divider-color); display:flex; align-items:center; justify-content:space-between; gap:12px; }
        .modalhead h2 { margin:0; font-size:21px; }
        .modalbody { padding:20px; }
        .modalfoot { position:sticky; bottom:0; background:var(--card-background-color); border-top:1px solid var(--divider-color); padding:14px 20px; display:flex; justify-content:flex-end; gap:10px; }
        .section { margin-bottom:24px; }
        .section h3 { margin:0 0 8px; }
        .section p { margin:4px 0 12px; }
        .consumerrow { display:grid; grid-template-columns:42px minmax(150px,.8fr) minmax(250px,1.4fr) 135px 120px; gap:8px; align-items:center; padding:9px 0; border-bottom:1px solid var(--divider-color); }
        .consumerrow.header { color:var(--secondary-text-color); font-size:12px; }
        .consumerrow input, .consumerrow select { width:100%; min-width:0; }
        .grouprow { border:1px solid var(--divider-color); border-radius:12px; padding:12px; margin:9px 0; }
        .grouptop { display:flex; gap:8px; align-items:center; }
        .grouptop input { flex:1; }
        .members { display:flex; flex-wrap:wrap; gap:8px 14px; margin-top:10px; }
        .members label { flex-direction:row; align-items:center; font-size:13px; }
        .notice { padding:11px 13px; border-radius:10px; background:var(--secondary-background-color); color:var(--secondary-text-color); line-height:1.45; }
        .progress { margin-top:12px; white-space:pre-wrap; font-family:monospace; font-size:12px; background:var(--secondary-background-color); padding:12px; border-radius:10px; }
        @media (max-width:900px) { .main { grid-template-columns:1fr; } .page{padding:12px;} .hero{align-items:flex-start;flex-direction:column;} .consumerrow{grid-template-columns:36px 1fr;}.consumerrow.header{display:none;} .consumerrow > *:nth-child(n+3){grid-column:2;} }
      </style>
      <div class="page">
        <div class="hero">
          <div><h1>WattWer</h1><p>PV-, Netz- und Batteriezuordnung pro Verbraucher</p></div>
          <div class="status" id="status">Lade Daten …</div>
        </div>
        <div class="toolbar">
          <button data-preset="today">Heute</button>
          <button data-preset="yesterday">Gestern</button>
          <button data-preset="7d">7 Tage</button>
          <button data-preset="30d">30 Tage</button>
          <button data-preset="year">Dieses Jahr</button>
          <label>Von<input id="startDate" type="date"></label>
          <label>Bis<input id="endDate" type="date"></label>
          <label>Auflösung<select id="resolution"><option value="auto">Auto</option><option value="15m">15 Minuten</option><option value="hour">Stunde</option><option value="day">Tag</option></select></label>
          <label>Ansicht<select id="displayMode"><option value="groups">Gruppen</option><option value="individual">Einzeln</option></select></label>
          <div class="spacer"></div>
          <button id="manage">Verbraucher verwalten</button>
          <button id="backfill">Historie nachrechnen</button>
          <button id="csv">CSV</button>
          <button id="refresh">Aktualisieren</button>
        </div>
        <div id="content"><div class="loading">Daten werden geladen …</div></div>
        <div id="modalHost"></div>
      </div>`;

    this.shadowRoot.querySelectorAll("[data-preset]").forEach(btn => btn.addEventListener("click", () => this._setPreset(btn.dataset.preset)));
    this.shadowRoot.getElementById("refresh").addEventListener("click", () => this._refresh());
    this.shadowRoot.getElementById("csv").addEventListener("click", () => this._exportCsv());
    this.shadowRoot.getElementById("manage").addEventListener("click", () => this._navigate("/wattwer-config"));
    this.shadowRoot.getElementById("backfill").addEventListener("click", () => this._openBackfill());
    this.shadowRoot.getElementById("resolution").addEventListener("change", e => { this._resolution = e.target.value; this._refresh(); });
    this.shadowRoot.getElementById("displayMode").value = this._displayMode;
    this.shadowRoot.getElementById("displayMode").addEventListener("change", e => { this._displayMode = e.target.value; localStorage.setItem("wattwer.defaultDisplayMode", this._displayMode); this._renderCurrent(); });
    ["startDate","endDate"].forEach(id => this.shadowRoot.getElementById(id).addEventListener("change", () => { this._rangeMode = "custom"; this._markPreset(); this._refresh(); }));
  }

  _localDateString(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth()+1).padStart(2,"0");
    const d = String(date.getDate()).padStart(2,"0");
    return `${y}-${m}-${d}`;
  }

  _setPreset(mode, refresh=true) {
    this._rangeMode = mode;
    const now = new Date();
    let start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    let end = new Date(start); end.setDate(end.getDate()+1);
    if (mode === "yesterday") { end = start; start = new Date(start); start.setDate(start.getDate()-1); }
    if (mode === "7d") start.setDate(start.getDate()-6);
    if (mode === "30d") start.setDate(start.getDate()-29);
    if (mode === "year") start = new Date(now.getFullYear(),0,1);
    this.shadowRoot.getElementById("startDate").value = this._localDateString(start);
    const endInclusive = new Date(end); endInclusive.setDate(endInclusive.getDate()-1);
    this.shadowRoot.getElementById("endDate").value = this._localDateString(endInclusive);
    this._markPreset();
    if (refresh) this._refresh();
  }

  _markPreset() { this.shadowRoot.querySelectorAll("[data-preset]").forEach(btn => btn.classList.toggle("active", btn.dataset.preset === this._rangeMode)); }

  _range() {
    const s = this.shadowRoot.getElementById("startDate").value;
    const e = this.shadowRoot.getElementById("endDate").value;
    const start = new Date(`${s}T00:00:00`);
    const end = new Date(`${e}T00:00:00`); end.setDate(end.getDate()+1);
    return {start, end};
  }

  async _refresh(showLoading=true) {
    if (!this._hass || this._refreshing) return;
    this._refreshing = true;
    if (showLoading) this.shadowRoot.getElementById("status").textContent = "Lade Daten …";
    try {
      const {start,end} = this._range();
      const [history, summary] = await Promise.all([
        this._hass.callWS({type:"pv_energy_allocation/history", start:start.getTime(), end:end.getTime(), resolution:this._resolution}),
        this._hass.callWS({type:"pv_energy_allocation/summary"})
      ]);
      this._lastView = {history, summary, start, end};
      const items = this._displayItems(history);
      if (!items.some(x => x.id === this._selectedDisplay)) this._selectedDisplay = items[0]?.id || "";
      this._renderData(history, summary, start, end);
      this._setLiveStatus(history);
    } catch (err) {
      this.shadowRoot.getElementById("content").innerHTML = `<div class="error">${this._escape(String(err?.message || err))}</div>`;
      this.shadowRoot.getElementById("status").textContent = "Fehler";
    } finally { this._refreshing = false; }
  }

  async _refreshLive() {
    if (!this._hass || !this._lastView || this._liveRefreshing || this._refreshing) return;
    this._liveRefreshing = true;
    try {
      const summary = await this._hass.callWS({type:"pv_energy_allocation/summary"});
      const previous = this._lastView.summary || {};
      const oldQuarter = previous.last_15m?.start ?? null;
      const newQuarter = summary.last_15m?.start ?? null;
      const oldConfig = JSON.stringify([previous.consumer_metadata || {}, previous.groups || []]);
      const newConfig = JSON.stringify([summary.consumer_metadata || {}, summary.groups || []]);
      if ((newQuarter && newQuarter !== oldQuarter) || oldConfig !== newConfig) {
        this._liveRefreshing = false;
        await this._refresh(false);
        return;
      }
      this._lastView.summary = summary;
      this._renderData(this._lastView.history, summary, this._lastView.start, this._lastView.end);
      this._setLiveStatus(this._lastView.history);
    } catch (_err) {
      this.shadowRoot.getElementById("status").textContent = "Live-Aktualisierung gestört";
    } finally { this._liveRefreshing = false; }
  }

  _renderCurrent() {
    if (!this._lastView) return;
    const items = this._displayItems(this._lastView.history);
    if (!items.some(x => x.id === this._selectedDisplay)) this._selectedDisplay = items[0]?.id || "";
    this._renderData(this._lastView.history, this._lastView.summary, this._lastView.start, this._lastView.end);
  }

  _setLiveStatus(history) {
    const now = new Intl.DateTimeFormat(undefined,{hour:"2-digit",minute:"2-digit",second:"2-digit"}).format(new Date());
    this.shadowRoot.getElementById("status").textContent = `Live ${now} · ${this._resolutionLabel(history.resolution)} · ${history.records.length} Intervalle`;
  }

  _resolutionLabel(r) { return r === "15m" ? "15 Minuten" : r === "hour" ? "Stunden" : "Tage"; }
  _blank(consumers) { const o={}; Object.keys(consumers).forEach(c=>o[c]={total:0,pv:0,grid:0,battery:0}); return o; }

  _displayItems(history) {
    const consumers = history.consumers || {};
    if (this._displayMode === "individual" || !(history.groups || []).length) {
      return Object.entries(consumers).map(([id,label]) => ({id,label,members:[id],group:false}));
    }
    const assigned = new Set();
    const items = [];
    for (const group of history.groups || []) {
      const members = (group.members || []).filter(id => consumers[id]);
      if (!members.length) continue;
      members.forEach(id => assigned.add(id));
      items.push({id:group.id,label:group.name,members,group:true});
    }
    for (const [id,label] of Object.entries(consumers)) if (!assigned.has(id)) items.push({id,label,members:[id],group:false});
    return items;
  }

  _sumMembers(values, members) {
    const out={total:0,pv:0,grid:0,battery:0};
    for (const cid of members) ["total","pv","grid","battery"].forEach(s => out[s] += Number(values?.[cid]?.[s] || 0));
    return out;
  }

  _renderData(history, summary, start, end) {
    const totals = this._blank(history.consumers);
    let covered = 0, duration = 0;
    const todayStart = summary.today_start;
    const now = Date.now();
    const includesToday = start.getTime() <= now && end.getTime() > todayStart;
    const chartRecords = [];

    for (const rec of history.records) {
      if (includesToday && rec.start >= todayStart) {
        if (history.resolution === "15m") chartRecords.push(rec);
        continue;
      }
      this._addValues(totals, rec.values);
      covered += rec.coverage * rec.duration;
      duration += rec.duration;
      chartRecords.push(rec);
    }
    if (includesToday) {
      this._addValues(totals, summary.today);
      const elapsed = Math.max(0, (Math.min(end.getTime(), now) - Math.max(start.getTime(), todayStart))/1000);
      if (elapsed > 0) { covered += summary.today_coverage * elapsed; duration += elapsed; }
      if (history.resolution === "15m" && summary.current_15m?.values) {
        chartRecords.push({
          start:summary.current_15m.start,
          duration:Math.max(1,(now-summary.current_15m.start)/1000),
          coverage:Math.min(1, summary.current_15m.coverage_seconds/Math.max(1,(now-summary.current_15m.start)/1000)),
          values:summary.current_15m.values,
          partial:true
        });
      }
    }
    const coveragePct = duration > 0 ? covered/duration*100 : 0;
    const items = this._displayItems(history);
    const cards = items.map(item => this._summaryCard(item.label, this._sumMembers(totals,item.members), summary.battery_visible, item.group)).join("");
    const consumerOptions = items.map(item => `<option value="${this._escapeAttr(item.id)}" ${item.id===this._selectedDisplay?"selected":""}>${this._escape(item.label)}${item.group?" (Gruppe)":""}</option>`).join("");
    const selected = items.find(x => x.id === this._selectedDisplay) || items[0];
    const live = summary.live || {};
    const qualityLabels = {
      ok: "gültig",
      fallback_generator: "gültig · Erzeuger-Fallback",
      fallback_night_zero: "gültig · Nacht-Fallback",
      degraded_generator_proportional: "gültig · proportionaler Erzeuger-Fallback",
      invalid: "ungültig",
    };
    const liveQuality = live.valid ? (qualityLabels[live.quality] || "gültig") : "ungültig";

    this.shadowRoot.getElementById("content").innerHTML = `
      <div class="grid">${cards || '<div class="loading">Keine Verbraucher konfiguriert.</div>'}</div>
      <div class="main">
        <div class="card chartcard">
          <div class="charthead">
            <div><h3>Verlauf</h3><div class="legend"><span><span class="dot pv"></span>PV</span><span><span class="dot gridc"></span>Netz</span>${summary.battery_visible?'<span><span class="dot battery"></span>Batterie</span>':''}</div></div>
            <label>Verbraucher / Gruppe<select id="consumerSelect">${consumerOptions}</select></label>
          </div>
          <div class="chartwrap">${selected ? this._chart(chartRecords,selected,history.resolution,summary.battery_visible) : '<div class="loading">Keine Auswahl.</div>'}</div>
        </div>
        <div class="card side">
          <h3>Datenqualität</h3>
          <div class="diag">
            ${this._diagRow("Auswahl-Abdeckung", `${coveragePct.toFixed(1)} %`)}
            ${this._diagRow("Live-Snapshot", liveQuality)}
            ${this._diagRow("Netzanteil live", this._pct(live.grid_fraction))}
            ${this._diagRow("PV-Anteil live", this._pct(live.pv_fraction))}
            ${summary.battery_visible ? this._diagRow("Batterieanteil live", this._pct(live.battery_fraction)) : ""}
            ${this._diagRow("Bruttolast live", this._w(live.gross_load_w))}
            ${this._diagRow("Lokale PV direkt", this._w(live.direct_pv_w))}
            ${this._diagRow("PV-Erzeugung gemessen", this._w(live.generation_total_w))}
            ${this._diagRow("Bilanzfehler live", this._w(live.balance_error_w))}
            ${this._diagRow("Diagnose-Summensensor Δ", this._w(live.house_net_error_w))}
          </div>
          ${live.quality_notes?.length ? `<p class="muted">${live.quality_notes.map(x=>this._escape(x)).join(" · ")}</p>`:""}
          ${!live.valid && live.stale_entities?.length ? `<p class="muted">Ungültig/veraltet: ${live.stale_entities.map(x=>this._escape(x)).join(", ")}</p>`:""}
        </div>
      </div>`;

    const selector = this.shadowRoot.getElementById("consumerSelect");
    if (selector) selector.addEventListener("change", e => { this._selectedDisplay=e.target.value; this._renderCurrent(); });
  }

  _addValues(target, values) {
    Object.keys(target).forEach(cid => {
      if (!values?.[cid]) return;
      ["total","pv","grid","battery"].forEach(s => target[cid][s] += Number(values[cid][s] || 0));
    });
  }

  _summaryCard(label,v,batteryEnabled,isGroup=false) {
    const total = v.total || 0;
    const pv = total > 0 ? v.pv/total*100 : 0;
    const grid = total > 0 ? v.grid/total*100 : 0;
    const battery = total > 0 ? v.battery/total*100 : 0;
    return `<div class="card summary">
      <h3>${this._escape(label)}${isGroup?' <span class="muted">· Gruppe</span>':''}</h3>
      <div class="total">${this._energy(total)}</div>
      <div class="sources">
        <div class="metric"><div class="label">PV</div><div class="value">${this._energy(v.pv)} · ${pv.toFixed(1)}%</div></div>
        <div class="metric"><div class="label">Netz</div><div class="value">${this._energy(v.grid)} · ${grid.toFixed(1)}%</div></div>
        ${batteryEnabled?`<div class="metric"><div class="label">Batterie</div><div class="value">${this._energy(v.battery)} · ${battery.toFixed(1)}%</div></div>`:""}
      </div>
      <div class="bar"><span class="pv" style="width:${pv}%"></span><span class="gridc" style="width:${grid}%"></span>${batteryEnabled?`<span class="battery" style="width:${battery}%"></span>`:""}</div>
    </div>`;
  }

  _chart(records,item,resolution,batteryEnabled) {
    if (!records.length) return `<div class="loading">Für diesen Zeitraum sind noch keine Daten vorhanden.</div>`;
    const normalize = r => ({...r, display:this._sumMembers(r.values,item.members)});
    let points = records.map(normalize);
    const maxBars = 480;
    if (points.length > maxBars) {
      const group = Math.ceil(points.length/maxBars); const sampled=[];
      for (let i=0;i<points.length;i+=group) {
        const slice=points.slice(i,i+group); const v={total:0,pv:0,grid:0,battery:0}; let dur=0,cov=0;
        slice.forEach(r=>{["total","pv","grid","battery"].forEach(s=>v[s]+=Number(r.display[s]||0));dur+=r.duration;cov+=r.coverage*r.duration;});
        sampled.push({start:slice[0].start,duration:dur,coverage:dur?cov/dur:0,display:v,sampled:true});
      }
      points=sampled;
    }
    const width=1200,height=300,padL=58,padR=16,padT=15,padB=38;
    const innerW=width-padL-padR, innerH=height-padT-padB;
    const maxTotal=Math.max(...points.map(r=>Number(r.display?.total||0)),0.000001);
    const step=innerW/points.length, barW=Math.max(1,step*.78);
    const rects=points.map((r,i)=>{
      const v=r.display||{}; const pv=Number(v.pv||0),grid=Number(v.grid||0),bat=Number(v.battery||0),total=Number(v.total||0);
      const x=padL+i*step+(step-barW)/2; let y=padT+innerH; const seg=[];
      [[pv,"#f4b400","PV"],[grid,"#4285f4","Netz"],[bat,"#8e5bd9","Batterie"]].forEach(([val,color,name])=>{
        if (!batteryEnabled && name==="Batterie") return;
        const h=Number(val)/maxTotal*innerH; y-=h;
        if (h>0) seg.push(`<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${barW.toFixed(2)}" height="${h.toFixed(2)}" fill="${color}" rx="1"><title>${name}: ${this._energy(Number(val))}</title></rect>`);
      });
      return `<g><title>${this._dateTime(r.start)} · Gesamt ${this._energy(total)} · Abdeckung ${(r.coverage*100).toFixed(0)}%</title>${seg.join("")}</g>`;
    }).join("");
    let yLines=""; const ticks=5;
    for(let i=0;i<=ticks;i++){const y=padT+innerH-innerH*i/ticks;const val=maxTotal*i/ticks;yLines+=`<line x1="${padL}" x2="${width-padR}" y1="${y}" y2="${y}" stroke="var(--divider-color)" stroke-width="1"/><text x="${padL-8}" y="${y+4}" text-anchor="end" fill="var(--secondary-text-color)" font-size="11">${this._energyShort(val)}</text>`;}
    let xLabels=""; const labelCount=Math.min(8,points.length);
    for(let j=0;j<labelCount;j++){const idx=Math.min(points.length-1,Math.round(j*(points.length-1)/Math.max(1,labelCount-1)));const x=padL+(idx+.5)*step;xLabels+=`<text x="${x}" y="${height-12}" text-anchor="middle" fill="var(--secondary-text-color)" font-size="11">${this._axisLabel(points[idx].start,resolution)}</text>`;}
    return `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">${yLines}${rects}${xLabels}</svg>`;
  }

  _navigate(path) {
    window.history.pushState(null, "", path);
    window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
  }

  async _openManager() {
    try {
      const cfg = await this._hass.callWS({type:"pv_energy_allocation/config"});
      this._management = cfg;
      this._renderManagerModal();
    } catch (err) { this._showModalError("Verbraucher konnten nicht geladen werden", err); }
  }

  _renderManagerModal() {
    const cfg=this._management; if(!cfg)return;
    const consumers=(cfg.consumers||[]).map(x=>({...x}));
    const groups=(cfg.groups||[]).map(x=>({...x,members:[...(x.members||[])]}));
    const canManage=!!cfg.can_manage;
    const rows=consumers.map(c=>this._consumerRow(c,canManage)).join("");
    const groupRows=groups.map(g=>this._groupRow(g,consumers,canManage)).join("");
    const host=this.shadowRoot.getElementById("modalHost");
    host.innerHTML=`<div class="modalback"><div class="modal">
      <div class="modalhead"><div><h2>Verbraucher verwalten</h2><div class="muted">Stabile interne IDs schützen bestehende Historie und Long-Term Statistics.</div></div><button id="closeModal">Schließen</button></div>
      <div class="modalbody">
        <div class="section">
          <h3>Verbraucher</h3>
          <p class="notice">Umbenennen ändert nur die Anzeige. Beim Wechsel der Leistungs-Entity bleibt dieselbe interne Verbraucher-ID bestehen; alte Messdaten werden nicht gelöscht. Bestehende Verbraucher werden zur Datensicherheit deaktiviert statt aus der Historie entfernt.</p>
          <div class="consumerrow header"><span>Aktiv</span><span>Name</span><span>Leistungs-Entity</span><span>Rolle</span><span>Aktion</span></div>
          <div id="consumerRows">${rows}</div>
          ${canManage?'<button id="addConsumer" style="margin-top:10px">+ Verbraucher hinzufügen</button>':''}
        </div>
        <div class="section">
          <h3>Gruppen</h3>
          <p class="muted">Gruppen sind nur eine Auswertungsebene. Einzelhistorien bleiben unverändert; Gruppenwerte werden bei der Anzeige aus den Mitgliedern summiert.</p>
          <div id="groupRows">${groupRows || '<p class="muted">Noch keine Gruppe angelegt.</p>'}</div>
          ${canManage?'<button id="addGroup">+ Gruppe hinzufügen</button>':''}
        </div>
        ${!canManage?'<div class="notice">Nur Administratoren dürfen die Konfiguration ändern.</div>':''}
      </div>
      <div class="modalfoot"><button id="cancelManager">Abbrechen</button>${canManage?'<button id="saveManager" class="primary">Änderungen speichern</button>':''}</div>
    </div></div>`;
    host.querySelector("#closeModal").onclick=()=>this._closeModal();
    host.querySelector("#cancelManager").onclick=()=>this._closeModal();
    host.querySelectorAll("[data-remove-new]").forEach(btn=>btn.onclick=()=>btn.closest(".consumerrow").remove());
    host.querySelectorAll("[data-remove-group]").forEach(btn=>btn.onclick=()=>btn.closest(".grouprow").remove());
    if(canManage){
      host.querySelector("#addConsumer").onclick=()=>this._appendConsumerRow();
      host.querySelector("#addGroup").onclick=()=>this._appendGroupRow();
      host.querySelector("#saveManager").onclick=()=>this._saveManager();
    }
  }

  _consumerRow(c,canManage) {
    const saved=!!c.id;
    return `<div class="consumerrow" data-consumer-id="${this._escapeAttr(c.id||"")}">
      <input class="c-enabled" type="checkbox" ${c.enabled!==false?"checked":""} ${canManage?"":"disabled"} title="Aktiv">
      <input class="c-name" value="${this._escapeAttr(c.name||"")}" ${canManage?"":"disabled"} placeholder="Anzeigename">
      <input class="c-entity" value="${this._escapeAttr(c.entity_id||"")}" ${canManage?"":"disabled"} placeholder="sensor.xyz_power">
      <select class="c-role" ${canManage?"":"disabled"}><option value="normal" selected>Normal</option></select>
      ${!saved && canManage?'<button type="button" data-remove-new>Entfernen</button>':`<span class="muted">${c.enabled!==false?'deaktivierbar':'historisch erhalten'}</span>`}
    </div>`;
  }

  _groupRow(g,consumers,canManage) {
    const checks=consumers.map(c=>`<label><input type="checkbox" data-member="${this._escapeAttr(c.id)}" ${(g.members||[]).includes(c.id)?"checked":""} ${canManage?"":"disabled"}>${this._escape(c.name)}</label>`).join("");
    return `<div class="grouprow" data-group-id="${this._escapeAttr(g.id||"")}"><div class="grouptop"><input class="g-name" value="${this._escapeAttr(g.name||"")}" ${canManage?"":"disabled"} placeholder="Gruppenname">${canManage?'<button type="button" data-remove-group class="danger">Gruppe löschen</button>':''}</div><div class="members">${checks}</div></div>`;
  }

  _appendConsumerRow() {
    const box=this.shadowRoot.querySelector("#consumerRows");
    const wrap=document.createElement("div"); wrap.innerHTML=this._consumerRow({id:"",name:"",entity_id:"",role:"normal",enabled:true},true);
    const row=wrap.firstElementChild; box.appendChild(row); row.querySelector("[data-remove-new]").onclick=()=>row.remove(); row.querySelector(".c-name").focus();
    // Group member lists are intentionally rebuilt after saving; a brand-new
    // consumer can be grouped immediately after the automatic reload.
  }

  _appendGroupRow() {
    const consumers=this._collectConsumers(false);
    const box=this.shadowRoot.querySelector("#groupRows");
    if(box.querySelector(".muted") && !box.querySelector(".grouprow")) box.innerHTML="";
    const wrap=document.createElement("div"); wrap.innerHTML=this._groupRow({id:"",name:"",members:[]},consumers,true);
    const row=wrap.firstElementChild; box.appendChild(row); row.querySelector("[data-remove-group]").onclick=()=>row.remove(); row.querySelector(".g-name").focus();
  }

  _collectConsumers(validate=true) {
    const rows=[...this.shadowRoot.querySelectorAll("#consumerRows .consumerrow")];
    return rows.map(row=>({
      id:row.dataset.consumerId||"",
      name:row.querySelector(".c-name").value.trim(),
      entity_id:row.querySelector(".c-entity").value.trim(),
      role:row.querySelector(".c-role").value,
      enabled:row.querySelector(".c-enabled").checked,
    })).filter(x=>!validate || x.name || x.entity_id);
  }

  _collectGroups() {
    return [...this.shadowRoot.querySelectorAll("#groupRows .grouprow")].map(row=>({
      id:row.dataset.groupId||"",
      name:row.querySelector(".g-name").value.trim(),
      members:[...row.querySelectorAll("[data-member]:checked")].map(x=>x.dataset.member),
    }));
  }

  async _saveManager() {
    const button=this.shadowRoot.querySelector("#saveManager"); button.disabled=true; button.textContent="Speichere …";
    try {
      const consumers=this._collectConsumers(); const groups=this._collectGroups();
      if(consumers.some(x=>!x.name||!x.entity_id)) throw new Error("Jeder Verbraucher benötigt Name und Leistungs-Entity.");
      await this._hass.callWS({type:"pv_energy_allocation/config/update",consumers,groups});
      this._closeModal();
      this.shadowRoot.getElementById("status").textContent="Konfiguration gespeichert · Integration wird neu geladen …";
      await this._waitForReload();
      await this._refresh(false);
    } catch(err) {
      button.disabled=false; button.textContent="Änderungen speichern";
      alert(`Speichern fehlgeschlagen: ${String(err?.message||err)}`);
    }
  }

  async _waitForReload() {
    for(let i=0;i<12;i++){
      await new Promise(r=>setTimeout(r,1000));
      try{await this._hass.callWS({type:"pv_energy_allocation/summary"});return;}catch(_err){}
    }
  }

  async _openBackfill() {
    try {
      this._backfillStatus=await this._hass.callWS({type:"pv_energy_allocation/backfill/status"});
      const now=new Date(); const end=new Date(now.getFullYear(),now.getMonth(),now.getDate()); const start=new Date(end); start.setDate(start.getDate()-7);
      const last=this._backfillStatus.last;
      const host=this.shadowRoot.getElementById("modalHost");
      host.innerHTML=`<div class="modalback"><div class="modal" style="max-width:760px">
        <div class="modalhead"><div><h2>Historische Daten nachrechnen</h2><div class="muted">Rekonstruktion aus vorhandenen Recorder-Rohzuständen · das laufende Viertel wird automatisch ausgelassen</div></div><button id="closeModal">Schließen</button></div>
        <div class="modalbody">
          <div class="notice">Es können nur Zeiträume rekonstruiert werden, für die die benötigten Roh-Leistungssensoren noch im Recorder vorhanden sind. Wiederholte identische Sensormeldungen sind historisch nicht vollständig nachweisbar; Backfill-Daten erhalten deshalb eine eigene Abdeckungskennzeichnung. Der Vorgang verändert keine bereits gemessenen Live-Zähler.</div>
          <div class="toolbar" style="box-shadow:none;margin:16px 0 0;padding:0;background:transparent">
            <label>Von<input id="bfStart" type="date" value="${this._localDateString(start)}"></label>
            <label>Bis<input id="bfEnd" type="date" value="${this._localDateString(end)}"></label>
          </div>
          <div class="diag">
            ${this._diagRow("Archiv 15 min", String(this._backfillStatus.counts?.["15m"]||0))}
            ${this._diagRow("Archiv Stunden", String(this._backfillStatus.counts?.hour||0))}
            ${this._diagRow("Archiv Tage", String(this._backfillStatus.counts?.day||0))}
            ${this._diagRow("Konfigurationsrevisionen", String(this._backfillStatus.revision_count||0))}
            ${last?this._diagRow("Letzter Backfill", `${this._dateTime(last.completed_at)} · ${(Number(last.coverage||0)*100).toFixed(1)} % Abdeckung`):""}
          </div>
          <div id="bfProgress" class="progress" style="display:none"></div>
        </div>
        <div class="modalfoot"><button id="cancelBackfill">Abbrechen</button>${this._backfillStatus.can_run?'<button id="runBackfill" class="primary">Backfill starten</button>':''}</div>
      </div></div>`;
      host.querySelector("#closeModal").onclick=()=>this._closeModal(); host.querySelector("#cancelBackfill").onclick=()=>this._closeModal();
      if(this._backfillStatus.can_run)host.querySelector("#runBackfill").onclick=()=>this._runBackfill();
    } catch(err){this._showModalError("Backfill-Status konnte nicht geladen werden",err);}
  }

  async _runBackfill() {
    const startStr=this.shadowRoot.querySelector("#bfStart").value; const endStr=this.shadowRoot.querySelector("#bfEnd").value;
    let cursor=new Date(`${startStr}T00:00:00`).getTime(); const endDate=new Date(`${endStr}T00:00:00`); endDate.setDate(endDate.getDate()+1); const target=endDate.getTime();
    if(!Number.isFinite(cursor)||!Number.isFinite(target)||target<=cursor){alert("Ungültiger Zeitraum.");return;}
    const button=this.shadowRoot.querySelector("#runBackfill"); const cancel=this.shadowRoot.querySelector("#cancelBackfill"); const progress=this.shadowRoot.querySelector("#bfProgress");
    button.disabled=true; cancel.disabled=true; progress.style.display="block"; progress.textContent="Starte …";
    const maxDays=Math.max(1,Number(this._backfillStatus?.max_days_per_run||31)); let chunk=0; let weighted=0; let seconds=0;
    try{
      while(cursor<target){
        const chunkEnd=Math.min(target,cursor+maxDays*86400000); chunk++;
        progress.textContent+=`\nBlock ${chunk}: ${new Date(cursor).toLocaleDateString()} – ${new Date(chunkEnd-1).toLocaleDateString()} …`;
        const result=await this._hass.callWS({type:"pv_energy_allocation/backfill/run",start:cursor,end:chunkEnd});
        const span=Math.max(1,(result.end-result.start)/1000); weighted+=Number(result.coverage||0)*span; seconds+=span;
        progress.textContent+=` ${(Number(result.coverage||0)*100).toFixed(1)} % Abdeckung`;
        cursor=chunkEnd;
      }
      progress.textContent+=`\nFertig. Gesamt-Abdeckung: ${(seconds?weighted/seconds*100:0).toFixed(1)} %`;
      cancel.disabled=false; cancel.textContent="Schließen"; button.style.display="none";
      await this._refresh(false);
    }catch(err){progress.textContent+=`\nFEHLER: ${String(err?.message||err)}`;button.disabled=false;cancel.disabled=false;}
  }

  _closeModal(){this.shadowRoot.getElementById("modalHost").innerHTML="";}
  _showModalError(title,err){const host=this.shadowRoot.getElementById("modalHost");host.innerHTML=`<div class="modalback"><div class="modal" style="max-width:650px"><div class="modalhead"><h2>${this._escape(title)}</h2><button id="closeModal">Schließen</button></div><div class="modalbody"><div class="error">${this._escape(String(err?.message||err))}</div></div></div></div>`;host.querySelector("#closeModal").onclick=()=>this._closeModal();}

  _exportCsv() {
    if (!this._lastView) return;
    const {history,start,end}=this._lastView; const items=this._displayItems(history);
    const rows=[["Start","Intervall_s","Abdeckung_%","Typ","Verbraucher","Gesamt_kWh","PV_kWh","PV_%","Netz_kWh","Netz_%","Batterie_kWh","Batterie_%"]];
    for(const rec of history.records){for(const item of items){const v=this._sumMembers(rec.values,item.members);const total=Number(v.total||0),pv=Number(v.pv||0),grid=Number(v.grid||0),bat=Number(v.battery||0);const pct=x=>total>0?x/total*100:0;rows.push([new Date(rec.start).toISOString(),rec.duration,(rec.coverage*100).toFixed(2),item.group?"Gruppe":"Verbraucher",item.label,total.toFixed(6),pv.toFixed(6),pct(pv).toFixed(3),grid.toFixed(6),pct(grid).toFixed(3),bat.toFixed(6),pct(bat).toFixed(3)]);}}
    const esc=v=>`"${String(v).replaceAll('"','""')}"`; const csv=rows.map(r=>r.map(esc).join(';')).join('\n'); const blob=new Blob(["\ufeff"+csv],{type:"text/csv;charset=utf-8"}); const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`pv-verteilung_${this._localDateString(start)}_${this._localDateString(new Date(end.getTime()-86400000))}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  }

  _diagRow(label,value){return `<div class="diagrow"><span class="muted">${label}</span><strong>${value}</strong></div>`;}
  _pct(v){return v==null?"–":`${(Number(v)*100).toFixed(1)} %`;}
  _w(v){return v==null?"–":`${Number(v).toFixed(1)} W`;}
  _energy(kwh){kwh=Number(kwh||0);return kwh<1?`${(kwh*1000).toFixed(kwh<.1?1:0)} Wh`:`${kwh.toFixed(kwh<10?3:2)} kWh`;}
  _energyShort(kwh){kwh=Number(kwh||0);return kwh<1?`${Math.round(kwh*1000)}Wh`:`${kwh.toFixed(1)}kWh`;}
  _dateTime(ms){return new Intl.DateTimeFormat(undefined,{dateStyle:"short",timeStyle:"short"}).format(new Date(ms));}
  _axisLabel(ms,res){const d=new Date(ms);if(res==="15m"||res==="hour")return new Intl.DateTimeFormat(undefined,{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}).format(d);return new Intl.DateTimeFormat(undefined,{day:"2-digit",month:"2-digit",year:"2-digit"}).format(d);}
  _escape(s){return String(s).replace(/[&<>'"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));}
  _escapeAttr(s){return this._escape(s);}
}

if (!customElements.get("pv-energy-allocation-panel")) customElements.define("pv-energy-allocation-panel", PVEnergyAllocationPanel);
