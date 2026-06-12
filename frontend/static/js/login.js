  const $ = id => document.getElementById(id);
  const msg = $("msg");
  let tagline = "Sign in to your board.";
  function setMsg(t, ok){ msg.textContent = t; msg.className = "msg " + (ok ? "ok" : "err"); }
  function show(view){
    ["login","request","setup"].forEach(v => $("view-"+v).classList.toggle("hidden", v!==view));
    setMsg("");
    if (view==="setup") $("sub").textContent = "Welcome — create the first admin account.";
    else if (view==="request") $("sub").textContent = "Request access. An admin will review it.";
    else $("sub").textContent = tagline;
  }

  async function init(){
    try {
      const me = await (await fetch("/api/me")).json();
      if (me.instance_name) { $("brand-name").textContent = me.instance_name; document.title = me.instance_name; }
      if (me.logo_url) $("brand-logo").innerHTML = '<img src="'+me.logo_url+'" alt="" />';
      else if (me.instance_logo) $("brand-logo").textContent = me.instance_logo;
      if (me.instance_tagline) tagline = me.instance_tagline;
      if (me.authenticated) { window.location = "/"; return; }
      show(me.needs_setup ? "setup" : "login");
    } catch(e){ show("login"); }
  }

  async function post(url, body){
    const res = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
    let data = {}; try { data = await res.json(); } catch(e){}
    return { ok: res.ok, status: res.status, data };
  }

  $("li-go").onclick = async () => {
    $("li-go").disabled = true;
    const r = await post("/api/login", {email:$("li-email").value.trim(), password:$("li-pass").value});
    if (r.ok) { window.location = "/"; return; }
    setMsg(r.data.detail || "Sign in failed.");
    $("li-go").disabled = false;
  };
  $("li-pass").addEventListener("keydown", e => { if (e.key==="Enter") $("li-go").click(); });

  $("rq-go").onclick = async () => {
    $("rq-go").disabled = true;
    const r = await post("/api/request-access", {
      name:$("rq-name").value.trim(), email:$("rq-email").value.trim(),
      password:$("rq-pass").value, note:$("rq-note").value.trim()
    });
    $("rq-go").disabled = false;
    if (r.ok) setMsg("Request submitted — you'll be able to sign in once an admin approves it.", true);
    else setMsg(r.data.detail || "Couldn't submit request.");
  };

  $("su-go").onclick = async () => {
    $("su-go").disabled = true;
    const r = await post("/api/setup", {email:$("su-email").value.trim(), name:$("su-name").value.trim(), password:$("su-pass").value});
    if (r.ok) { window.location = "/"; return; }
    setMsg(r.data.detail || "Setup failed.");
    $("su-go").disabled = false;
  };

  $("to-request").onclick = () => show("request");
  $("to-login").onclick = () => show("login");
  init();
