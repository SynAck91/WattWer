class WattWerConfigPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._panel = null;
    this._initialized = false;
    this._cfg = null;
    this._tab = "consumers";
    this._selectedConsumer = null;
    this._selectedGenerator = null;
    this._selectedGroup = null;
    this._search = "";
    this._generatorSearch = "";
    this._busy = false;
    this._entityTarget = null;
    this._backfillStatus = null;
  }

  set hass(value) {
    this._hass = value;
    if (!this._initialized) {
      this._initialized = true;
      this._renderShell();
      this._load();
    }
  }
  get hass() { return this._hass; }
  set panel(value) { this._panel = value; }
  set narrow(value) { this._narrow = value; this.toggleAttribute("narrow", !!value); }

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; min-height:100%; background:var(--primary-background-color); color:var(--primary-text-color); }
        * { box-sizing:border-box; }
        button, input, select, textarea { font:inherit; }
        button { cursor:pointer; }
        .page { min-height:100vh; padding:24px; display:flex; justify-content:center; align-items:flex-start; }
        .shell { width:min(1180px,100%); background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:22px; overflow:hidden; box-shadow:0 18px 55px rgba(0,0,0,.28); }
        .head { display:flex; align-items:center; gap:14px; padding:19px 22px 16px; background:linear-gradient(180deg, color-mix(in srgb,var(--card-background-color) 92%,var(--primary-color) 8%),var(--card-background-color)); }
        .brand { width:48px; height:48px; border-radius:12px; object-fit:cover; box-shadow:0 5px 16px rgba(0,0,0,.25); }
        .titles { flex:1; min-width:0; }
        .titles h1 { margin:0; font-size:22px; letter-spacing:-.02em; }
        .titles p { margin:4px 0 0; color:var(--secondary-text-color); font-size:13px; }
        .iconbtn { width:40px; height:40px; border:0; border-radius:12px; background:transparent; color:var(--secondary-text-color); display:grid; place-items:center; }
        .iconbtn:hover { background:var(--secondary-background-color); color:var(--primary-text-color); }
        .tabs { display:grid; grid-template-columns:repeat(6,1fr); border-top:1px solid var(--divider-color); border-bottom:1px solid var(--divider-color); padding:0 20px; }
        .tab { position:relative; border:0; background:transparent; color:var(--secondary-text-color); padding:15px 10px; display:flex; align-items:center; justify-content:center; gap:8px; font-weight:600; }
        .tab.active { color:var(--primary-color); }
        .tab.active:after { content:""; position:absolute; left:14px; right:14px; bottom:-1px; height:3px; background:var(--primary-color); border-radius:3px 3px 0 0; }
        .body { padding:18px; min-height:570px; }
        .split { display:grid; grid-template-columns:minmax(330px,.92fr) minmax(390px,1.08fr); gap:16px; }
        .pane { border:1px solid var(--divider-color); border-radius:16px; background:color-mix(in srgb,var(--card-background-color) 96%,var(--primary-color) 4%); overflow:hidden; min-width:0; }
        .panehead { padding:15px 16px 10px; display:flex; align-items:flex-start; gap:10px; }
        .panehead .grow { flex:1; }
        .panehead h2 { margin:0; font-size:18px; }
        .panehead p { margin:4px 0 0; color:var(--secondary-text-color); font-size:12px; line-height:1.35; }
        .primary { border:0; background:var(--primary-color); color:var(--text-primary-color,#fff); padding:10px 14px; border-radius:11px; font-weight:650; box-shadow:0 3px 10px color-mix(in srgb,var(--primary-color) 25%,transparent); }
        .primary:disabled { opacity:.5; cursor:default; }
        .secondary { border:1px solid var(--divider-color); background:var(--secondary-background-color); color:var(--primary-text-color); padding:10px 14px; border-radius:11px; font-weight:600; }
        .danger { border:1px solid color-mix(in srgb,var(--error-color) 70%,var(--divider-color)); background:transparent; color:var(--error-color); padding:10px 14px; border-radius:11px; font-weight:600; }
        .searchrow { padding:0 12px 10px; display:flex; gap:8px; }
        .search { flex:1; display:flex; align-items:center; gap:8px; border:1px solid var(--divider-color); border-radius:11px; padding:0 10px; background:var(--secondary-background-color); }
        .search input { width:100%; border:0; outline:0; padding:10px 0; background:transparent; color:var(--primary-text-color); }
        .list { padding:0 10px 12px; display:grid; gap:7px; max-height:475px; overflow:auto; }
        .item { border:1px solid var(--divider-color); border-radius:12px; padding:10px 11px; display:grid; grid-template-columns:42px minmax(0,1fr) auto 24px; gap:10px; align-items:center; background:var(--card-background-color); cursor:pointer; }
        .item:hover { border-color:color-mix(in srgb,var(--primary-color) 45%,var(--divider-color)); }
        .item.selected { border-color:var(--primary-color); box-shadow:inset 0 0 0 1px var(--primary-color); background:color-mix(in srgb,var(--card-background-color) 92%,var(--primary-color) 8%); }
        .avatar { width:40px; height:40px; border-radius:50%; display:grid; place-items:center; background:color-mix(in srgb,var(--primary-color) 18%,var(--secondary-background-color)); color:var(--primary-color); }
        .avatar.fw { background:color-mix(in srgb,#ff9800 20%,var(--secondary-background-color)); color:#ff9800; }
        .avatar.off { background:var(--secondary-background-color); color:var(--disabled-text-color); }
        .itemtitle { font-weight:650; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .sub { color:var(--secondary-text-color); font-size:11px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-top:3px; }
        .badges { display:flex; flex-direction:column; align-items:flex-end; gap:4px; }
        .badge { font-size:10px; border-radius:999px; padding:3px 7px; background:var(--secondary-background-color); color:var(--secondary-text-color); white-space:nowrap; }
        .badge.ok { background:color-mix(in srgb,#16a34a 18%,var(--card-background-color)); color:#39d271; }
        .badge.role { background:color-mix(in srgb,var(--primary-color) 18%,var(--card-background-color)); color:var(--primary-color); }
        .editor { padding:0 16px 16px; }
        .editorTitle { display:flex; align-items:center; gap:10px; padding:6px 0 12px; border-bottom:1px solid var(--divider-color); margin-bottom:14px; }
        .editorTitle h2 { margin:0; font-size:20px; }
        .editorTitle .grow { flex:1; }
        .switchline { display:flex; align-items:center; gap:9px; font-size:13px; }
        .toggle { position:relative; width:44px; height:24px; display:inline-block; }
        .toggle input { opacity:0; width:0; height:0; }
        .slider { position:absolute; inset:0; border-radius:24px; background:var(--disabled-color,#777); transition:.15s; }
        .slider:before { content:""; position:absolute; width:18px; height:18px; left:3px; top:3px; border-radius:50%; background:white; transition:.15s; box-shadow:0 1px 4px rgba(0,0,0,.25); }
        .toggle input:checked + .slider { background:var(--primary-color); }
        .toggle input:checked + .slider:before { transform:translateX(20px); }
        .section { border:1px solid var(--divider-color); border-radius:13px; padding:12px; margin:11px 0; }
        .sectionTitle { display:flex; align-items:center; gap:7px; font-weight:650; margin-bottom:10px; font-size:13px; }
        .formgrid { display:grid; grid-template-columns:150px minmax(0,1fr); gap:10px 12px; align-items:center; }
        .formgrid label { color:var(--secondary-text-color); font-size:12px; }
        input[type=text], input[type=number], input[type=date], select, textarea { width:100%; border:1px solid var(--divider-color); border-radius:9px; background:var(--secondary-background-color); color:var(--primary-text-color); padding:9px 10px; outline:0; }
        input:focus, select:focus, textarea:focus { border-color:var(--primary-color); box-shadow:0 0 0 1px var(--primary-color); }
        textarea { min-height:68px; resize:vertical; }
        .entityline { display:flex; gap:7px; }
        .entityline input { flex:1; }
        .help { color:var(--secondary-text-color); font-size:11px; line-height:1.4; margin-top:5px; }
        .foot { display:flex; justify-content:space-between; align-items:center; gap:10px; padding-top:14px; }
        .actions { display:flex; justify-content:flex-end; gap:9px; }
        .notice { margin:0 18px 18px; border:1px solid color-mix(in srgb,var(--primary-color) 40%,var(--divider-color)); background:color-mix(in srgb,var(--primary-color) 10%,var(--card-background-color)); border-radius:12px; padding:11px 13px; display:flex; gap:10px; color:var(--secondary-text-color); font-size:12px; line-height:1.45; }
        .notice strong { color:var(--primary-text-color); }
        .empty { padding:45px 20px; color:var(--secondary-text-color); text-align:center; }
        .settings { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
        .settingCard { border:1px solid var(--divider-color); border-radius:15px; padding:15px; background:var(--card-background-color); }
        .settingCard h3 { margin:0 0 4px; font-size:15px; }
        .settingCard p { margin:0 0 12px; font-size:11px; color:var(--secondary-text-color); }
        .settingCard .field { margin:10px 0; }
        .settingCard .field > label { display:block; font-size:11px; color:var(--secondary-text-color); margin-bottom:5px; }
        .groupMembers { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px; }
        .member { display:flex; align-items:center; gap:8px; padding:9px; border:1px solid var(--divider-color); border-radius:9px; font-size:12px; }
        .member input { width:17px; height:17px; }
        .modalback { position:fixed; inset:0; z-index:50; background:rgba(0,0,0,.58); display:flex; justify-content:center; align-items:flex-start; padding:6vh 16px; }
        .modal { width:min(720px,100%); max-height:82vh; background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:16px; overflow:hidden; box-shadow:0 20px 60px rgba(0,0,0,.45); }
        .modalhead { padding:15px 16px; border-bottom:1px solid var(--divider-color); display:flex; align-items:center; gap:10px; }
        .modalhead h3 { margin:0; flex:1; }
        .modalbody { padding:12px; max-height:65vh; overflow:auto; }
        .entityItem { padding:10px 11px; border-bottom:1px solid var(--divider-color); cursor:pointer; }
        .entityItem:hover { background:var(--secondary-background-color); }
        .entityItem strong { display:block; font-size:13px; }
        .entityItem span { color:var(--secondary-text-color); font-size:11px; }
        .progress { white-space:pre-wrap; font:12px ui-monospace,monospace; border-radius:10px; background:var(--secondary-background-color); padding:12px; margin-top:12px; }
        .topmessage { margin:0 18px 12px; border-radius:11px; padding:9px 12px; font-size:12px; display:none; }
        .topmessage.show { display:block; }
        .topmessage.ok { background:color-mix(in srgb,#16a34a 15%,var(--card-background-color)); color:#43d77a; }
        .topmessage.err { background:color-mix(in srgb,var(--error-color) 15%,var(--card-background-color)); color:var(--error-color); }
        @media(max-width:850px){ .page{padding:10px}.tabs{grid-template-columns:repeat(6,auto);overflow:auto;padding:0}.tab{font-size:12px}.split{grid-template-columns:1fr}.settings{grid-template-columns:1fr}.formgrid{grid-template-columns:1fr}.groupMembers{grid-template-columns:1fr}.list{max-height:310px}.head{padding:14px}.titles p{display:none}.body{padding:10px}.notice{margin:0 10px 10px} }
      </style>
      <div class="page">
        <main class="shell">
          <div class="head">
            <img class="brand" src="/pv_energy_allocation_static/wattwer-icon.png" alt="WattWer">
            <div class="titles"><h1>WattWer Optionen</h1><p>Verbraucher, PV-Erzeuger, Gruppen und Messquellen für die Energiezuordnung verwalten.</p></div>
            <button class="iconbtn" id="help" title="Hinweise"><ha-icon icon="mdi:help-circle-outline"></ha-icon></button>
            <button class="iconbtn" id="close" title="Schließen"><ha-icon icon="mdi:close"></ha-icon></button>
          </div>
          <nav class="tabs">
            ${this._tabButton("consumers","mdi:transmission-tower-import","Verbraucher")}
            ${this._tabButton("generators","mdi:solar-power","PV-Erzeugung")}
            ${this._tabButton("groups","mdi:account-group-outline","Gruppen")}
            ${this._tabButton("general","mdi:cog-outline","Allgemein")}
            ${this._tabButton("backfill","mdi:archive-clock-outline","Backfill")}
            ${this._tabButton("display","mdi:monitor-dashboard","Anzeige")}
          </nav>
          <div id="message" class="topmessage"></div>
          <div class="body" id="body"><div class="empty">WattWer-Konfiguration wird geladen …</div></div>
          <div class="notice"><ha-icon icon="mdi:information-outline"></ha-icon><div><strong>Datensicherheit:</strong> Eine Umbenennung, Gruppierung oder Änderung der Mess-Entity behält die stabile interne Verbraucher-ID. Bestehende historische Energie- und Statistikdaten werden dadurch nicht gelöscht.</div></div>
        </main>
        <div id="modalHost"></div>
      </div>`;
    this.shadowRoot.querySelectorAll(".tab").forEach(b => b.addEventListener("click", () => this._setTab(b.dataset.tab)));
    this.shadowRoot.getElementById("close").onclick = () => this._navigate("/config/integrations/integration/pv_energy_allocation");
    this.shadowRoot.getElementById("help").onclick = () => this._showHelp();
  }

  _tabButton(id, icon, label) {
    return `<button class="tab ${this._tab===id?"active":""}" data-tab="${id}"><ha-icon icon="${icon}"></ha-icon><span>${label}</span></button>`;
  }

  _navigate(path) {
    window.history.pushState(null, "", path);
    window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
  }

  async _load(showMessage=false) {
    try {
      this._cfg = await this._hass.callWS({ type:"pv_energy_allocation/config" });
      this._selectedConsumer ||= this._cfg.consumers?.[0]?.id || null;
      this._selectedGenerator ||= this._cfg.generators?.[0]?.id || null;
      this._selectedGroup ||= this._cfg.groups?.[0]?.id || null;
      if (showMessage) this._message("Konfiguration aktualisiert.", true);
      this._render();
    } catch (err) {
      this.shadowRoot.getElementById("body").innerHTML = `<div class="empty">Konfiguration konnte nicht geladen werden:<br>${this._esc(String(err?.message||err))}</div>`;
    }
  }

  _setTab(tab) {
    if (this._cfg) {
      // Draft rows only exist client-side until explicitly saved. Switching
      // sections discards them so an incomplete draft can never block saving
      // an unrelated group or global setting.
      this._cfg.consumers = (this._cfg.consumers || []).filter(x => !String(x.id || "").startsWith("__new__"));
      this._cfg.groups = (this._cfg.groups || []).filter(x => !String(x.id || "").startsWith("__new__"));
      this._cfg.generators = (this._cfg.generators || []).filter(x => !String(x.id || "").startsWith("__new__"));
    }
    this._tab = tab;
    this._selectedConsumer = this._cfg?.consumers?.[0]?.id || this._selectedConsumer;
    this._selectedGenerator = this._cfg?.generators?.[0]?.id || this._selectedGenerator;
    this._selectedGroup = this._cfg?.groups?.[0]?.id || this._selectedGroup;
    this.shadowRoot.querySelectorAll(".tab").forEach(x => x.classList.toggle("active", x.dataset.tab===tab));
    this._render();
  }

  _render() {
    if (!this._cfg) return;
    if (this._tab === "consumers") this._renderConsumers();
    else if (this._tab === "generators") this._renderGenerators();
    else if (this._tab === "groups") this._renderGroups();
    else if (this._tab === "general") this._renderGeneral();
    else if (this._tab === "backfill") this._renderBackfill();
    else this._renderDisplay();
  }

  _renderConsumers() {
    const body=this.shadowRoot.getElementById("body");
    const all=(this._cfg.consumers||[]);
    const filter=this._search.trim().toLowerCase();
    const visible=all.filter(c=>!filter || `${c.name} ${c.entity_id}`.toLowerCase().includes(filter));
    let current=all.find(c=>c.id===this._selectedConsumer);
    if(!current && all.length){current=all[0];this._selectedConsumer=current.id;}
    body.innerHTML=`<div class="split">
      <section class="pane">
        <div class="panehead"><div class="grow"><h2>Verbraucher</h2><p>Einzelne Verbraucher verwalten, umbenennen oder deaktivieren.</p></div>${this._cfg.can_manage?'<button class="primary" id="addConsumer">+ Verbraucher hinzufügen</button>':''}</div>
        <div class="searchrow"><div class="search"><ha-icon icon="mdi:magnify"></ha-icon><input id="consumerSearch" placeholder="Verbraucher suchen…" value="${this._attr(this._search)}"></div></div>
        <div class="list">${visible.map(c=>this._consumerItem(c)).join("") || '<div class="empty">Keine Verbraucher gefunden.</div>'}</div>
      </section>
      <section class="pane">${current?this._consumerEditor(current):'<div class="empty">Noch kein Verbraucher konfiguriert.</div>'}</section>
    </div>`;
    body.querySelector("#consumerSearch")?.addEventListener("input",e=>{this._search=e.target.value;this._renderConsumers();});
    body.querySelector("#addConsumer")?.addEventListener("click",()=>this._addConsumerDraft());
    body.querySelectorAll("[data-consumer]").forEach(row=>row.onclick=()=>{this._selectedConsumer=row.dataset.consumer;this._renderConsumers();});
    this._wireConsumerEditor(current);
  }

  _consumerItem(c) {
    const selected=c.id===this._selectedConsumer;
    return `<div class="item ${selected?"selected":""}" data-consumer="${this._attr(c.id)}">
      <div class="avatar ${c.enabled===false?"off":""}"><ha-icon icon="${this._attr(c.icon||"mdi:flash")}"></ha-icon></div>
      <div><div class="itemtitle">${this._esc(c.name)}</div><div class="sub">${this._esc(c.entity_id)}</div></div>
      <div class="badges"><span class="badge ${c.enabled!==false?"ok":""}">${c.enabled!==false?"Aktiv":"Deaktiviert"}</span></div>
      <ha-icon icon="mdi:chevron-right"></ha-icon>
    </div>`;
  }

  _consumerEditor(c) {
    const isNew=!c.id || c.id.startsWith("__new__");
    return `<div class="panehead"><div class="grow"><h2>Verbraucher bearbeiten</h2><p>Name und Mess-Entity des Verbrauchers anpassen.</p></div></div>
      <div class="editor" data-editor-consumer="${this._attr(c.id)}">
        <div class="editorTitle"><div class="avatar"><ha-icon id="consumerIconPreview" icon="${this._attr(c.icon||"mdi:flash")}"></ha-icon></div><div class="grow"><h2>${this._esc(c.name||"Neuer Verbraucher")}</h2><div class="sub">${isNew?"Neue stabile ID wird beim Speichern erzeugt":`Interne ID: ${this._esc(c.id)}`}</div></div><div class="switchline"><label class="toggle"><input id="cEnabled" type="checkbox" ${c.enabled!==false?"checked":""}><span class="slider"></span></label>Aktiv</div></div>
        <div class="section"><div class="sectionTitle"><ha-icon icon="mdi:information-outline"></ha-icon>Basisdaten</div><div class="formgrid">
          <label>Name</label><input id="cName" type="text" value="${this._attr(c.name||"")}" placeholder="z. B. Wärmepumpe">
          <label>Icon</label><div class="entityline"><input id="cIcon" type="text" value="${this._attr(c.icon||"mdi:flash")}" placeholder="mdi:flash"><button class="secondary" id="iconDefaults">Vorschläge</button></div>
          <label>Beschreibung</label><input id="cDescription" type="text" value="${this._attr(c.description||"")}" placeholder="optional">
        </div></div>
        <div class="section"><div class="sectionTitle"><ha-icon icon="mdi:flash-outline"></ha-icon>Messung</div><div class="formgrid">
          <label>Leistung (W)</label><div class="entityline"><input id="cEntity" type="text" value="${this._attr(c.entity_id||"")}" placeholder="sensor.xyz_power"><button class="secondary" id="browseConsumerEntity">Durchsuchen</button></div>
          <label>Negativwerte</label><div><label class="switchline"><input type="checkbox" checked disabled> Nicht als Verbrauch zählen</label><div class="help">Negative Wirkleistung wird energietechnisch nicht als positiver Geräteverbrauch integriert.</div></div>
        </div></div>
        <div class="foot"><div>${isNew?'<button class="danger" id="discardConsumer">Verwerfen</button>':'<button class="danger" id="deactivateConsumer">Deaktivieren</button>'}</div><div class="actions"><button class="secondary" id="resetConsumer">Zurücksetzen</button><button class="primary" id="saveConsumer">Speichern</button></div></div>
      </div>`;
  }

  _wireConsumerEditor(c) {
    if(!c)return;
    const root=this.shadowRoot.getElementById("body");
    const name=root.querySelector("#cName"), icon=root.querySelector("#cIcon");
    name?.addEventListener("input",()=>{root.querySelector(".editorTitle h2").textContent=name.value||"Neuer Verbraucher";});
    icon?.addEventListener("input",()=>root.querySelector("#consumerIconPreview")?.setAttribute("icon",icon.value||"mdi:flash"));
    root.querySelector("#browseConsumerEntity")?.addEventListener("click",()=>this._openEntityBrowser(value=>{root.querySelector("#cEntity").value=value;}));
    root.querySelector("#iconDefaults")?.addEventListener("click",()=>this._openIconChooser(value=>{root.querySelector("#cIcon").value=value;root.querySelector("#consumerIconPreview")?.setAttribute("icon",value);}));
    root.querySelector("#saveConsumer")?.addEventListener("click",()=>this._saveCurrentConsumer());
    root.querySelector("#resetConsumer")?.addEventListener("click",()=>this._renderConsumers());
    root.querySelector("#deactivateConsumer")?.addEventListener("click",()=>{root.querySelector("#cEnabled").checked=false;this._saveCurrentConsumer();});
    root.querySelector("#discardConsumer")?.addEventListener("click",()=>{this._cfg.consumers=this._cfg.consumers.filter(x=>x.id!==c.id);this._selectedConsumer=this._cfg.consumers[0]?.id||null;this._renderConsumers();});
  }

  _addConsumerDraft() {
    const id=`__new__${Date.now()}`;
    this._cfg.consumers.push({id,name:"Neuer Verbraucher",entity_id:"",role:"normal",enabled:true,icon:"mdi:flash",description:""});
    this._selectedConsumer=id; this._search=""; this._renderConsumers();
  }

  _readCurrentConsumer() {
    const root=this.shadowRoot.getElementById("body");
    const old=this._cfg.consumers.find(x=>x.id===this._selectedConsumer);
    if(!old)return null;
    return {...old,
      id:old.id.startsWith("__new__")?"":old.id,
      name:root.querySelector("#cName").value.trim(),
      entity_id:root.querySelector("#cEntity").value.trim(),
      icon:root.querySelector("#cIcon").value.trim()||"mdi:flash",
      description:root.querySelector("#cDescription").value.trim(),
      role:"normal",
      enabled:root.querySelector("#cEnabled").checked,
    };
  }

  async _saveCurrentConsumer() {
    if(this._busy)return;
    const updated=this._readCurrentConsumer(); if(!updated)return;
    if(!updated.name||!updated.entity_id){this._message("Name und Leistungs-Entity sind erforderlich.",false);return;}
    const originalId=this._selectedConsumer;
    const consumers=this._cfg.consumers.map(x=>x.id===originalId?updated:x).map(x=>({...x,id:x.id?.startsWith("__new__")?"":x.id}));
    await this._saveConsumersGroups(consumers,this._cfg.groups,"Verbraucher gespeichert.");
  }

  _renderGenerators() {
    const body=this.shadowRoot.getElementById("body");
    const all=(this._cfg.generators||[]);
    const filter=this._generatorSearch.trim().toLowerCase();
    const visible=all.filter(g=>!filter || `${g.name} ${g.entity_id} ${g.fallback_entity_id||""}`.toLowerCase().includes(filter));
    let current=all.find(g=>g.id===this._selectedGenerator);
    if(!current&&all.length){current=all[0];this._selectedGenerator=current.id;}
    body.innerHTML=`<div class="split">
      <section class="pane">
        <div class="panehead"><div class="grow"><h2>PV-Erzeugung</h2><p>Beliebig viele PV-Erzeuger und lokale Erzeugungszweige verwalten.</p></div>${this._cfg.can_manage?'<button class="primary" id="addGenerator">+ PV-Erzeuger</button>':''}</div>
        <div class="searchrow"><div class="search"><ha-icon icon="mdi:magnify"></ha-icon><input id="generatorSearch" placeholder="PV-Erzeuger suchen…" value="${this._attr(this._generatorSearch)}"></div></div>
        <div class="list">${visible.map(g=>this._generatorItem(g)).join("") || '<div class="empty">Noch kein PV-Erzeuger konfiguriert.</div>'}</div>
      </section>
      <section class="pane">${current?this._generatorEditor(current):'<div class="empty">PV-Erzeuger auswählen oder hinzufügen.</div>'}</section>
    </div>`;
    body.querySelector("#generatorSearch")?.addEventListener("input",e=>{this._generatorSearch=e.target.value;this._renderGenerators();});
    body.querySelector("#addGenerator")?.addEventListener("click",()=>this._addGeneratorDraft());
    body.querySelectorAll("[data-generator]").forEach(row=>row.onclick=()=>{this._selectedGenerator=row.dataset.generator;this._renderGenerators();});
    this._wireGeneratorEditor(current);
  }

  _generatorItem(g){
    const selected=g.id===this._selectedGenerator;
    const target=g.role==="direct_consumer"?(this._cfg.consumers.find(c=>c.id===g.consumer_id)?.name||"Lokaler Verbraucher"):"Hauptbus";
    return `<div class="item ${selected?"selected":""}" data-generator="${this._attr(g.id)}">
      <div class="avatar ${g.enabled===false?"off":""}"><ha-icon icon="${this._attr(g.icon||"mdi:solar-power")}"></ha-icon></div>
      <div><div class="itemtitle">${this._esc(g.name)}</div><div class="sub">${this._esc(g.entity_id)}</div></div>
      <div class="badges"><span class="badge ${g.enabled!==false?"ok":""}">${g.enabled!==false?"Aktiv":"Deaktiviert"}</span><span class="badge role">${this._esc(target)}</span></div>
      <ha-icon icon="mdi:chevron-right"></ha-icon>
    </div>`;
  }

  _generatorEditor(g){
    const isNew=!g.id||g.id.startsWith("__new__");
    const consumers=(this._cfg.consumers||[]).filter(c=>c.enabled!==false);
    return `<div class="panehead"><div class="grow"><h2>PV-Erzeuger bearbeiten</h2><p>Messquelle, Fallback und elektrische Zuordnung festlegen.</p></div></div>
      <div class="editor" data-editor-generator="${this._attr(g.id)}">
        <div class="editorTitle"><div class="avatar"><ha-icon id="generatorIconPreview" icon="${this._attr(g.icon||"mdi:solar-power")}"></ha-icon></div><div class="grow"><h2>${this._esc(g.name||"Neuer PV-Erzeuger")}</h2><div class="sub">${isNew?"Neue stabile ID wird beim Speichern erzeugt":`Interne ID: ${this._esc(g.id)}`}</div></div><div class="switchline"><label class="toggle"><input id="gEnabled" type="checkbox" ${g.enabled!==false?"checked":""}><span class="slider"></span></label>Aktiv</div></div>
        <div class="section"><div class="sectionTitle"><ha-icon icon="mdi:information-outline"></ha-icon>Basisdaten</div><div class="formgrid">
          <label>Name</label><input id="gName" type="text" value="${this._attr(g.name||"")}" placeholder="z. B. Dach Süd">
          <label>Icon</label><div class="entityline"><input id="gIcon" type="text" value="${this._attr(g.icon||"mdi:solar-power")}" placeholder="mdi:solar-power"><button class="secondary" id="generatorIconDefaults">Vorschläge</button></div>
          <label>Beschreibung</label><input id="gDescription" type="text" value="${this._attr(g.description||"")}" placeholder="optional">
        </div></div>
        <div class="section"><div class="sectionTitle"><ha-icon icon="mdi:solar-panel"></ha-icon>Messung</div><div class="formgrid">
          <label>PV-Leistung (W)</label><div class="entityline"><input id="gEntity" type="text" value="${this._attr(g.entity_id||"")}" placeholder="sensor.pv_power"><button class="secondary" id="browseGeneratorEntity">Durchsuchen</button></div>
          <label>Fallback-Sensor</label><div class="entityline"><input id="gFallback" type="text" value="${this._attr(g.fallback_entity_id||"")}" placeholder="optional"><button class="secondary" id="browseGeneratorFallback">Durchsuchen</button></div>
          <label>Max. Sensoralter (s)</label><input id="gMaxAge" type="number" min="5" max="3600" step="1" value="${Number(g.max_age||180)}">
          <label>Nachts 0 W annehmen</label><div class="switchline"><label class="toggle"><input id="gNightZero" type="checkbox" ${g.night_zero!==false?"checked":""}><span class="slider"></span></label><span>bei fehlender Messung unter Horizont</span></div>
        </div><div class="help">Der Fallback-Sensor wird verwendet, wenn er frischer als die primäre Messung ist. Ein Nacht-Nullwert wird nur angewendet, wenn Home Assistant <code>sun.sun = below_horizon</code> kennt.</div></div>
        <div class="section"><div class="sectionTitle"><ha-icon icon="mdi:transmission-tower"></ha-icon>Elektrische Zuordnung</div><div class="formgrid">
          <label>Einbindung</label><select id="gRole"><option value="main_bus" ${g.role!=="direct_consumer"?"selected":""}>Gemeinsamer Hauptbus</option><option value="direct_consumer" ${g.role==="direct_consumer"?"selected":""}>Lokal bei einem Verbraucher</option></select>
          <label id="gConsumerLabel">Lokaler Verbraucher</label><select id="gConsumer">${consumers.map(c=>`<option value="${this._attr(c.id)}" ${c.id===g.consumer_id?"selected":""}>${this._esc(c.name)}</option>`).join("")}</select>
        </div><div class="help">„Lokal“ bedeutet: Der Erzeuger deckt zuerst den gewählten Verbraucher; nur ein Überschuss fließt in den gemeinsamen Quellenmix. Das ist nur verwenden, wenn die Messpunkt-Topologie dies tatsächlich hergibt.</div></div>
        <div class="foot"><div>${isNew?'<button class="danger" id="discardGenerator">Verwerfen</button>':'<button class="danger" id="deactivateGenerator">Deaktivieren</button>'}</div><div class="actions"><button class="secondary" id="resetGenerator">Zurücksetzen</button><button class="primary" id="saveGenerator">Speichern</button></div></div>
      </div>`;
  }

  _wireGeneratorEditor(g){
    if(!g)return;
    const root=this.shadowRoot.getElementById("body");
    const name=root.querySelector("#gName"),icon=root.querySelector("#gIcon"),role=root.querySelector("#gRole"),target=root.querySelector("#gConsumer"),targetLabel=root.querySelector("#gConsumerLabel");
    const roleState=()=>{const local=role.value==="direct_consumer";target.disabled=!local;target.style.opacity=local?"1":".45";targetLabel.style.opacity=local?"1":".45";};
    role?.addEventListener("change",roleState);roleState();
    name?.addEventListener("input",()=>{root.querySelector(".editorTitle h2").textContent=name.value||"Neuer PV-Erzeuger";});
    icon?.addEventListener("input",()=>root.querySelector("#generatorIconPreview")?.setAttribute("icon",icon.value||"mdi:solar-power"));
    root.querySelector("#browseGeneratorEntity")?.addEventListener("click",()=>this._openEntityBrowser(v=>{root.querySelector("#gEntity").value=v;}));
    root.querySelector("#browseGeneratorFallback")?.addEventListener("click",()=>this._openEntityBrowser(v=>{root.querySelector("#gFallback").value=v;}));
    root.querySelector("#generatorIconDefaults")?.addEventListener("click",()=>this._openIconChooser(v=>{root.querySelector("#gIcon").value=v;root.querySelector("#generatorIconPreview")?.setAttribute("icon",v);}));
    root.querySelector("#saveGenerator")?.addEventListener("click",()=>this._saveCurrentGenerator());
    root.querySelector("#resetGenerator")?.addEventListener("click",()=>this._renderGenerators());
    root.querySelector("#deactivateGenerator")?.addEventListener("click",()=>{root.querySelector("#gEnabled").checked=false;this._saveCurrentGenerator();});
    root.querySelector("#discardGenerator")?.addEventListener("click",()=>{this._cfg.generators=this._cfg.generators.filter(x=>x.id!==g.id);this._selectedGenerator=this._cfg.generators[0]?.id||null;this._renderGenerators();});
  }

  _addGeneratorDraft(){
    const id=`__new__${Date.now()}`;
    this._cfg.generators=this._cfg.generators||[];
    this._cfg.generators.push({id,name:"Neuer PV-Erzeuger",entity_id:"",fallback_entity_id:"",role:"main_bus",consumer_id:null,enabled:true,night_zero:true,max_age:180,icon:"mdi:solar-power",description:""});
    this._selectedGenerator=id;this._generatorSearch="";this._renderGenerators();
  }

  _readCurrentGenerator(){
    const root=this.shadowRoot.getElementById("body"),old=this._cfg.generators.find(x=>x.id===this._selectedGenerator);if(!old)return null;
    const role=root.querySelector("#gRole").value;
    return {...old,id:old.id.startsWith("__new__")?"":old.id,name:root.querySelector("#gName").value.trim(),entity_id:root.querySelector("#gEntity").value.trim(),fallback_entity_id:root.querySelector("#gFallback").value.trim()||null,icon:root.querySelector("#gIcon").value.trim()||"mdi:solar-power",description:root.querySelector("#gDescription").value.trim(),role,consumer_id:role==="direct_consumer"?(root.querySelector("#gConsumer").value||null):null,enabled:root.querySelector("#gEnabled").checked,night_zero:root.querySelector("#gNightZero").checked,max_age:Number(root.querySelector("#gMaxAge").value||180)};
  }

  async _saveCurrentGenerator(){
    if(this._busy)return;const updated=this._readCurrentGenerator();if(!updated)return;
    if(!updated.name||!updated.entity_id){this._message("Name und PV-Leistungs-Entity sind erforderlich.",false);return;}
    if(updated.role==="direct_consumer"&&!updated.consumer_id){this._message("Für eine lokale PV-Zuordnung muss ein Verbraucher gewählt werden.",false);return;}
    const originalId=this._selectedGenerator;
    const generators=this._cfg.generators.map(x=>x.id===originalId?updated:x).map(x=>({...x,id:x.id?.startsWith("__new__")?"":x.id}));
    if(this._busy)return;this._busy=true;
    try{await this._hass.callWS({type:"pv_energy_allocation/config/update",consumers:this._cfg.consumers,groups:this._cfg.groups,generators});this._message("PV-Erzeuger gespeichert. WattWer wird neu geladen …",true);await this._waitReload();this._selectedGenerator=null;await this._load();}
    catch(err){this._message(`Speichern fehlgeschlagen: ${String(err?.message||err)}`,false);}finally{this._busy=false;}
  }

  _renderGroups() {
    const body=this.shadowRoot.getElementById("body");
    const groups=this._cfg.groups||[];
    let current=groups.find(g=>g.id===this._selectedGroup); if(!current&&groups.length){current=groups[0];this._selectedGroup=current.id;}
    body.innerHTML=`<div class="split"><section class="pane">
      <div class="panehead"><div class="grow"><h2>Gruppen</h2><p>Mehrere Verbraucher als übergeordneten Verbraucher darstellen.</p></div>${this._cfg.can_manage?'<button class="primary" id="addGroup">+ Gruppe hinzufügen</button>':''}</div>
      <div class="list">${groups.map(g=>this._groupItem(g)).join("")||'<div class="empty">Noch keine Gruppe angelegt.</div>'}</div>
    </section><section class="pane">${current?this._groupEditor(current):'<div class="empty">Gruppe auswählen oder neu anlegen.</div>'}</section></div>`;
    body.querySelector("#addGroup")?.addEventListener("click",()=>this._addGroupDraft());
    body.querySelectorAll("[data-group]").forEach(row=>row.onclick=()=>{this._selectedGroup=row.dataset.group;this._renderGroups();});
    if(current){body.querySelector("#saveGroup")?.addEventListener("click",()=>this._saveCurrentGroup());body.querySelector("#deleteGroup")?.addEventListener("click",()=>this._deleteCurrentGroup());body.querySelector("#resetGroup")?.addEventListener("click",()=>this._renderGroups());}
  }

  _groupItem(g){const members=(g.members||[]).map(id=>this._cfg.consumers.find(c=>c.id===id)?.name).filter(Boolean);return `<div class="item ${g.id===this._selectedGroup?"selected":""}" data-group="${this._attr(g.id)}"><div class="avatar"><ha-icon icon="mdi:account-group"></ha-icon></div><div><div class="itemtitle">${this._esc(g.name)}</div><div class="sub">${members.length} Verbraucher · ${this._esc(members.join(", "))}</div></div><div class="badges"><span class="badge role">Gruppe</span></div><ha-icon icon="mdi:chevron-right"></ha-icon></div>`;}

  _groupEditor(g){const isNew=!g.id||g.id.startsWith("__new__");const assigned=new Set((this._cfg.groups||[]).filter(x=>x.id!==g.id).flatMap(x=>x.members||[]));return `<div class="panehead"><div class="grow"><h2>Gruppe bearbeiten</h2><p>Gruppen summieren vorhandene Einzelhistorien; es werden keine Messdaten umgebucht.</p></div></div><div class="editor">
    <div class="section"><div class="sectionTitle"><ha-icon icon="mdi:account-group-outline"></ha-icon>Basisdaten</div><div class="formgrid"><label>Name</label><input id="gName" value="${this._attr(g.name||"")}" placeholder="z. B. Gebäudeteil gesamt"></div></div>
    <div class="section"><div class="sectionTitle"><ha-icon icon="mdi:format-list-checks"></ha-icon>Mitglieder</div><div class="groupMembers">${this._cfg.consumers.map(c=>{const locked=assigned.has(c.id);return `<label class="member" style="${locked?"opacity:.5":""}"><input type="checkbox" data-gmember="${this._attr(c.id)}" ${(g.members||[]).includes(c.id)?"checked":""} ${locked?"disabled":""}> <ha-icon icon="${this._attr(c.icon||"mdi:flash")}"></ha-icon><span>${this._esc(c.name)}${locked?" · bereits gruppiert":""}</span></label>`;}).join("")}</div><div class="help">Ein Verbraucher kann gleichzeitig nur einer WattWer-Gruppe angehören.</div></div>
    <div class="foot"><div><button class="danger" id="deleteGroup">${isNew?"Verwerfen":"Gruppe löschen"}</button></div><div class="actions"><button class="secondary" id="resetGroup">Zurücksetzen</button><button class="primary" id="saveGroup">Speichern</button></div></div></div>`;}

  _addGroupDraft(){const id=`__new__${Date.now()}`;this._cfg.groups.push({id,name:"Neue Gruppe",members:[]});this._selectedGroup=id;this._renderGroups();}
  async _saveCurrentGroup(){const body=this.shadowRoot.getElementById("body"), old=this._cfg.groups.find(x=>x.id===this._selectedGroup);if(!old)return;const item={...old,id:old.id.startsWith("__new__")?"":old.id,name:body.querySelector("#gName").value.trim(),members:[...body.querySelectorAll("[data-gmember]:checked")].map(x=>x.dataset.gmember)};if(!item.name||!item.members.length){this._message("Gruppenname und mindestens ein Mitglied sind erforderlich.",false);return;}const groups=this._cfg.groups.map(x=>x.id===this._selectedGroup?item:x).map(x=>({...x,id:x.id?.startsWith("__new__")?"":x.id}));await this._saveConsumersGroups(this._cfg.consumers.map(x=>({...x,id:x.id?.startsWith("__new__")?"":x.id})),groups,"Gruppe gespeichert.");}
  async _deleteCurrentGroup(){const id=this._selectedGroup;this._cfg.groups=this._cfg.groups.filter(x=>x.id!==id);this._selectedGroup=this._cfg.groups[0]?.id||null;if(id.startsWith("__new__")){this._renderGroups();return;}await this._saveConsumersGroups(this._cfg.consumers,this._cfg.groups,"Gruppe entfernt. Einzelhistorien bleiben erhalten.");}

  async _saveConsumersGroups(consumers,groups,message){if(this._busy)return;this._busy=true;try{await this._hass.callWS({type:"pv_energy_allocation/config/update",consumers,groups,generators:this._cfg.generators||[]});this._message(`${message} WattWer wird neu geladen …`,true);await this._waitReload();this._selectedConsumer=null;this._selectedGroup=null;await this._load();}catch(err){this._message(`Speichern fehlgeschlagen: ${String(err?.message||err)}`,false);}finally{this._busy=false;}}

  _renderGeneral(){const s=this._cfg.settings||{};const body=this.shadowRoot.getElementById("body");body.innerHTML=`<div class="settings">
    ${this._settingsCard("Netzanschlusspunkt","Messwerte am öffentlichen Netzanschlusspunkt.",[["grid_import","Netzbezug","sensor"],["grid_export","Netzeinspeisung","sensor"]],s)}
    ${this._settingsCard("Diagnose","Optionaler unabhängiger Netto-/Summensensor für Plausibilitätsprüfungen.",[["house_net","Netto-/Summensensor (optional)","sensor"]],s)}
    ${this._settingsCard("Batterie","Optional. Erst konfigurieren, wenn reale Lade- und Entladesensoren vorhanden sind.",[["battery_charge","Batterie Ladeleistung","sensor"],["battery_discharge","Batterie Entladeleistung","sensor"]],s)}
    <div class="settingCard"><h3>Hintergrundlasten</h3><p>Diese Verbraucher beeinflussen den Quellenmix, werden aber nicht einzeln abgerechnet.</p><div class="field"><label>Entity-IDs, eine pro Zeile</label><textarea id="set_background_loads">${this._esc((s.background_loads||[]).join("\n"))}</textarea></div></div>
    ${this._settingsCard("Berechnung","Abtastung, Frischeprüfung und Totzone.",[["sample_interval","Abtastintervall (s)","number"],["max_age","Max. Sensoralter (s)","number"],["deadband","Nullschwelle (W)","number"]],s)}
    ${this._settingsCard("Historie","Automatische Auflösungsgrenzen für die Darstellung.",[["quarter_retention_days","15-Minuten-Tage","number"],["hour_retention_days","Stunden-Tage","number"]],s)}
    </div><div class="foot"><div></div><div class="actions"><button class="secondary" id="resetSettings">Zurücksetzen</button><button class="primary" id="saveSettings">Einstellungen speichern</button></div></div>`;
    body.querySelectorAll("[data-browse-setting]").forEach(btn=>btn.onclick=()=>this._openEntityBrowser(v=>{body.querySelector(`#set_${btn.dataset.browseSetting}`).value=v;}));
    body.querySelector("#resetSettings").onclick=()=>this._renderGeneral();body.querySelector("#saveSettings").onclick=()=>this._saveSettings();}

  _settingsCard(title,desc,fields,s){return `<div class="settingCard"><h3>${this._esc(title)}</h3><p>${this._esc(desc)}</p>${fields.map(([key,label,type])=>`<div class="field"><label>${this._esc(label)}</label>${type==="sensor"?`<div class="entityline"><input id="set_${key}" value="${this._attr(s[key]||"")}" placeholder="sensor…"><button class="secondary" data-browse-setting="${key}">Durchsuchen</button></div>`:`<input type="number" step="any" id="set_${key}" value="${this._attr(s[key]??"")}">`}</div>`).join("")}</div>`;}

  async _saveSettings(){if(this._busy)return;const b=this.shadowRoot.getElementById("body");const s={};["grid_import","grid_export","house_net","battery_charge","battery_discharge"].forEach(k=>s[k]=b.querySelector(`#set_${k}`)?.value.trim()||"");["sample_interval","max_age","deadband","quarter_retention_days","hour_retention_days"].forEach(k=>s[k]=Number(b.querySelector(`#set_${k}`)?.value));s.background_loads=(b.querySelector("#set_background_loads")?.value||"").split(/[\n,;]+/).map(x=>x.trim()).filter(Boolean);this._busy=true;try{await this._hass.callWS({type:"pv_energy_allocation/config/settings_update",settings:s});this._message("Einstellungen gespeichert. WattWer wird neu geladen …",true);await this._waitReload();await this._load();}catch(err){this._message(`Speichern fehlgeschlagen: ${String(err?.message||err)}`,false);}finally{this._busy=false;}}

  async _renderBackfill(){const body=this.shadowRoot.getElementById("body");body.innerHTML='<div class="empty">Backfill-Status wird geladen …</div>';try{this._backfillStatus=await this._hass.callWS({type:"pv_energy_allocation/backfill/status"});const end=new Date();end.setHours(0,0,0,0);const start=new Date(end);start.setDate(start.getDate()-7);const st=this._backfillStatus;body.innerHTML=`<div class="settings"><div class="settingCard"><h3>Historie nachrechnen</h3><p>Rekonstruiert vorhandene Recorder-Rohwerte bis einschließlich heute; das aktuell laufende Viertel wird automatisch ausgelassen.</p><div class="field"><label>Von</label><input type="date" id="bfStart" value="${this._date(start)}"></div><div class="field"><label>Bis einschließlich</label><input type="date" id="bfEnd" value="${this._date(end)}"></div><button class="primary" id="runBackfill" ${st.can_run?"":"disabled"}>Backfill starten</button><div class="progress" id="bfProgress" style="display:none"></div></div><div class="settingCard"><h3>Archivstatus</h3><p>Backfill-Daten werden getrennt von den laufenden Lifetime-Zählern geführt.</p>${this._kv("15-Minuten-Datensätze",st.counts?.["15m"]||0)}${this._kv("Stunden-Datensätze",st.counts?.hour||0)}${this._kv("Tages-Datensätze",st.counts?.day||0)}${this._kv("Konfigurationsrevisionen",st.revision_count||0)}${st.last?this._kv("Letzte Abdeckung",`${(Number(st.last.coverage||0)*100).toFixed(1)} %`):""}</div></div>`;body.querySelector("#runBackfill")?.addEventListener("click",()=>this._runBackfill());}catch(err){body.innerHTML=`<div class="empty">Backfill-Status nicht verfügbar: ${this._esc(String(err?.message||err))}</div>`;}}

  async _runBackfill(){const b=this.shadowRoot.getElementById("body"),p=b.querySelector("#bfProgress"),btn=b.querySelector("#runBackfill");let cursor=new Date(`${b.querySelector("#bfStart").value}T00:00:00`).getTime();const endD=new Date(`${b.querySelector("#bfEnd").value}T00:00:00`);endD.setDate(endD.getDate()+1);const target=endD.getTime();if(!Number.isFinite(cursor)||!Number.isFinite(target)||target<=cursor){this._message("Ungültiger Backfill-Zeitraum.",false);return;}btn.disabled=true;p.style.display="block";p.textContent="Starte …";try{let block=0,weighted=0,secs=0,max=Math.max(1,Number(this._backfillStatus?.max_days_per_run||31));while(cursor<target){const e=Math.min(target,cursor+max*86400000);block++;p.textContent+=`\nBlock ${block}: ${new Date(cursor).toLocaleDateString()} – ${new Date(e-1).toLocaleDateString()} …`;const r=await this._hass.callWS({type:"pv_energy_allocation/backfill/run",start:cursor,end:e});const span=Math.max(1,(r.end-r.start)/1000);weighted+=Number(r.coverage||0)*span;secs+=span;p.textContent+=` ${(Number(r.coverage||0)*100).toFixed(1)} %`;cursor=e;}p.textContent+=`\nFertig · Gesamt-Abdeckung ${(secs?weighted/secs*100:0).toFixed(1)} %`;this._message("Backfill abgeschlossen.",true);}catch(err){p.textContent+=`\nFEHLER: ${String(err?.message||err)}`;}finally{btn.disabled=false;}}

  _renderDisplay(){const refresh=Number(localStorage.getItem("wattwer.liveRefreshSeconds")||5),mode=localStorage.getItem("wattwer.defaultDisplayMode")||"groups";const body=this.shadowRoot.getElementById("body");body.innerHTML=`<div class="settings"><div class="settingCard"><h3>Dashboard</h3><p>Lokale Anzeigeoptionen dieses Browsers. Mess- und Statistikdaten werden dadurch nicht verändert.</p><div class="field"><label>Live-Aktualisierung</label><select id="displayRefresh"><option value="5" ${refresh===5?"selected":""}>5 Sekunden</option><option value="10" ${refresh===10?"selected":""}>10 Sekunden</option><option value="30" ${refresh===30?"selected":""}>30 Sekunden</option><option value="60" ${refresh===60?"selected":""}>60 Sekunden</option></select></div><div class="field"><label>Standardansicht</label><select id="displayMode"><option value="groups" ${mode==="groups"?"selected":""}>Gruppen</option><option value="individual" ${mode==="individual"?"selected":""}>Einzelverbraucher</option></select></div><div class="actions"><button class="primary" id="saveDisplay">Anzeige speichern</button></div></div><div class="settingCard"><h3>PV-Verteilung öffnen</h3><p>Das Auswertungs-Dashboard bleibt separat von dieser Konfiguration in der Sidebar erreichbar.</p><button class="secondary" id="openDashboard"><ha-icon icon="mdi:open-in-new"></ha-icon> Ansicht im Dashboard öffnen</button><div class="help" style="margin-top:12px">WattWer-Version ${this._esc(this._cfg.version||"")}</div></div></div>`;body.querySelector("#saveDisplay").onclick=()=>{localStorage.setItem("wattwer.liveRefreshSeconds",body.querySelector("#displayRefresh").value);localStorage.setItem("wattwer.defaultDisplayMode",body.querySelector("#displayMode").value);this._message("Anzeigeoptionen gespeichert.",true);};body.querySelector("#openDashboard").onclick=()=>this._navigate("/pv-energy-allocation");}

  _openEntityBrowser(onPick){const candidates=Object.values(this._hass.states||{}).filter(s=>s.entity_id?.startsWith("sensor.")).filter(s=>{const dc=s.attributes?.device_class,u=String(s.attributes?.unit_of_measurement||"").toLowerCase();return dc==="power"||["w","kw","mw"].includes(u);}).sort((a,b)=>(a.attributes?.friendly_name||a.entity_id).localeCompare(b.attributes?.friendly_name||b.entity_id));const host=this.shadowRoot.getElementById("modalHost");host.innerHTML=`<div class="modalback"><div class="modal"><div class="modalhead"><h3>Leistungs-Entity auswählen</h3><button class="iconbtn" id="entityClose"><ha-icon icon="mdi:close"></ha-icon></button></div><div class="modalbody"><div class="search" style="margin-bottom:9px"><ha-icon icon="mdi:magnify"></ha-icon><input id="entitySearch" placeholder="Entity oder Name suchen…"></div><div id="entityList">${this._entityRows(candidates)}</div></div></div></div>`;const render=()=>{const q=host.querySelector("#entitySearch").value.toLowerCase();const rows=candidates.filter(s=>`${s.entity_id} ${s.attributes?.friendly_name||""}`.toLowerCase().includes(q));host.querySelector("#entityList").innerHTML=this._entityRows(rows);host.querySelectorAll("[data-pick-entity]").forEach(x=>x.onclick=()=>{onPick(x.dataset.pickEntity);host.innerHTML="";});};host.querySelector("#entityClose").onclick=()=>host.innerHTML="";host.querySelector("#entitySearch").oninput=render;render();host.querySelector("#entitySearch").focus();}
  _entityRows(rows){return rows.map(s=>`<div class="entityItem" data-pick-entity="${this._attr(s.entity_id)}"><strong>${this._esc(s.attributes?.friendly_name||s.entity_id)}</strong><span>${this._esc(s.entity_id)} · ${this._esc(s.state)} ${this._esc(s.attributes?.unit_of_measurement||"")}</span></div>`).join("")||'<div class="empty">Keine passenden Leistungssensoren gefunden.</div>';}
  _openIconChooser(onPick){const icons=["mdi:flash","mdi:home-lightning-bolt","mdi:heat-pump","mdi:power-plug","mdi:home-city","mdi:meter-electric","mdi:ev-station","mdi:water-boiler","mdi:washing-machine","mdi:fridge-outline","mdi:stove","mdi:server","mdi:air-conditioner","mdi:lightning-bolt-circle"];const host=this.shadowRoot.getElementById("modalHost");host.innerHTML=`<div class="modalback"><div class="modal"><div class="modalhead"><h3>Icon auswählen</h3><button class="iconbtn" id="iconClose"><ha-icon icon="mdi:close"></ha-icon></button></div><div class="modalbody"><div class="groupMembers">${icons.map(i=>`<button class="member" data-pick-icon="${i}"><ha-icon icon="${i}"></ha-icon><span>${i}</span></button>`).join("")}</div></div></div></div>`;host.querySelector("#iconClose").onclick=()=>host.innerHTML="";host.querySelectorAll("[data-pick-icon]").forEach(x=>x.onclick=()=>{onPick(x.dataset.pickIcon);host.innerHTML="";});}
  _showHelp(){const host=this.shadowRoot.getElementById("modalHost");host.innerHTML=`<div class="modalback"><div class="modal"><div class="modalhead"><h3>WattWer Konfiguration</h3><button class="iconbtn" id="helpClose"><ha-icon icon="mdi:close"></ha-icon></button></div><div class="modalbody"><p>Diese Oberfläche ist das integrationsspezifische Konfigurationspanel von WattWer. Das Zahnrad der Integration öffnet diese Seite; das PV-Verteilungs-Dashboard bleibt davon getrennt.</p><p><strong>Historische Identität:</strong> Namen, Icons und Mess-Entities dürfen geändert werden. Bestehende Verbraucher behalten dabei ihre stabile interne ID. Für einen Hardwaretausch sollte daher der vorhandene Verbraucher bearbeitet und nicht als neuer Verbraucher angelegt werden.</p></div></div></div>`;host.querySelector("#helpClose").onclick=()=>host.innerHTML="";}

  async _waitReload(){for(let i=0;i<18;i++){await new Promise(r=>setTimeout(r,700));try{await this._hass.callWS({type:"pv_energy_allocation/config"});return;}catch(_e){}}}
  _message(text,ok){const el=this.shadowRoot.getElementById("message");el.textContent=text;el.className=`topmessage show ${ok?"ok":"err"}`;clearTimeout(this._msgTimer);this._msgTimer=setTimeout(()=>{el.className="topmessage";},6000);}
  _kv(k,v){return `<div style="display:flex;justify-content:space-between;gap:20px;padding:9px 0;border-bottom:1px solid var(--divider-color);font-size:12px"><span style="color:var(--secondary-text-color)">${this._esc(k)}</span><strong>${this._esc(v)}</strong></div>`;}
  _date(d){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;}
  _esc(v){return String(v??"").replace(/[&<>'"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));}
  _attr(v){return this._esc(v);}
}

if (!customElements.get("wattwer-config-panel")) customElements.define("wattwer-config-panel", WattWerConfigPanel);
