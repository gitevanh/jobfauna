const API = "/api";
const COLUMNS = [
  { key: "saved",     label: "Saved",     color: "var(--col-saved)" },
  { key: "applied",   label: "Applied",   color: "var(--col-applied)" },
  { key: "interview", label: "Interview", color: "var(--col-interview)" },
  { key: "offer",     label: "Offer",     color: "var(--col-offer)" },
  { key: "rejected",  label: "Rejected",  color: "var(--col-rejected)" },
];

// Change this to your repo once it's created.
const REPO_URL = "https://github.com/gitevanh/jobfauna";
const APP_VERSION = "1.0.0";

// Themes mirroring the NimiBeats set. Fauna is the default (defined in :root).
const THEMES = [
  { id:"nimi",   name:"Nimi",   sub:"Sage mint",     c:"#a3d9c0" },
  { id:"mint",   name:"Mint",   sub:"Ghost mint",    c:"#b9f0d6" },
  { id:"fauna",  name:"Fauna",  sub:"Nature green",  c:"#6fdc8c" },
  { id:"doki",   name:"Doki",   sub:"Golden yellow", c:"#f5d042" },
  { id:"sakuna", name:"Sakuna", sub:"Sakura pink",   c:"#f9a8d4" },
  { id:"kronii", name:"Kronii", sub:"Time blue",     c:"#6cb8f2" },
  { id:"gigi",   name:"Gigi",   sub:"Warm amber",    c:"#f5a623" },
  { id:"shiori", name:"Shiori", sub:"Gothic purple", c:"#c084fc" },
  { id:"mono",   name:"Mono",   sub:"Black & white", c:"#e8e9ed" },
];
function currentTheme() { try { return localStorage.getItem("jobfauna-theme") || "fauna"; } catch (e) { return "fauna"; } }
function applyTheme(id) { document.documentElement.dataset.theme = id; try { localStorage.setItem("jobfauna-theme", id); } catch (e) {} }

function applyBrand(me) {
  const logo = me.instance_logo || "🌿";
  const name = me.instance_name || "JobFauna";
  const logoEl = document.getElementById("brand-logo");
  if (me.logo_url) logoEl.innerHTML = `<img src="${escapeHtml(me.logo_url)}" alt="" />`;
  else logoEl.textContent = logo;
  document.getElementById("brand-name").textContent = name;
  document.title = name;
  window._brand = { logo, name, logo_url: me.logo_url || "" };
}

let jobs = [];
let aiEnabled = false;
let editingId = null;   // null = creating a new job
let searchTerm = "";
let currentUser = null;

// ---------- API helpers ----------
async function api(path, opts) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (res.status === 401) { window.location = "/login"; throw new Error("unauthorized"); }
  if (!res.ok) throw new Error("Request failed: " + res.status);
  return res.status === 204 ? null : res.json();
}

async function loadMe() {
  let me;
  try { me = await api("/me"); } catch (e) { return; }
  if (me.needs_setup || !me.authenticated) { window.location = "/login"; return; }
  applyBrand(me);
  currentUser = me.user;
  document.getElementById("account-btn").textContent = currentUser.email;
  if (currentUser.role === "admin") document.getElementById("admin-btn").style.display = "inline-block";
  aiEnabled = me.enrichment_enabled;
  const pill = document.getElementById("ai-pill");
  pill.classList.toggle("on", aiEnabled);
  document.getElementById("ai-pill-text").textContent = aiEnabled ? "AI on" : "AI off";
}

async function loadJobs() {
  jobs = await api("/jobs");
  render();
}

// ---------- Rendering ----------
function fitClass(score) { return score >= 70 ? "high" : score >= 40 ? "mid" : "low"; }

function render() {
  const board = document.getElementById("board");
  board.innerHTML = "";
  const term = searchTerm.toLowerCase();
  const visible = jobs.filter(j =>
    !term || (j.company + " " + j.title).toLowerCase().includes(term)
  );

  COLUMNS.forEach(col => {
    const inCol = visible.filter(j => j.status === col.key);
    const colEl = document.createElement("section");
    colEl.className = "column";
    colEl.innerHTML = `
      <div class="col-head">
        <span class="swatch" style="background:${col.color}"></span>
        <span class="name">${col.label}</span>
        <span class="count">${inCol.length}</span>
      </div>
      <div class="col-body" data-status="${col.key}"></div>`;
    const body = colEl.querySelector(".col-body");

    if (inCol.length === 0) {
      body.innerHTML = `<div class="empty-col">Drop here</div>`;
    } else {
      inCol.forEach(j => body.appendChild(cardEl(j)));
    }

    // drag-and-drop targets
    body.addEventListener("dragover", e => { e.preventDefault(); body.classList.add("drag-over"); });
    body.addEventListener("dragleave", () => body.classList.remove("drag-over"));
    body.addEventListener("drop", e => {
      e.preventDefault();
      body.classList.remove("drag-over");
      const id = Number(e.dataTransfer.getData("text/plain"));
      moveJob(id, col.key);
    });

    board.appendChild(colEl);
  });

  // stats
  const active = jobs.filter(j => ["saved","applied","interview"].includes(j.status)).length;
  document.getElementById("stat-total").textContent = jobs.length;
  document.getElementById("stat-active").textContent = active;
  document.getElementById("stat-interview").textContent = jobs.filter(j => j.status === "interview").length;
}

function cardEl(j) {
  const el = document.createElement("article");
  el.className = "card";
  el.draggable = true;
  const fit = j.fit_score > 0
    ? `<span class="fit ${fitClass(j.fit_score)}">${j.fit_score}</span>` : "";
  const cat = j.category ? `<span class="chip cat">${j.category}</span>` : "";
  const loc = j.location ? `<div class="loc">⚲ ${escapeHtml(j.location)}</div>` : "";
  el.innerHTML = `
    <div class="company">${escapeHtml(j.company || "—")}</div>
    <div class="title">${escapeHtml(j.title || "Untitled role")}</div>
    <div class="meta">${cat}${fit}</div>
    ${loc}`;
  el.addEventListener("click", () => openDrawer(j));
  el.addEventListener("dragstart", e => {
    e.dataTransfer.setData("text/plain", j.id);
    el.classList.add("dragging");
  });
  el.addEventListener("dragend", () => el.classList.remove("dragging"));
  return el;
}

async function moveJob(id, status) {
  const job = jobs.find(j => j.id === id);
  if (!job || job.status === status) return;
  job.status = status;                 // optimistic update
  render();
  try { await api(`/jobs/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }); }
  catch (e) { toast("Couldn't save — is the server running?"); loadJobs(); }
}

// ---------- Drawer ----------
function openDrawer(job) {
  editingId = job ? job.id : null;
  document.getElementById("drawer-title").textContent = job ? "Edit job" : "Add job";
  const g = id => document.getElementById(id);
  g("f-title").value = job?.title || "";
  g("f-company").value = job?.company || "";
  g("f-status").value = job?.status || "saved";
  g("f-location").value = job?.location || "";
  g("f-salary").value = job?.salary || "";
  g("f-url").value = job?.url || "";
  g("f-notes").value = job?.notes || "";
  g("f-description").value = job?.description || "";

  // url link
  const link = g("f-url-link");
  if (job?.url) { link.style.display = "inline"; link.href = job.url; link.textContent = "↗ open posting"; }
  else link.style.display = "none";

  // ai box
  const fitEl = g("f-fit");
  const score = job?.fit_score || 0;
  fitEl.textContent = score > 0 ? score : "—";
  fitEl.className = "fit " + (score > 0 ? fitClass(score) : "low");
  const catEl = g("f-cat");
  if (job?.category) { catEl.style.display = "inline"; catEl.textContent = job.category; }
  else catEl.style.display = "none";
  const sum = g("f-summary");
  if (job?.summary) { sum.textContent = job.summary; sum.classList.remove("empty"); }
  else { sum.textContent = aiEnabled ? "No AI summary yet." : "Add an API key to enable AI analysis."; sum.classList.add("empty"); }

  // re-enrich only for existing jobs when AI is on
  g("reenrich-btn").style.display = (job && aiEnabled) ? "inline-block" : "none";
  g("delete-btn").style.display = job ? "block" : "none";

  // cover letter + tailored CV
  g("f-cover").value = job?.cover_letter || "";
  g("f-tailored").value = job?.tailored_cv || "";
  const canGen = job && aiEnabled;
  g("gen-cover").style.display = canGen ? "inline-block" : "none";
  g("gen-cv").style.display = canGen ? "inline-block" : "none";
  if (canGen) {
    g("gen-cover").onclick = () => generateDoc("cover-letter", "gen-cover", "f-cover", "Cover letter");
    g("gen-cv").onclick = () => generateDoc("tailor-cv", "gen-cv", "f-tailored", "Tailored CV");
  }
  g("copy-cover").onclick = () => copyField("f-cover");
  g("copy-cv").onclick = () => copyField("f-tailored");
  g("docx-cover").onclick = () => downloadDoc("docx", "f-cover", "Cover letter");
  g("pdf-cover").onclick = () => downloadDoc("pdf", "f-cover", "Cover letter");
  g("docx-cv").onclick = () => downloadDoc("docx", "f-tailored", "Tailored CV");
  g("pdf-cv").onclick = () => downloadDoc("pdf", "f-tailored", "Tailored CV");

  document.getElementById("scrim").classList.add("show");
  document.getElementById("drawer").classList.add("show");
}

async function generateDoc(endpoint, btnId, fieldId, label) {
  if (editingId === null) return;
  const btn = document.getElementById(btnId);
  const orig = btn.textContent;
  btn.disabled = true; btn.textContent = "Writing…";
  try {
    const r = await api(`/jobs/${editingId}/${endpoint}`, { method: "POST" });
    const text = r.cover_letter ?? r.tailored_cv ?? "";
    document.getElementById(fieldId).value = text;
    // keep local copy in sync
    const idx = jobs.findIndex(j => j.id === editingId);
    if (idx >= 0) { jobs[idx][endpoint === "cover-letter" ? "cover_letter" : "tailored_cv"] = text; }
    toast(label + " ready");
  } catch (e) {
    toast(label + " failed — check your CV/AI key");
  }
  btn.disabled = false; btn.textContent = orig;
}

function copyField(id) {
  const v = document.getElementById(id).value;
  if (!v) { toast("Nothing to copy yet"); return; }
  navigator.clipboard.writeText(v).then(() => toast("Copied"), () => toast("Copy failed"));
}

async function downloadDoc(fmt, fieldId, label) {
  const text = document.getElementById(fieldId).value;
  if (!text.trim()) { toast("Nothing to download yet"); return; }
  const company = document.getElementById("f-company").value.trim();
  const title = document.getElementById("f-title").value.trim();
  const fname = `${label} - ${company || title || "JobFauna"}`;
  try {
    const res = await fetch(`/api/render/${fmt}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body: text, filename: fname }),
    });
    if (!res.ok) throw new Error();
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${fname}.${fmt}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    toast("Download failed");
  }
}

function closeDrawer() {
  document.getElementById("scrim").classList.remove("show");
  document.getElementById("drawer").classList.remove("show");
  editingId = null;
}

function collectForm() {
  const g = id => document.getElementById(id).value.trim();
  return {
    title: g("f-title"), company: g("f-company"), status: g("f-status"),
    location: g("f-location"), salary: g("f-salary"), url: g("f-url"),
    notes: g("f-notes"), description: g("f-description"),
    cover_letter: g("f-cover"), tailored_cv: g("f-tailored"),
  };
}

async function saveJob() {
  const data = collectForm();
  try {
    if (editingId === null) {
      await api("/jobs", { method: "POST", body: JSON.stringify({ ...data, source: "manual" }) });
      toast("Job added" + (aiEnabled ? " — AI analysis applied" : ""));
    } else {
      await api(`/jobs/${editingId}`, { method: "PATCH", body: JSON.stringify(data) });
      toast("Saved");
    }
    closeDrawer();
    await loadJobs();
  } catch (e) { toast("Save failed — is the server running?"); }
}

async function deleteJob() {
  if (editingId === null) return;
  if (!confirm("Delete this job?")) return;
  await api(`/jobs/${editingId}`, { method: "DELETE" });
  closeDrawer();
  toast("Deleted");
  await loadJobs();
}

async function reenrich() {
  if (editingId === null) return;
  const btn = document.getElementById("reenrich-btn");
  btn.textContent = "Analyzing...";
  btn.disabled = true;
  try {
    const updated = await api(`/jobs/${editingId}/enrich`, { method: "POST" });
    const idx = jobs.findIndex(j => j.id === editingId);
    if (idx >= 0) jobs[idx] = updated;
    openDrawer(updated);   // refresh drawer contents
    render();
    toast("AI analysis updated");
  } catch (e) { toast("Analysis failed"); }
  btn.textContent = "↻ Run AI analysis";
  btn.disabled = false;
}

// ---------- Modals: account + admin ----------
function openModal(html) {
  document.getElementById("modal").innerHTML = html;
  document.getElementById("modal-scrim").classList.add("show");
}
function closeModal() {
  document.getElementById("modal-scrim").classList.remove("show");
}

async function openAccount() {
  openModal(`
    <div class="modal-head"><h2>Account</h2><div class="spacer"></div><button class="icon-btn" onclick="closeModal()">&times;</button></div>
    <div class="modal-body">
      <div>
        <div class="section-label">Signed in as</div>
        <div>${escapeHtml(currentUser.email)} <span class="badge ${currentUser.role}">${currentUser.role}</span></div>
      </div>
      <div>
        <div class="section-label">Change password</div>
        <input id="pw-cur" type="password" placeholder="current password" />
        <input id="pw-new" type="password" placeholder="new password (8+ chars)" style="margin-top:8px" />
        <input id="pw-cf" type="password" placeholder="confirm new password" style="margin-top:8px" />
        <button class="mini" id="pw-save" style="margin-top:10px">Update password</button>
        <div class="msg" id="pw-msg" style="text-align:left"></div>
      </div>
      <div>
        <div class="section-label">Your CV / résumé</div>
        <div class="empty-note" style="margin-bottom:6px">Used by AI to write cover letters and tailor your CV per job.</div>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap">
          <button class="mini" id="cv-upload-btn">⬆ Upload file (PDF / DOCX / TXT)</button>
          <span class="empty-note" id="cv-upload-status"></span>
          <input type="file" id="cv-file" accept=".pdf,.docx,.txt,.md" style="display:none" />
        </div>
        <textarea id="acc-cv" placeholder="Paste your CV / résumé here, or upload a file above..." style="min-height:130px"></textarea>
        <div class="section-label" style="margin-top:10px">Short background</div>
        <div class="empty-note" style="margin-bottom:6px">One paragraph — used for the per-job fit score.</div>
        <textarea id="acc-profile" placeholder="Your experience and what you're looking for..."></textarea>
        <button class="mini" id="cv-save" style="margin-top:10px">Save CV &amp; background</button>
        <div class="msg" id="cv-msg" style="text-align:left"></div>
      </div>
      <div>
        <div class="section-label">Theme</div>
        <div class="theme-grid" id="theme-row"></div>
      </div>
      <div>
        <div class="section-label">Extension API tokens</div>
        <div id="tok-list"></div>
        <div id="tok-new"></div>
        <button class="mini" id="gen-tok" style="margin-top:10px">+ Generate token</button>
      </div>
      <div style="display:flex;gap:10px">
        <button class="btn btn-ghost" id="about-btn" style="flex:1">About</button>
        <button class="btn btn-ghost" id="signout" style="flex:1">Sign out</button>
      </div>
    </div>`);

  renderThemes();
  renderTokens(await api("/tokens"));

  // CV / background
  try {
    const prof = await api("/account/profile");
    document.getElementById("acc-cv").value = prof.cv || "";
    document.getElementById("acc-profile").value = prof.profile || "";
  } catch (e) {}
  document.getElementById("cv-save").onclick = async () => {
    const m = document.getElementById("cv-msg"); m.style.textAlign = "left";
    try {
      await api("/account/profile", { method: "PUT", body: JSON.stringify({
        cv: document.getElementById("acc-cv").value,
        profile: document.getElementById("acc-profile").value,
      })});
      m.className = "msg ok"; m.textContent = "Saved.";
    } catch (e) { m.className = "msg err"; m.textContent = "Couldn't save."; }
  };

  document.getElementById("cv-upload-btn").onclick = () => document.getElementById("cv-file").click();
  document.getElementById("cv-file").onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const status = document.getElementById("cv-upload-status");
    status.textContent = "Reading…";
    const fd = new FormData();
    fd.append("file", f);
    try {
      const res = await fetch("/api/account/cv-upload", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Couldn't read file");
      document.getElementById("acc-cv").value = data.text;
      status.textContent = "Loaded — review and Save.";
    } catch (err) {
      status.textContent = err.message || "Couldn't read file.";
    }
    e.target.value = "";
  };

  document.getElementById("pw-save").onclick = async () => {
    const m = document.getElementById("pw-msg");
    m.style.textAlign = "left";
    const cur = document.getElementById("pw-cur").value;
    const nw = document.getElementById("pw-new").value;
    const cf = document.getElementById("pw-cf").value;
    if (nw !== cf) { m.className = "msg err"; m.textContent = "New passwords don't match."; return; }
    try {
      await api("/account/password", { method: "POST", body: JSON.stringify({ current_password: cur, new_password: nw }) });
      m.className = "msg ok"; m.textContent = "Password updated.";
      ["pw-cur","pw-new","pw-cf"].forEach(id => document.getElementById(id).value = "");
    } catch (e) {
      m.className = "msg err"; m.textContent = "Couldn't update — check your current password (new must be 8+ chars).";
    }
  };

  document.getElementById("gen-tok").onclick = async () => {
    const r = await api("/tokens", { method: "POST", body: JSON.stringify({ name: "extension" }) });
    document.getElementById("tok-new").innerHTML =
      `<div class="section-label" style="margin-top:10px">New token — copy now, shown once</div>
       <div class="token-box">${escapeHtml(r.token)}</div>`;
    renderTokens(await api("/tokens"));
  };
  document.getElementById("about-btn").onclick = openAbout;
  document.getElementById("signout").onclick = async () => {
    try { await api("/logout", { method: "POST" }); } catch (e) {}
    window.location = "/login";
  };
}

function renderThemes() {
  const row = document.getElementById("theme-row");
  if (!row) return;
  const cur = currentTheme();
  row.innerHTML = "";
  THEMES.forEach(t => {
    const b = document.createElement("button");
    b.className = "theme-card" + (t.id === cur ? " active" : "");
    b.innerHTML = `<span class="dotc" style="background:${t.c}"></span><div class="tname">${t.name}</div><div class="tsub">${t.sub}</div>`;
    b.onclick = () => { applyTheme(t.id); renderThemes(); };
    row.appendChild(b);
  });
}

function openAbout() {
  const b = window._brand || { logo: "🌿", name: "JobFauna" };
  openModal(`
    <div class="modal-head"><h2>About</h2><div class="spacer"></div><button class="icon-btn" onclick="closeModal()">&times;</button></div>
    <div class="modal-body about">
      <div class="about-name"><span class="logo">${escapeHtml(b.logo)}</span> ${escapeHtml(b.name)}</div>
      <p>A self-hosted job-application tracker: one-click capture from a browser extension, a
         drag-and-drop board, optional AI enrichment, and multi-user accounts with admin approval.</p>
      <p>Built on FastAPI + SQLite with a no-build vanilla frontend — powered by the open-source
         <strong>JobFauna</strong> project.</p>
      <p>Source &amp; docs: <a href="${REPO_URL}" target="_blank" rel="noopener">${REPO_URL.replace('https://','')}</a></p>
      <p style="color:var(--faint)">Version ${APP_VERSION} · MIT License</p>
    </div>`);
}

function renderTokens(tokens) {
  const el = document.getElementById("tok-list");
  if (!el) return;
  el.innerHTML = tokens.length ? "" : `<div class="empty-note">No tokens yet — generate one and paste it into the extension.</div>`;
  tokens.forEach(t => {
    const row = document.createElement("div");
    row.className = "urow";
    row.innerHTML = `<div class="who"><span class="em">${escapeHtml(t.name)}</span><span class="sub">added ${t.created_at.slice(0,10)}</span></div><div class="acts"><button class="mini bad">Revoke</button></div>`;
    row.querySelector("button").onclick = async () => { await api("/tokens/" + t.id, { method: "DELETE" }); renderTokens(await api("/tokens")); };
    el.appendChild(row);
  });
}

async function openAdmin() {
  openModal(`
    <div class="modal-head"><h2>Admin</h2><div class="spacer"></div><button class="icon-btn" onclick="closeModal()">&times;</button></div>
    <div class="modal-body">
      <div><div class="section-label" id="pl-label">Access requests</div><div id="pending-list"></div></div>
      <div><div class="section-label">Users</div><div id="user-list"></div></div>
      <div>
        <div class="section-label">Create a user directly</div>
        <div class="row2"><input id="nu-email" placeholder="email" /><input id="nu-name" placeholder="name (optional)" /></div>
        <div class="row2" style="margin-top:8px"><input id="nu-pass" type="password" placeholder="password (8+ chars)" /><select id="nu-role"><option value="user">user</option><option value="admin">admin</option></select></div>
        <button class="mini" id="nu-create" style="margin-top:10px">Create user</button>
        <div class="msg" id="nu-msg" style="text-align:left"></div>
      </div>
      <div>
        <div class="section-label">Instance settings</div>
        <div class="row2"><input id="set-name" placeholder="Instance name" /><input id="set-logo" placeholder="Logo emoji/text" /></div>
        <input id="set-tagline" placeholder="Login tagline" style="margin-top:8px" />
        <input id="set-logourl" placeholder="Logo image URL (optional)" style="margin-top:8px" />
        <input id="set-ai" type="password" placeholder="Anthropic API key — enables AI features" style="margin-top:8px" />
        <div id="set-ai-note" class="empty-note" style="margin-top:6px"></div>
        <div class="section-label" style="margin-top:12px">AI models</div>
        <div class="row2">
          <select id="set-enrich-model"></select>
          <select id="set-writing-model"></select>
        </div>
        <div class="empty-note" style="margin-top:4px" id="model-note">Left: enrichment (cheap). Right: cover letters / CV (stronger).</div>
        <button class="mini" id="set-save" style="margin-top:10px">Save settings</button>
        <div class="msg" id="set-msg" style="text-align:left"></div>
      </div>
    </div>`);
  await refreshAdmin();
  await loadAdminSettings();

  document.getElementById("nu-create").onclick = async () => {
    const m = document.getElementById("nu-msg");
    const body = {
      email: document.getElementById("nu-email").value.trim(),
      name: document.getElementById("nu-name").value.trim(),
      password: document.getElementById("nu-pass").value,
      role: document.getElementById("nu-role").value,
    };
    try {
      await api("/admin/users", { method: "POST", body: JSON.stringify(body) });
      m.className = "msg ok"; m.style.textAlign = "left"; m.textContent = "User created.";
      ["nu-email","nu-name","nu-pass"].forEach(id => document.getElementById(id).value = "");
      await refreshAdmin();
    } catch (e) {
      m.className = "msg err"; m.style.textAlign = "left";
      m.textContent = "Couldn't create — check the email/password, or it may already exist.";
    }
  };

  document.getElementById("set-save").onclick = async () => {
    const m = document.getElementById("set-msg");
    m.style.textAlign = "left";
    const body = {
      instance_name: document.getElementById("set-name").value.trim(),
      instance_logo: document.getElementById("set-logo").value.trim(),
      login_tagline: document.getElementById("set-tagline").value.trim(),
      logo_url: document.getElementById("set-logourl").value.trim(),
      enrich_model: document.getElementById("set-enrich-model").value,
      writing_model: document.getElementById("set-writing-model").value,
    };
    const aik = document.getElementById("set-ai").value.trim();
    if (aik) body.anthropic_api_key = aik;
    try {
      await api("/admin/settings", { method: "PATCH", body: JSON.stringify(body) });
      m.className = "msg ok"; m.textContent = "Saved.";
      document.getElementById("set-ai").value = "";
      const me = await api("/me");
      applyBrand(me);
      aiEnabled = me.enrichment_enabled;
      document.getElementById("ai-pill").classList.toggle("on", aiEnabled);
      document.getElementById("ai-pill-text").textContent = aiEnabled ? "AI on" : "AI off";
      await loadAdminSettings();
    } catch (e) {
      m.className = "msg err"; m.textContent = "Couldn't save settings.";
    }
  };
}

function fillModelSelect(el, models, current, def) {
  el.innerHTML = "";
  const opt0 = document.createElement("option");
  opt0.value = ""; opt0.textContent = `Default (${def})`;
  el.appendChild(opt0);
  const list = models.slice();
  if (current && !list.includes(current)) list.unshift(current);
  list.forEach(id => {
    const o = document.createElement("option");
    o.value = id; o.textContent = id;
    el.appendChild(o);
  });
  el.value = current || "";
}

async function loadAdminSettings() {
  const s = await api("/admin/settings");
  document.getElementById("set-name").value = s.instance_name;
  document.getElementById("set-logo").value = s.instance_logo;
  document.getElementById("set-tagline").value = s.instance_tagline || "";
  document.getElementById("set-logourl").value = s.logo_url || "";

  let models = [];
  try { models = (await api("/admin/models")).models || []; } catch (e) {}
  fillModelSelect(document.getElementById("set-enrich-model"), models, s.enrich_model, s.default_enrich_model);
  fillModelSelect(document.getElementById("set-writing-model"), models, s.writing_model, s.default_writing_model);
  document.getElementById("model-note").textContent = models.length
    ? "Left: enrichment (cheap). Right: cover letters / CV (stronger)."
    : "Set an API key to load the full model list (current selections shown).";

  const note = document.getElementById("set-ai-note");
  if (s.ai_key_from_env) {
    note.innerHTML = "Using <code>ANTHROPIC_API_KEY</code> from the environment (it overrides any key set here).";
  } else if (s.ai_key_set) {
    note.innerHTML = `A key is saved — AI is on. Enter a new key to replace it, or <a href="#" id="clear-ai" style="color:var(--bad)">clear it</a>.`;
    const clear = document.getElementById("clear-ai");
    if (clear) clear.onclick = async (e) => {
      e.preventDefault();
      await api("/admin/settings", { method: "PATCH", body: JSON.stringify({ anthropic_api_key: "" }) });
      const me = await api("/me");
      aiEnabled = me.enrichment_enabled;
      document.getElementById("ai-pill").classList.toggle("on", aiEnabled);
      document.getElementById("ai-pill-text").textContent = aiEnabled ? "AI on" : "AI off";
      await loadAdminSettings();
    };
  } else {
    note.textContent = "No key set — AI features are off.";
  }
}

async function refreshAdmin() {
  const users = await api("/admin/users");
  const pending = users.filter(u => u.status === "pending");
  const active = users.filter(u => u.status !== "pending");
  document.getElementById("pl-label").textContent = `Access requests (${pending.length})`;

  const pl = document.getElementById("pending-list");
  pl.innerHTML = pending.length ? "" : `<div class="empty-note">No pending requests.</div>`;
  pending.forEach(u => {
    const row = document.createElement("div");
    row.className = "urow";
    const note = u.note ? " · " + escapeHtml(u.note) : "";
    row.innerHTML = `<div class="who"><span class="em">${escapeHtml(u.email)}</span><span class="sub">${escapeHtml(u.name || "")}${note}</span></div><div class="acts"><button class="mini good">Approve</button><button class="mini bad">Reject</button></div>`;
    const [appr, rej] = row.querySelectorAll("button");
    appr.onclick = async () => { await api("/admin/users/" + u.id, { method: "PATCH", body: JSON.stringify({ status: "approved" }) }); refreshAdmin(); };
    rej.onclick = async () => { if (confirm("Reject and delete this request?")) { await api("/admin/users/" + u.id, { method: "DELETE" }); refreshAdmin(); } };
    pl.appendChild(row);
  });

  const ul = document.getElementById("user-list");
  ul.innerHTML = "";
  active.forEach(u => {
    const row = document.createElement("div");
    row.className = "urow";
    const isMe = u.id === currentUser.id;
    const badges = `<span class="badge ${u.role}">${u.role}</span>` + (u.status !== "approved" ? `<span class="badge ${u.status}">${u.status}</span>` : "");
    row.innerHTML = `<div class="who"><span class="em">${escapeHtml(u.email)}${isMe ? ' (you)' : ''}</span><span class="sub">${badges}</span></div><div class="acts"></div>`;
    const acts = row.querySelector(".acts");

    const roleBtn = document.createElement("button");
    roleBtn.className = "mini";
    roleBtn.textContent = u.role === "admin" ? "Remove admin" : "Make admin";
    roleBtn.onclick = async () => {
      try { await api("/admin/users/" + u.id, { method: "PATCH", body: JSON.stringify({ role: u.role === "admin" ? "user" : "admin" }) }); }
      catch (e) { toast("Can't remove the last admin"); }
      refreshAdmin();
    };

    const stBtn = document.createElement("button");
    stBtn.className = "mini";
    stBtn.textContent = u.status === "approved" ? "Disable" : "Enable";
    stBtn.onclick = async () => {
      try { await api("/admin/users/" + u.id, { method: "PATCH", body: JSON.stringify({ status: u.status === "approved" ? "disabled" : "approved" }) }); }
      catch (e) { toast("Can't disable the last admin"); }
      refreshAdmin();
    };

    const delBtn = document.createElement("button");
    delBtn.className = "mini bad";
    delBtn.textContent = "Delete";
    delBtn.onclick = async () => {
      if (!confirm("Delete " + u.email + " and all their jobs?")) return;
      try { await api("/admin/users/" + u.id, { method: "DELETE" }); }
      catch (e) { toast("Can't delete the last admin"); }
      refreshAdmin();
    };

    acts.append(roleBtn, stBtn, delBtn);
    ul.appendChild(row);
  });
}

// ---------- Misc ----------
function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, c =>
    ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}
let toastTimer;
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}

// ---------- Wire up ----------
document.getElementById("add-btn").addEventListener("click", () => openDrawer(null));
document.getElementById("close-drawer").addEventListener("click", closeDrawer);
document.getElementById("scrim").addEventListener("click", closeDrawer);
document.getElementById("save-btn").addEventListener("click", saveJob);
document.getElementById("delete-btn").addEventListener("click", deleteJob);
document.getElementById("reenrich-btn").addEventListener("click", reenrich);
document.getElementById("search").addEventListener("input", e => { searchTerm = e.target.value; render(); });
document.getElementById("account-btn").addEventListener("click", openAccount);
document.getElementById("admin-btn").addEventListener("click", openAdmin);
document.getElementById("modal-scrim").addEventListener("click", e => { if (e.target.id === "modal-scrim") closeModal(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") { closeDrawer(); closeModal(); } });

// ---------- Go ----------
(async () => { await loadMe(); await loadJobs(); })();
