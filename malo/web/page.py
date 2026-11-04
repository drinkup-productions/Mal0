PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MalO</title>
<style>
:root{--bg:#14121d;--pan:#241f33;--bord:#3a3350;--fg:#e8e4f4;--mut:#8b85a3;--acc:#8b5cf6}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;
 display:flex;flex-direction:column;height:100vh}
header{display:flex;gap:6px;padding:8px;background:var(--pan);border-bottom:1px solid var(--bord);
 align-items:center;flex-wrap:wrap}
select,button,input,textarea{font:inherit;color:var(--fg);background:var(--pan);
 border:1px solid var(--bord);border-radius:8px;padding:7px 10px}
button{background:var(--acc);border-color:var(--acc);font-weight:600}
button.ghost{background:var(--pan);border-color:var(--bord);font-weight:400}
#av{height:38vh;max-height:340px;object-fit:contain;display:block;margin:0 auto;padding:6px}
#log{flex:1;overflow-y:auto;padding:8px 10px;white-space:pre-wrap;word-wrap:break-word}
.u{background:var(--acc);color:#fff;border-radius:10px;padding:6px 9px;margin:6px 0 6px auto;
 max-width:85%;width:fit-content}
.b{background:var(--pan);border-radius:10px;padding:6px 9px;margin:6px 0;max-width:92%;width:fit-content}
.s{color:var(--mut);text-align:center;font-size:13px;margin:6px 0}
.t{color:#9ecbff;font-family:ui-monospace,monospace;font-size:12px;margin:2px 0}
.o{color:#b9c6dd;font-family:ui-monospace,monospace;font-size:11px;margin:0 0 2px 14px}
.e{color:#ffb4b4;font-family:ui-monospace,monospace;font-size:11px;margin:0 0 2px 14px}
footer{display:flex;gap:6px;padding:8px;background:var(--pan);border-top:1px solid var(--bord)}
#inp{flex:1;resize:none;height:44px}
#bar{display:none;gap:6px;padding:8px;background:#3a2f10;color:#ffd479;align-items:center}
</style></head><body>
<header>
 <select id="pro" title="workspace profile"></select>
 <select id="per"></select>
 <select id="mod"></select>
 <button class="ghost" id="pat">headpat</button>
 <button class="ghost" id="treat">treat</button>
 <button class="ghost" id="stop">stop</button>
</header>
<img id="av" alt="">
<div id="log"></div>
<div id="bar"><span id="bartxt"></span><span style="flex:1"></span>
 <button id="ok">Run</button><button class="ghost" id="skip">Skip</button></div>
<footer><textarea id="inp" placeholder="say something"></textarea><button id="send">Send</button></footer>
<script>
const T = new URLSearchParams(location.search).get("t") || "";
const $ = id => document.getElementById(id);
const log = $("log");
let pending = null, stage = 0, baseImg = "";

function el(cls, text){ const d = document.createElement("div"); d.className = cls;
  d.textContent = text; log.appendChild(d); log.scrollTop = log.scrollHeight; return d; }

async function api(path, body){
  const r = await fetch(path, {method:"POST", headers:{"X-Token":T,"Content-Type":"application/json"},
    body: JSON.stringify(body || {})});
  return r.ok ? r.json().catch(()=>({})) : {};
}

function paint(){
  if (!baseImg) return;
  const name = stage > 0 ? ["", "belly_larger.png","belly_full.png","belly_stuffed.png"][stage] : "";
  $("av").src = "/img?t=" + encodeURIComponent(T) + "&name=" + encodeURIComponent(name);
}

async function load(){
  const s = await (await fetch("/state?t=" + encodeURIComponent(T))).json();
  $("pro").innerHTML = "";
  for (const p of s.profiles){ const o = document.createElement("option");
    o.value = p.name; o.textContent = p.name; if (p.name === s.profile) o.selected = true;
    $("pro").appendChild(o); }
  $("per").innerHTML = "";
  for (const p of s.personas){ const o = document.createElement("option");
    o.value = p.id; o.textContent = p.label; if (p.id === s.active) o.selected = true;
    $("per").appendChild(o); }
  $("mod").innerHTML = "";
  for (const m of s.models){ const o = document.createElement("option");
    o.value = m; o.textContent = m; if (m === s.model) o.selected = true; $("mod").appendChild(o); }
  stage = s.stage; baseImg = s.active; paint();
}

$("pro").onchange = async e => { const r = await api("/profile", {name: e.target.value});
  if (r.workspace) el("s", "profile " + r.profile + " -> " + r.workspace); };
$("per").onchange = async e => { await api("/persona", {id: e.target.value}); stage = 0; load(); };
$("mod").onchange = e => api("/model", {value: e.target.value});
$("pat").onclick = () => api("/pat");
$("treat").onclick = async () => { const r = await api("/treat");
  if (typeof r.stage === "number"){ stage = r.stage; paint(); } };
$("stop").onclick = () => api("/stop");
$("ok").onclick = () => { api("/confirm", {ok:true}); $("bar").style.display = "none"; };
$("skip").onclick = () => { api("/confirm", {ok:false}); $("bar").style.display = "none"; };
$("send").onclick = send;
$("inp").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey){ e.preventDefault(); send(); } };

function send(){
  const text = $("inp").value.trim();
  if (!text) return;
  $("inp").value = "";
  api("/send", {text});
}

const es = new EventSource("/events?t=" + encodeURIComponent(T));
es.onmessage = e => {
  const ev = JSON.parse(e.data);
  if (ev.type === "delta"){
    if (log.lastChild && log.lastChild.classList.contains("b")) log.lastChild.textContent += ev.text;
    else el("b", ev.text);
    log.scrollTop = log.scrollHeight;
  } else if (ev.type === "think") el("s", ev.text);
  else if (ev.type === "tool") el("t", "> " + ev.name);
  else if (ev.type === "tool_result") el(ev.ok ? "o" : "e", ev.text);
  else if (ev.type === "confirm"){
    pending = ev.id; $("bartxt").textContent = "run " + ev.name + " " + JSON.stringify(ev.args).slice(0, 90);
    $("bar").style.display = "flex";
  } else if (ev.type === "turn"){ $("inp").focus(); }
  else if (ev.type === "error") el("s", "!! " + ev.text);
  else if (ev.type === "state") load();
};
load();
</script></body></html>
"""