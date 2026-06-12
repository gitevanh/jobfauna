// popup.js — cross-browser (Chrome/Edge + Firefox)
// Uses the WebExtension `browser` namespace when present (Firefox), falling back
// to `chrome` (Chromium). Both return promises for the APIs we use here.

const ext = (typeof browser !== "undefined") ? browser : chrome;
const DEFAULT_SERVER = "http://localhost:8000";
const $ = (id) => document.getElementById(id);

// ---- Runs INSIDE the page, so it must be self-contained. ----
function scrapeJobPage() {
  const pick = (selectors) => {
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && el.textContent.trim()) return el.textContent.trim();
    }
    return "";
  };
  const meta = (name) => {
    const el = document.querySelector(`meta[property="${name}"], meta[name="${name}"]`);
    return el ? el.getAttribute("content") : "";
  };

  const host = location.hostname;
  let title = "", company = "", loc = "", description = "";

  if (host.includes("linkedin.com")) {
    title = pick([".job-details-jobs-unified-top-card__job-title", ".top-card-layout__title", "h1"]);
    company = pick([".job-details-jobs-unified-top-card__company-name", ".topcard__org-name-link", ".topcard__flavor"]);
    loc = pick([".job-details-jobs-unified-top-card__primary-description-container", ".topcard__flavor--bullet"]);
    description = pick(["#job-details", ".jobs-description__content", ".description__text"]);
  } else if (host.includes("indeed.")) {
    title = pick([".jobsearch-JobInfoHeader-title", 'h1[data-testid="jobsearch-JobInfoHeader-title"]', "h1"]);
    company = pick(['[data-testid="inlineHeader-companyName"]', '[data-company-name]', ".jobsearch-CompanyInfoContainer a"]);
    loc = pick(['[data-testid="inlineHeader-companyLocation"]', '[data-testid="job-location"]']);
    description = pick(["#jobDescriptionText"]);
  } else if (host.includes("glassdoor.")) {
    title = pick(['[data-test="job-title"]', "h1"]);
    company = pick(['[data-test="employer-name"]', '[data-test="employerName"]']);
    loc = pick(['[data-test="location"]', '[data-test="emp-location"]']);
    description = pick(['[class*="JobDetails_jobDescription"]', "#JobDescriptionContainer"]);
  }

  if (!title) title = pick(["h1"]) || meta("og:title") || document.title;
  if (!company) company = meta("og:site_name") || host.replace(/^www\./, "").split(".")[0];
  if (!description) {
    const main = document.querySelector("article, main, [role='main']");
    description = main ? main.innerText.trim() : (meta("description") || document.body.innerText.trim());
  }

  return {
    title: title.slice(0, 200),
    company: company.slice(0, 120),
    location: loc.slice(0, 160),
    description: description.slice(0, 8000),
    url: location.href,
  };
}

// ---- Settings ----
async function getSettings() {
  const s = await ext.storage.local.get(["server", "token", "cfid", "cfsecret"]);
  return {
    server: (s.server || DEFAULT_SERVER).replace(/\/$/, ""),
    token: s.token || "",
    cfid: s.cfid || "",
    cfsecret: s.cfsecret || "",
  };
}

function updateCfgDot(hasToken) {
  $("cfg-dot").classList.toggle("on", !!hasToken);
}

async function saveSettings() {
  const server = ($("server").value.trim() || DEFAULT_SERVER).replace(/\/$/, "");
  const token = $("token").value.trim();
  await ext.storage.local.set({
    server, token,
    cfid: $("cfid").value.trim(),
    cfsecret: $("cfsecret").value.trim(),
  });
  // Best-effort: ask for permission to reach a custom (non-localhost) server.
  // Never let this break saving — it's wrapped and optional.
  try {
    const origin = new URL(server).origin + "/*";
    if (ext.permissions && ext.permissions.request) {
      await ext.permissions.request({ origins: [origin] });
    }
  } catch (e) { /* ignore */ }
  updateCfgDot(!!token);
}

function authHeaders(s) {
  const h = { "Content-Type": "application/json" };
  if (s.token) h["Authorization"] = "Bearer " + s.token;
  if (s.cfid && s.cfsecret) {
    h["CF-Access-Client-Id"] = s.cfid;
    h["CF-Access-Client-Secret"] = s.cfsecret;
  }
  return h;
}

async function testConnection() {
  const m = $("settings-msg");
  m.className = "smsg"; m.textContent = "Testing…";
  const s = await getSettings();
  try {
    const res = await fetch(`${s.server}/api/jobs`, { headers: authHeaders(s) });
    if (res.status === 200) { m.className = "smsg ok"; m.textContent = "✓ Connected — token works"; }
    else if (res.status === 401) { m.className = "smsg err"; m.textContent = "Reached server, but token is invalid"; }
    else { m.className = "smsg err"; m.textContent = "Server responded " + res.status; }
  } catch (e) {
    m.className = "smsg err"; m.textContent = "Couldn't reach the server";
  }
}

// ---- Save the scraped job ----
async function saveJob() {
  const btn = $("save");
  const msg = $("msg");
  msg.className = "msg"; msg.textContent = "";
  btn.disabled = true; btn.textContent = "Saving…";

  const s = await getSettings();
  const payload = {
    title: $("title").value.trim(),
    company: $("company").value.trim(),
    location: $("location").value.trim(),
    description: $("description").value.trim(),
    url: window._url || "",
    status: "saved",
    source: "extension",
  };

  try {
    const res = await fetch(`${s.server}/api/jobs`, {
      method: "POST",
      headers: authHeaders(s),
      body: JSON.stringify(payload),
    });
    if (res.status === 401) throw new Error("unauthorized");
    if (!res.ok) throw new Error("bad status " + res.status);
    msg.className = "msg ok"; msg.textContent = "✓ Saved to your tracker!";
    btn.textContent = "Saved";
    setTimeout(() => window.close(), 900);
  } catch (e) {
    msg.className = "msg err";
    msg.textContent = e.message === "unauthorized"
      ? "Auth failed — check your API token in settings."
      : "Couldn't reach tracker. Is the server running?";
    btn.disabled = false; btn.textContent = "Save to tracker";
  }
}

// ---- Init ----
async function init() {
  const s = await getSettings();
  $("server").value = s.server;
  $("token").value = s.token;
  $("cfid").value = s.cfid;
  $("cfsecret").value = s.cfsecret;
  updateCfgDot(!!s.token);

  // First-run convenience: if there's no token yet, open settings and nudge.
  if (!s.token) {
    $("settings").open = true;
    const m = $("settings-msg");
    m.className = "smsg"; m.textContent = "Add your API token, then Save settings.";
  }

  try {
    const [tab] = await ext.tabs.query({ active: true, currentWindow: true });
    const [result] = await ext.scripting.executeScript({ target: { tabId: tab.id }, func: scrapeJobPage });
    const data = result.result;
    $("title").value = data.title || "";
    $("company").value = data.company || "";
    $("location").value = data.location || "";
    $("description").value = data.description || "";
    window._url = data.url || tab.url;
    $("scrape-status").textContent = "✓ page read";
  } catch (e) {
    $("scrape-status").textContent = "couldn't read page";
    window._url = "";
  }
}

$("save").addEventListener("click", saveJob);
$("save-settings").addEventListener("click", async () => {
  await saveSettings();
  const m = $("settings-msg");
  m.className = "smsg ok"; m.textContent = "Saved ✓";
});
$("test-conn").addEventListener("click", testConnection);
init();
